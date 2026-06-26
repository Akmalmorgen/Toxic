"""
Анонимный бот: Анон.Вопрос / Валентинка + Чат-рулетка по полу + Магазин (коины, VIP) + Админка.
Стек: aiogram v3, sqlite3 (stdlib) / PostgreSQL (Neon).
"""

import os
import sqlite3
import logging
import random
import re
import string
import urllib.parse
import urllib.request
import json
import html
import asyncio
import threading
import contextvars
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramConflictError, TelegramForbiddenError
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated, PreCheckoutQuery, ErrorEvent,
    ReplyKeyboardRemove, ReplyParameters, BufferedInputFile, BotCommand,
    KeyboardButton as _AiKeyboardButton,
    ReplyKeyboardMarkup as _AiReplyKeyboardMarkup,
    InlineKeyboardButton as _AiInlineKeyboardButton,
    InlineKeyboardMarkup as _AiInlineKeyboardMarkup,
    LabeledPrice as _AiLabeledPrice,
)

# aiogram бросает свои исключения; даём привычное имя для существующих try/except.
TelegramError = TelegramAPIError


# ========================= ЯЗЫК ТЕКУЩЕГО АПДЕЙТА (task-safe) =========================
# Раньше это была глобальная переменная _CURLANG. aiogram обрабатывает апдейты
# конкурентно (каждый в своей asyncio-задаче), поэтому используем ContextVar —
# у каждой задачи свой изолированный язык, без гонок.
_lang_var = contextvars.ContextVar("cur_lang", default="ru")


def cur_lang():
    return _lang_var.get()


def set_cur_lang(value):
    _lang_var.set(value)


# ===================== PTB-совместимые фабрики поверх моделей aiogram =====================
# Конструкторы aiogram требуют именованные аргументы (text=, keyboard=, ...),
# а весь код ниже создаёт клавиатуры позиционно. Эти тонкие обёртки сохраняют
# привычный синтаксис и при этом возвращают настоящие модели aiogram.
def KeyboardButton(text, **kw):
    return _AiKeyboardButton(text=text, **kw)


class ReplyKeyboardMarkup(_AiReplyKeyboardMarkup):
    # Класс (а не функция), потому что в коде есть isinstance(..., ReplyKeyboardMarkup).
    def __init__(self, keyboard, resize_keyboard=False, one_time_keyboard=False, **kw):
        super().__init__(
            keyboard=keyboard,
            resize_keyboard=resize_keyboard,
            one_time_keyboard=one_time_keyboard,
            **kw,
        )


def InlineKeyboardButton(text, **kw):
    return _AiInlineKeyboardButton(text=text, **kw)


def InlineKeyboardMarkup(inline_keyboard, **kw):
    return _AiInlineKeyboardMarkup(inline_keyboard=inline_keyboard, **kw)


def LabeledPrice(label=None, amount=None, **kw):
    if label is not None:
        kw.setdefault("label", label)
    if amount is not None:
        kw.setdefault("amount", amount)
    return _AiLabeledPrice(**kw)


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather")


# ============================ ДВИЖОК aiogram + АДАПТЕРЫ ============================
# Один экземпляр Bot/Dispatcher на всё приложение. parse_mode не задаём по умолчанию,
# чтобы обычные сообщения не интерпретировались как HTML (HTML включается явно там,
# где это нужно — как и было в исходном коде).
bot = Bot(BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()


class _BotProxy:
    """Адаптер aiogram Bot под вызовы в стиле PTB, которые использует код ниже.

    Большинство методов проксируются как есть; переопределяем только то, где
    сигнатуры/типы aiogram отличаются:
      * send_message(..., reply_to_message_id=) -> reply_parameters
      * send_document(..., document=<файловый объект>) -> BufferedInputFile
    """

    def __init__(self, real_bot):
        self._bot = real_bot

    def __getattr__(self, name):
        return getattr(self._bot, name)

    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        if reply_to_message_id is not None:
            kw["reply_parameters"] = ReplyParameters(message_id=reply_to_message_id)
        return await self._bot.send_message(chat_id, text, **kw)

    async def send_document(self, chat_id, document=None, **kw):
        if hasattr(document, "read"):
            raw = document.read()
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            fname = os.path.basename(getattr(document, "name", "") or "file.txt")
            document = BufferedInputFile(raw, filename=fname)
        return await self._bot.send_document(chat_id, document, **kw)


BOTP = _BotProxy(bot)

# Хранилище пользовательских данных (аналог context.user_data из PTB) — в памяти,
# по одному словарю на пользователя. Сбрасывается при рестарте (как и было).
UD = defaultdict(dict)


def ud(uid):
    return UD[uid]


class _Msg:
    """Обёртка над aiogram Message с привычными PTB-методами (reply_text, chat_id)."""

    def __init__(self, message):
        self._m = message

    def __getattr__(self, name):
        return getattr(self._m, name)

    @property
    def chat_id(self):
        return self._m.chat.id

    async def reply_text(self, text, reply_markup=None, parse_mode=None,
                         reply_to_message_id=None, **kw):
        if reply_to_message_id is not None:
            kw["reply_parameters"] = ReplyParameters(message_id=reply_to_message_id)
        return await self._m.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, **kw)

    async def delete(self):
        return await self._m.delete()


class _CB:
    """Обёртка над aiogram CallbackQuery в стиле PTB (answer, edit_message_text)."""

    def __init__(self, cq):
        self._cq = cq
        self.data = cq.data
        self.from_user = cq.from_user
        self.message = _Msg(cq.message) if cq.message else None

    async def answer(self, text=None, show_alert=False, **kw):
        return await self._cq.answer(text=text, show_alert=show_alert, **kw)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        return await self._cq.message.edit_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode, **kw
        )

    async def edit_message_caption(self, caption=None, reply_markup=None, parse_mode=None, **kw):
        return await self._cq.message.edit_caption(
            caption=caption, reply_markup=reply_markup, parse_mode=parse_mode, **kw
        )


class UpdateShim:
    """Лёгкий аналог PTB Update: достаточно того, что реально используется в коде."""

    def __init__(self, message=None, callback_query=None, pre_checkout_query=None,
                 my_chat_member=None, effective_user=None, effective_chat=None):
        self.message = _Msg(message) if message is not None else None
        self.callback_query = callback_query
        self.pre_checkout_query = pre_checkout_query
        self.my_chat_member = my_chat_member
        self.effective_user = effective_user
        self.effective_chat = effective_chat


# Имена-заглушки для аннотаций в сигнатурах (update: Update, context: ContextTypes...).
Update = UpdateShim


class ContextTypes:
    DEFAULT_TYPE = object


class Ctx:
    """Аналог PTB context: .bot, .user_data, .args, .error."""

    def __init__(self, uid, args=None, error=None):
        self.bot = BOTP
        self.user_data = UD[uid]
        self.args = args or []
        self.error = error


DB_PATH = os.getenv("DB_PATH", "").strip() or os.path.join(os.path.dirname(__file__), "bot.db")
DAILY_LIMIT = 20
BAN_DAYS = 7
ROULETTE_BAN_DAYS = 30           # бан по жалобе из рулетки — на месяц
ANON_BAN_FOREVER = "9999-12-31T23:59:59"  # бан по жалобе из анонимки — навсегда (попарно)
ROULETTE_TICK_SECONDS = 3
LINK_CHANGE_COOLDOWN_DAYS = 7
VIP_DISCOUNT_PERCENT = 20   # скидка VIP в магазине, %
VIP_DAILY_BONUS = 5         # ежедневный бонус VIP, коинов

# === Подарок 18+ доступа другу ===
GIFT_18PLUS_PRICE = 567          # цена подарка 18+ (обычный пользователь), коинов
GIFT_18PLUS_PRICE_VIP = 456      # цена подарка 18+ для VIP (со скидкой), коинов
GIFT_18PLUS_DAYS = 30            # на сколько дней открывается 18+ доступ другу

# === Реферальные награды и бонусы за активность по ссылке ===
REF_REWARD_NORMAL = 20      # коинов за приглашённого друга (обычный)
REF_REWARD_VIP = 50         # коинов за приглашённого друга (VIP)
REF_VIP_THRESHOLD = 5       # друзей для бесплатного VIP
REF_VIP_DAYS = 7            # на сколько дней бесплатный VIP
REF_MODER_THRESHOLD = 10    # друзей для бесплатной модерки
REF_MODER_DAYS = 7          # на сколько дней бесплатная модерка
LINK_REWARD_EVERY = 10      # каждые N действий по ссылке
LINK_REWARD_COINS = 20      # коинов за каждые LINK_REWARD_EVERY действий

ADMIN_ACCESS_KEY = "next_toxic"   # секретный ключ доступа модера к админ-панели (выдаёт только создатель)
CREATOR_USERNAME = "@ToxIc_0707"  # к кому обращаться за ключом

# === Авто-обслуживание (джанитор) ===
INACTIVE_DAYS = 14          # порог неактивности
JANITOR_WAKE_HOURS = 6      # как часто просыпается фоновый джанитор
JANITOR_PERIOD_DAYS = 14    # раз в сколько дней выполнять удаление/уведомления

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("anon_bot")

DATABASE_URL = (
    os.getenv("DATABASE_URL", "").strip()
    or os.getenv("POSTGRES_URL", "").strip()
    or os.getenv("NEON_DATABASE_URL", "").strip()
)
USE_PG = bool(DATABASE_URL)


# === Слой совместимости БД: один и тот же код работает с sqlite и с PostgreSQL (Neon) ===
if USE_PG:
    import re as _re
    import psycopg2

    _pg_lock = threading.RLock()

    # Унифицированная строка результата: доступ и по имени row["col"], и по индексу row[0]
    class _Row(dict):
        def __init__(self, cols, vals):
            super().__init__(zip(cols, vals))
            self._vals = list(vals)
        def __getitem__(self, k):
            if isinstance(k, int):
                return self._vals[k]
            return dict.__getitem__(self, k)

    class _PgCursor:
        def __init__(self, raw):
            self._raw = raw
            self._cols = [d[0] for d in raw.description] if raw.description else []
            # Кэшируем все строки сразу, чтобы lastrowid и fetchone/fetchall не конкурировали
            try:
                self._rows = raw.fetchall() if raw.description else []
            except Exception:
                self._rows = []
            self._pos = 0
            # Вычисляем lastrowid из первой строки (RETURNING * возвращает вставленную запись)
            self._lastrowid = None
            if self._rows and "id" in self._cols:
                idx = self._cols.index("id")
                self._lastrowid = self._rows[0][idx]

        def fetchone(self):
            if self._pos >= len(self._rows):
                return None
            r = self._rows[self._pos]
            self._pos += 1
            return _Row(self._cols, r)

        def fetchall(self):
            rows = [_Row(self._cols, r) for r in self._rows[self._pos:]]
            self._pos = len(self._rows)
            return rows

        @property
        def lastrowid(self):
            return self._lastrowid

    # Перевод схемы sqlite -> Postgres (типы)
    def _translate_schema(script):
        s = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        s = _re.sub(r"\bINTEGER\b", "BIGINT", s)
        return s

    class _PgConnection:
        def __init__(self, url):
            self.url = url
            self._connect()
        def _connect(self):
            self._conn = psycopg2.connect(
                self.url, connect_timeout=30,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            )
            self._conn.autocommit = True
        def execute(self, sql, params=()):
            q = sql.replace("?", "%s")
            # INSERT без RETURNING -> добавляем RETURNING * (чтобы работал lastrowid)
            if sql.lstrip()[:6].upper() == "INSERT" and "returning" not in sql.lower():
                q = q.rstrip().rstrip(";") + " RETURNING *"
            with _pg_lock:
                for attempt in (1, 2):
                    try:
                        cur = self._conn.cursor()
                        cur.execute(q, params)
                        return _PgCursor(cur)
                    except (psycopg2.OperationalError, psycopg2.InterfaceError):
                        if attempt == 2:
                            raise
                        self._connect()  # потеряли соединение (Neon уснул) — переподключаемся
        def executescript(self, script):
            with _pg_lock:
                cur = self._conn.cursor()
                cur.execute(_translate_schema(script))
                return _PgCursor(cur)
        def commit(self):
            pass  # autocommit
        def cursor(self):
            return self  # для init_db: conn.cursor().executescript(...)

    conn = _PgConnection(DATABASE_URL)
    log.info("БД: PostgreSQL (Neon)")
else:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    log.info("БД: sqlite (%s)", DB_PATH)


def db():
    return conn



def init_db():
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        gender TEXT,
        search_pref TEXT,
        custom_link TEXT UNIQUE,
        link_changed_at TEXT,
        coins INTEGER NOT NULL DEFAULT 0,
        vip_until TEXT,
        is_moder INTEGER NOT NULL DEFAULT 0,
        is_banned INTEGER NOT NULL DEFAULT 0,
        last_bonus TEXT,
        lang TEXT NOT NULL DEFAULT 'ru',
        moder_until TEXT,
        link_sent_total INTEGER NOT NULL DEFAULT 0,
        link_answered_total INTEGER NOT NULL DEFAULT 0,
        link_sent_rewarded INTEGER NOT NULL DEFAULT 0,
        link_answered_rewarded INTEGER NOT NULL DEFAULT 0,
        ref_vip_claims INTEGER NOT NULL DEFAULT 0,
        ref_moder_claims INTEGER NOT NULL DEFAULT 0,
        last_active TEXT,
        nudged_at TEXT,
        admin_unlocked INTEGER NOT NULL DEFAULT 0,
        age TEXT,
        age_consent INTEGER NOT NULL DEFAULT 0,
        eighteenplus_until TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS anon_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        msg_type TEXT NOT NULL,
        content_type TEXT NOT NULL,
        text TEXT,
        voice_file_id TEXT,
        answer_text TEXT,
        answer_voice_file_id TEXT,
        answered INTEGER NOT NULL DEFAULT 0,
        deleted INTEGER NOT NULL DEFAULT 0,
        parent_id INTEGER,
        owner_chat_message_id INTEGER,
        sender_chat_message_id INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        reported_id INTEGER NOT NULL,
        context TEXT NOT NULL,
        reason TEXT,
        ref_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        banned_id INTEGER NOT NULL,
        until TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS roulette_queue (
        user_id INTEGER PRIMARY KEY,
        gender TEXT NOT NULL,
        pref TEXT NOT NULL,
        is_vip INTEGER NOT NULL DEFAULT 0,
        mode TEXT NOT NULL DEFAULT 'normal',
        actual_age INTEGER,
        age_min INTEGER,
        age_max INTEGER,
        joined_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS roulette_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        ended_by INTEGER,
        mode TEXT NOT NULL DEFAULT 'normal',
        started_at TEXT NOT NULL,
        ended_at TEXT
    );
    CREATE TABLE IF NOT EXISTS shop_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        price INTEGER NOT NULL,
        is_vip INTEGER NOT NULL DEFAULT 0,
        duration_days INTEGER,
        reward_type TEXT NOT NULL DEFAULT 'manual',
        reward_amount INTEGER,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        price_paid INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS mandatory_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_username TEXT NOT NULL,
        title TEXT
    );
    CREATE TABLE IF NOT EXISTS ad_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        text TEXT,
        button_text TEXT,
        button_url TEXT
    );

    CREATE TABLE IF NOT EXISTS moder_apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_id INTEGER,
        price_paid INTEGER NOT NULL DEFAULT 0,
        gender TEXT,
        age TEXT,
        tg_time TEXT,
        availability TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS star_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        title_uz TEXT,
        title_en TEXT,
        coins INTEGER NOT NULL,
        price_stars INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS star_purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        package_id INTEGER,
        coins INTEGER NOT NULL,
        stars INTEGER NOT NULL,
        charge_id TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL UNIQUE,
        coins_awarded INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    -- Состояние незавершённого анона по ссылке (переживает рестарт бота).
    CREATE TABLE IF NOT EXISTS link_flow (
        user_id INTEGER PRIMARY KEY,
        target_id INTEGER NOT NULL,
        msg_type TEXT,
        state TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    -- 18+ магазин товаров
    CREATE TABLE IF NOT EXISTS eighteen_plus_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        title_uz TEXT,
        title_en TEXT,
        description TEXT,
        price INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    -- Заявки на подтверждение возраста (для пользователей <18)
    CREATE TABLE IF NOT EXISTS age_verification_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        photo_file_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_response TEXT,
        created_at TEXT NOT NULL,
        responded_at TEXT
    );
    -- Произвольные настройки (редактируемые админом): ключ -> значение.
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    conn.commit()
    migrate()


def migrate():
    """Безопасно добавляет недостающие колонки в уже существующую БД."""
    alters = [
        "ALTER TABLE users ADD COLUMN first_name TEXT",
        "ALTER TABLE users ADD COLUMN is_moder INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_bonus TEXT",
        "ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT 'ru'",
        "ALTER TABLE anon_messages ADD COLUMN parent_id INTEGER",
        "ALTER TABLE shop_items ADD COLUMN reward_type TEXT NOT NULL DEFAULT 'manual'",
        "ALTER TABLE shop_items ADD COLUMN reward_amount INTEGER",
        "ALTER TABLE shop_items ADD COLUMN title_uz TEXT",
        "ALTER TABLE shop_items ADD COLUMN title_en TEXT",
        "ALTER TABLE users ADD COLUMN moder_until TEXT",
        "ALTER TABLE users ADD COLUMN link_sent_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN link_answered_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN link_sent_rewarded INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN link_answered_rewarded INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ref_vip_claims INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ref_moder_claims INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_active TEXT",
        "ALTER TABLE users ADD COLUMN nudged_at TEXT",
        "ALTER TABLE users ADD COLUMN admin_unlocked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN age TEXT",
        "ALTER TABLE users ADD COLUMN age_consent INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN eighteenplus_until TEXT",
        "ALTER TABLE mandatory_channels ADD COLUMN title TEXT",
        "ALTER TABLE roulette_queue ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE roulette_queue ADD COLUMN actual_age INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN age_min INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN age_max INTEGER",
        "ALTER TABLE roulette_sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE shop_items ADD COLUMN is_18plus INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE star_packages ADD COLUMN title_uz TEXT",
        "ALTER TABLE star_packages ADD COLUMN title_en TEXT",
    ]
    for sql in alters:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # колонка уже существует (sqlite или postgres)
    conn.commit()


def now_iso():
    return datetime.utcnow().isoformat()


def now_dt():
    return datetime.utcnow()


# === Настройки (редактируемые админом) ===
def get_setting(key, default=None):
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    except Exception:
        return default
    return row["value"] if row and row["value"] is not None else default


def get_setting_int(key, default):
    try:
        return int(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def set_setting(key, value):
    conn.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()


# Динамические значения реферальных наград (с откатом к константам по умолчанию)
def cfg_vip_days():        return get_setting_int("ref_vip_days", REF_VIP_DAYS)
def cfg_vip_threshold():   return max(1, get_setting_int("ref_vip_threshold", REF_VIP_THRESHOLD))
def cfg_moder_days():      return get_setting_int("ref_moder_days", REF_MODER_DAYS)
def cfg_moder_threshold(): return max(1, get_setting_int("ref_moder_threshold", REF_MODER_THRESHOLD))


def touch_user(uid):
    """Отмечает активность пользователя (для джанитора). Пишем не чаще раза в час."""
    try:
        u = get_user(uid)
        if not u:
            return
        la = u["last_active"]
        if la:
            try:
                if now_dt() - datetime.fromisoformat(la) < timedelta(hours=1):
                    return
            except (ValueError, TypeError):
                pass
        conn.execute("UPDATE users SET last_active=? WHERE tg_id=?", (now_iso(), uid))
        conn.commit()
    except Exception:
        pass



def get_user(tg_id):
    return conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def resolve_user_ref(text):
    """Находит пользователя по числовому tg_id или по @username (он должен быть в боте).
    Возвращает tg_id или None."""
    if not text:
        return None
    s = text.strip()
    if s.isdigit():
        u = get_user(int(s))
        return u["tg_id"] if u else None
    # @username — ищем в нашей базе (без учёта регистра)
    uname = s.lstrip("@").strip().lower()
    if not uname:
        return None
    row = conn.execute("SELECT tg_id FROM users WHERE LOWER(username)=?", (uname,)).fetchone()
    return row["tg_id"] if row else None


def ensure_user(tg_id, username, first_name=None):
    u = get_user(tg_id)
    if u is None:
        conn.execute(
            "INSERT INTO users (tg_id, username, first_name, coins, created_at) VALUES (?, ?, ?, 0, ?)",
            (tg_id, username, first_name, now_iso()),
        )
        conn.commit()
        u = get_user(tg_id)
    else:
        if u["username"] != username:
            conn.execute("UPDATE users SET username=? WHERE tg_id=?", (username, tg_id))
        if first_name and u["first_name"] != first_name:
            conn.execute("UPDATE users SET first_name=? WHERE tg_id=?", (first_name, tg_id))
        conn.commit()
        u = get_user(tg_id)
    return u


def is_moder(user_row):
    if not user_row:
        return False
    if user_row["is_moder"]:
        return True
    # Временная модерка (например, награда за рефералов) — действует до moder_until
    try:
        mu = user_row["moder_until"]
        if mu and datetime.fromisoformat(mu) > now_dt():
            return True
    except (KeyError, IndexError, ValueError, TypeError):
        pass
    return False


def is_staff(tg_id):
    """Админ или модератор."""
    if is_admin(tg_id):
        return True
    u = get_user(tg_id)
    return is_moder(u)


def is_banned(user_row):
    return bool(user_row) and bool(user_row["is_banned"])


def user_mention(user_row):
    """Кликабельная ссылка на пользователя: @username или ID через tg://."""
    if not user_row:
        return "—"
    name = user_row["first_name"] or "пользователь"
    if user_row["username"]:
        return f"{name} (@{user_row['username']})"
    return f'<a href="tg://user?id={user_row["tg_id"]}">{html.escape(name)}</a> (ID: {user_row["tg_id"]})'


def is_vip(user_row):
    if not user_row:
        return False
    # Админы и модеры — VIP навсегда, без ограничений
    try:
        if is_admin(user_row["tg_id"]) or is_moder(user_row):
            return True
    except (KeyError, TypeError):
        pass
    if not user_row["vip_until"]:
        return False
    try:
        return datetime.fromisoformat(user_row["vip_until"]) > now_dt()
    except ValueError:
        return False


def is_admin(tg_id):
    return tg_id in ADMIN_IDS


def user_age_int(user_row):
    """Возраст пользователя как число (или None, если не задан/нечисловой)."""
    try:
        a = user_row["age"]
    except (KeyError, IndexError, TypeError):
        return None
    if a is None:
        return None
    s = str(a).strip()
    return int(s) if s.isdigit() else None


def is_adult(user_row):
    """True, если возраст задан и >= 18 (доступ к 18+)."""
    a = user_age_int(user_row)
    return a is not None and a >= 18


def is_eighteenplus_active(user_row):
    """True, если у пользователя есть активный (купленный) доступ к 18+ чату.
    У админа — всегда. Модерам тоже даём (для проверки)."""
    if not user_row:
        return False
    try:
        if is_admin(user_row["tg_id"]) or is_moder(user_row):
            return True
    except (KeyError, IndexError, TypeError):
        pass
    try:
        v = user_row["eighteenplus_until"]
    except (KeyError, IndexError, TypeError):
        return False
    if not v:
        return False
    try:
        return datetime.fromisoformat(v) > now_dt()
    except (ValueError, TypeError):
        return False


# Диапазоны поиска по возрасту в 18+ рулетке: метка кнопки -> (мин, макс)
AGE_SEARCH_RANGES = {
    "18/20": (18, 20), "20/22": (20, 22), "22/24": (22, 24),
    "24/26": (24, 26), "26/28": (26, 28), "28/30": (28, 30),
    "30+": (30, 200),
}


def grant_18plus_access(uid, days):
    """Открывает пользователю доступ к 18+ чату на `days` дней (0 = навсегда). Продлевает текущий."""
    base = now_dt()
    u = get_user(uid)
    try:
        if u and u["eighteenplus_until"] and datetime.fromisoformat(u["eighteenplus_until"]) > now_dt():
            base = datetime.fromisoformat(u["eighteenplus_until"])
    except (KeyError, IndexError, ValueError, TypeError):
        base = now_dt()
    until = (base + timedelta(days=days)).isoformat() if (days and days > 0) else "9999-12-31T23:59:59"
    conn.execute("UPDATE users SET eighteenplus_until=?, age_consent=1 WHERE tg_id=?", (until, uid))
    conn.commit()


def has_admin_access(tg_id):
    """Доступ к админ-панели: настоящий админ ИЛИ модер, разблокировавший ключ доступа."""
    if is_admin(tg_id):
        return True
    u = get_user(tg_id)
    try:
        return bool(u) and is_moder(u) and bool(u["admin_unlocked"])
    except (KeyError, IndexError, TypeError):
        return False


def is_unlimited(user_row):
    """Админ или модер — безлимитный аккаунт: бесконечные коины, VIP навсегда, без лимитов."""
    if not user_row:
        return False
    try:
        return is_admin(user_row["tg_id"]) or is_moder(user_row)
    except (KeyError, TypeError):
        return False


# Условный «бесконечный» баланс для отображения у админа/модера
UNLIMITED_COINS = 10 ** 9


def has_forbidden_contacts(text):
    """True, если в тексте есть @юзернеймы, ссылки, домены, соцсети или длинные числа (ID/телефон).
    Используется для запрета обмена контактами/рекламы каналов в анонимках и рулетке."""
    if not text:
        return False
    low = text.lower()
    # @username
    if re.search(r'@[a-z][a-z0-9_]{2,}', low):
        return True
    # ссылки / приглашения в каналы
    if re.search(r'https?://|www\.|t\.me|telegram\.me|telegram\.dog|joinchat|tg://', low):
        return True
    # домены вида name.com / name.ru / name.uz и т.п.
    if re.search(r'\b[a-z0-9][a-z0-9-]*\.(com|ru|uz|net|org|io|me|info|biz|tv|app|link|site|online|club|store|xyz|kz)\b', low):
        return True
    # явные названия соцсетей/мессенджеров
    if re.search(r'\b(instagram|insta|tiktok|youtube|youtu|whatsapp|watsap|vatsap|facebook|snapchat|discord|onlyfans|vkontakte|тикток|инстаграм|ютуб|ватсап|вотсап)\b', low):
        return True
    # длинные числовые последовательности (ID Telegram / номер телефона): 7+ цифр подряд (с разделителями)
    for m in re.finditer(r'[\d\s\-()+]{7,}', text):
        if sum(c.isdigit() for c in m.group()) >= 7:
            return True
    return False


def gender_label(code):
    return {
        "m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
        "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"},
    }.get(code, {}).get(cur_lang(), "—")


def pref_label(code):
    return {
        "m": {"ru": "Парня", "uz": "Yigit", "en": "A guy"},
        "f": {"ru": "Девушку", "uz": "Qiz", "en": "A girl"},
        "any": {"ru": "Любого", "uz": "Farqi yo'q", "en": "Anyone"},
    }.get(code, {}).get(cur_lang(), "—")


def effective_price(price, user_row):
    """Цена с учётом VIP-скидки. У админа/модера — сниженная (со скидкой),
    но при покупке с них всё равно не списываются коины (см. do_purchase)."""
    if is_vip(user_row):
        return max(0, round(price * (100 - VIP_DISCOUNT_PERCENT) / 100))
    return price


async def try_delete_message(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


# ====================== СИСТЕМА ЯЗЫКОВ (Ру / Узб / Англ) ======================
LANGS = ("ru", "uz", "en")
LANG_BUTTONS = {"🇷🇺 Русский": "ru", "🇺🇿 O'zbekcha": "uz", "🇬🇧 English": "en"}

# Реестр кнопок: каноническая русская метка -> перевод (uz, en). Эмодзи одинаковые во всех языках.
BTN = {
    "🔗 Моя ссылка": ("🔗 Havolam", "🔗 My link"),
    "🎲 Чат-рулетка": ("🎲 Chat-ruletka", "🎲 Chat roulette"),
    "👤 Профиль": ("👤 Profil", "👤 Profile"),
    "🛒 Магазин": ("🛒 Do'kon", "🛒 Shop"),
    "👥 Пригласить": ("👥 Taklif qilish", "👥 Invite"),
    "ℹ️ Помощь": ("ℹ️ Yordam", "ℹ️ Help"),
    "🌐 Язык": ("🌐 Til", "🌐 Language"),
    "💎 Купить коины": ("💎 Coin sotib olish", "💎 Buy coins"),
    "🛠 Админка": ("🛠 Admin panel", "🛠 Admin"),
    "🛡 Модерка": ("🛡 Moderator", "🛡 Moderation"),
    "✅ Да": ("✅ Ha", "✅ Yes"),
    "❌ Отмена": ("❌ Bekor qilish", "❌ Cancel"),
    "💎 Коины": ("💎 Coinlar", "💎 Coins"),
    "⏳ VIP": ("⏳ VIP", "⏳ VIP"),
    "🛡 Модер": ("🛡 Moder", "🛡 Moder"),
    "📦 Вручную": ("📦 Qo'lda", "📦 Manual"),
    "📊 Статистика": ("📊 Statistika", "📊 Statistics"),
    "👑 VIP по ID": ("👑 ID bo'yicha VIP", "👑 VIP by ID"),
    "➕ Выдать VIP": ("➕ VIP berish", "➕ Grant VIP"),
    "➖ Забрать VIP": ("➖ VIP olish", "➖ Revoke VIP"),
    "🔞 18+ доступ: ВКЛ": ("🔞 18+ kirish: YONIQ", "🔞 18+ access: ON"),
    "🔞 18+ доступ: ВЫКЛ": ("🔞 18+ kirish: O'CHIQ", "🔞 18+ access: OFF"),
    "📤 Выгрузить пользователей": ("📤 Foydalanuvchilarni yuklash", "📤 Export users"),
    "💰 Начислить коины": ("💰 Coin qo'shish", "💰 Add coins"),
    "📢 Обязательные каналы": ("📢 Majburiy kanallar", "📢 Required channels"),
    "➕ Добавить канал": ("➕ Kanal qo'shish", "➕ Add channel"),
    "🗑 Удалить канал": ("🗑 Kanalni o'chirish", "🗑 Delete channel"),
    "✅ Сохранить": ("✅ Saqlash", "✅ Save"),
    "📣 Реклама": ("📣 Reklama", "📣 Ad"),
    "✉️ Рассылка": ("✉️ Xabar tarqatish", "✉️ Broadcast"),
    "📢 Рассылка": ("📢 Xabar tarqatish", "📢 Broadcast"),
    "🛡 Модеры": ("🛡 Moderatorlar", "🛡 Moderators"),
    "🔒 Отозвать доступ": ("🔒 Kirishni bekor qilish", "🔒 Revoke access"),
    "🔨 Бан / Разбан": ("🔨 Ban / Unban", "🔨 Ban / Unban"),
    "⭐ Коины за Stars": ("⭐ Stars uchun coin", "⭐ Coins for Stars"),
    "⬅️ Назад": ("⬅️ Orqaga", "⬅️ Back"),
    "🏠 Меню": ("🏠 Menyu", "🏠 Menu"),
    "➕ Добавить пакет коинов": ("➕ Coin paket qo'shish", "➕ Add coin package"),
    "🗑 Удалить пакет коинов": ("🗑 Coin paketni o'chirish", "🗑 Delete coin package"),
    "🚩 Жалобы": ("🚩 Shikoyatlar", "🚩 Reports"),
    "👨 Мужской": ("👨 Erkak", "👨 Male"),
    "👩 Женский": ("👩 Ayol", "👩 Female"),
    "🔗 Показать ссылку": ("🔗 Havolani ko'rsatish", "🔗 Show link"),
    "✏️ Сменить ссылку": ("✏️ Havolani o'zgartirish", "✏️ Change link"),
    "👨 Парня": ("👨 Yigit", "👨 A guy"),
    "👩 Девушку": ("👩 Qiz", "👩 A girl"),
    "🤷 Любого": ("🤷 Farqi yo'q", "🤷 Anyone"),
    "❓ Вопрос": ("❓ Savol", "❓ Question"),
    "💌 Валентинка": ("💌 Valentinka", "💌 Valentine"),
    "🤬 Мат": ("🤬 So'kinish", "🤬 Swearing"),
    "💰 Мошенничество": ("💰 Firibgarlik", "💰 Fraud"),
    "😡 Оскорбление": ("😡 Haqorat", "😡 Insult"),
    "🔞 18+ стикеры": ("🔞 18+ stikerlar", "🔞 18+ stickers"),
    "👎 Не нравится": ("👎 Yoqmadi", "👎 Dislike"),
    "✏️ Сменить пол": ("✏️ Jinsni o'zgartirish", "✏️ Change gender"),
    "👥 Всем": ("👥 Hammaga", "👥 Everyone"),
    "👨 Мужчинам": ("👨 Erkaklarga", "👨 To men"),
    "👩 Женщинам": ("👩 Ayollarga", "👩 To women"),
    "➕ Выдать модера": ("➕ Moder berish", "➕ Grant moder"),
    "➖ Забрать модера": ("➖ Moderni olish", "➖ Revoke moder"),
    "✏️ Изменить": ("✏️ O'zgartirish", "✏️ Edit"),
    "➕ Добавить товар": ("➕ Mahsulot qo'shish", "➕ Add item"),
    "🗑 Удалить товар": ("🗑 Mahsulotni o'chirish", "🗑 Delete item"),
    "📝 Название": ("📝 Nomi", "📝 Name"),
    "💰 Цена": ("💰 Narxi", "💰 Price"),
    "⏳ Срок VIP": ("⏳ VIP muddati", "⏳ VIP duration"),
    "💎 Сумма коинов": ("💎 Coin miqdori", "💎 Coin amount"),
    "🏆 Топ пригласивших": ("🏆 Top taklif qilganlar", "🏆 Top inviters"),
    "⛔ Отменить поиск": ("⛔ Qidiruvni bekor qilish", "⛔ Stop search"),
    "➡️ Далее": ("➡️ Keyingi", "➡️ Next"),
    "⏹️ Стоп": ("⏹️ To'xtatish", "⏹️ Stop"),
    "🔍 Новый поиск": ("🔍 Yangi qidiruv", "🔍 New search"),
    "🚩 Пожаловаться": ("🚩 Shikoyat qilish", "🚩 Report"),
    "📤 Отправить всем": ("📤 Hammaga yuborish", "📤 Send to all"),
    "🔞 18+": ("🔞 18+", "🔞 18+"),
    "🔞 18+ рулетка": ("🔞 18+ ruletka", "🔞 18+ roulette"),
    "🔞 Мне нет 18": ("🔞 18 yoshda emasman", "🔞 I'm under 18"),
    "🎁 Подарить 18+": ("🎁 18+ sovg'a qilish", "🎁 Gift 18+"),
    "🎁 Подарить коины": ("🎁 Coin sovg'a qilish", "🎁 Gift coins"),
    "🤷 Любой возраст": ("🤷 Istalgan yosh", "🤷 Any age"),
    "✅ Согласиться": ("✅ Roziman", "✅ I agree"),
    "✅ Подтвердить": ("✅ Tasdiqlash", "✅ Confirm"),
    "❌ Отклонить": ("❌ Rad etish", "❌ Reject"),
    "📷 Отправить фото": ("📷 Foto yuborish", "📷 Send photo"),
    "✏️ Изменить возраст": ("✏️ Yoshni o'zgartirish", "✏️ Change age"),
    "🛒 Обычный товар": ("🛒 Oddiy mahsulot", "🛒 Regular item"),
    "🔞 Товар 18+": ("🔞 18+ mahsulot", "🔞 18+ item"),
    "18+ рулетка": ("18+ ruletka", "18+ roulette"),
    "18+ магазин": ("18+ do'kon", "18+ shop"),
}
# Обратная карта: метка на любом языке -> каноническая русская метка
_ALIAS = {}
for _ru, (_uz, _en) in BTN.items():
    _ALIAS[_ru] = _ru
    _ALIAS[_uz] = _ru
    _ALIAS[_en] = _ru

# Текущий язык апдейта хранится в ContextVar (см. cur_lang()/set_cur_lang() вверху файла).


def get_lang(uid):
    try:
        u = get_user(uid)
        if u and u["lang"] in LANGS:
            return u["lang"]
    except Exception:
        pass
    return "ru"


def set_lang(uid, lang):
    conn.execute("UPDATE users SET lang=? WHERE tg_id=?", (lang, uid))
    conn.commit()


def canon(text):
    """Любая языковая метка кнопки -> каноническая русская (для маршрутизации).
    Убирает декоративные обрамления styled() перед поиском."""
    if text is None:
        return None
    # Убираем styled() обрамления
    t = text
    if t.startswith("⟡ ") and t.endswith(" ⟡"):
        t = t[2:-2]
    elif t.startswith("« ") and t.endswith(" »"):
        t = t[2:-2]
    return _ALIAS.get(t, _ALIAS.get(text, text))


# Стилизация кнопок — единый декор применяется после получения перевода
def styled(text, kind="default"):
    """Добавляет декоративное обрамление к тексту кнопки.
    kind: default — без изменений, premium — ⟡...⟡, accent — «...»"""
    if kind == "premium":
        return f"⟡ {text} ⟡"
    if kind == "accent":
        return f"« {text} »"
    return text


def tr_btn(ru_label, lang=None, kind="default"):
    """Перевод русской метки кнопки на текущий/заданный язык + стилизация."""
    lang = lang or cur_lang()
    if lang == "ru":
        base = ru_label
    else:
        pair = BTN.get(ru_label)
        if not pair:
            base = ru_label
        else:
            base = pair[0] if lang == "uz" else pair[1]
    return styled(base, kind) if kind != "default" else base


def tr_kb(markup, lang=None):
    """Переводит метки reply-клавиатуры на текущий язык, сохраняя структуру.
    Уже стилизованные кнопки (⟡/«») не переводятся повторно."""
    lang = lang or cur_lang()
    if lang == "ru" or not isinstance(markup, ReplyKeyboardMarkup):
        return markup
    new_rows = []
    for row in markup.keyboard:
        new_row = []
        for b in row:
            txt = b.text
            # Если кнопка уже стилизована — оставляем как есть
            if txt.startswith("⟡ ") or txt.startswith("« "):
                new_row.append(KeyboardButton(txt))
            else:
                new_row.append(KeyboardButton(tr_btn(canon(txt), lang)))
        new_rows.append(new_row)
    return ReplyKeyboardMarkup(
        new_rows,
        resize_keyboard=markup.resize_keyboard,
        one_time_keyboard=markup.one_time_keyboard,
    )


# Реестр переводов экранов/сообщений
T = {
    "main_menu": {
        "ru": "Главное меню 👇",
        "uz": "Asosiy menyu 👇",
        "en": "Main menu 👇",
    },
    "pick_on_kb": {
        "ru": "Выберите вариант на клавиатуре 👇",
        "uz": "Klaviaturadan variantni tanlang 👇",
        "en": "Please choose an option on the keyboard 👇",
    },
    "not_understood": {
        "ru": "Не понял команду. Воспользуйтесь меню 👇",
        "uz": "Buyruqni tushunmadim. Menyudan foydalaning 👇",
        "en": "I didn't get that. Please use the menu 👇",
    },
    "search_cancelled": {
        "ru": "Поиск отменён. Главное меню 👇",
        "uz": "Qidiruv bekor qilindi. Asosiy menyu 👇",
        "en": "Search cancelled. Main menu 👇",
    },
    # === Общие ===
    "banned": {
        "ru": "🚫 Вы заблокированы и не можете пользоваться ботом.",
        "uz": "🚫 Siz bloklangansiz va botdan foydalana olmaysiz.",
        "en": "🚫 You are blocked and cannot use the bot.",
    },
    "done": {
        "ru": "Готово.",
        "uz": "Tayyor.",
        "en": "Done.",
    },
    "enter_number": {
        "ru": "Введите число:",
        "uz": "Raqam kiriting:",
        "en": "Enter a number:",
    },
    "enter_days": {
        "ru": "Введите число дней:",
        "uz": "Kunlar sonini kiriting:",
        "en": "Enter the number of days:",
    },
    "choose_on_kb": {
        "ru": "Выберите 👇",
        "uz": "Tanlang 👇",
        "en": "Choose 👇",
    },
    # === Ссылка (доп.) ===
    "link_section": {
        "ru": "🔗 <b>Раздел «Моя ссылка»</b>\n\nВыберите действие 👇",
        "uz": "🔗 <b>«Havolam» bo'limi</b>\n\nAmalni tanlang 👇",
        "en": "🔗 <b>«My link» section</b>\n\nChoose an action 👇",
    },
    "link_show": {
        "ru": "✦ <b>Ваша персональная ссылка</b> ✦\n<blockquote>{link}</blockquote>\n📤 Нажми «Поделиться» — выбери, кому отправить, и тебе будут писать анонимно 💌",
        "uz": "✦ <b>Shaxsiy havolangiz</b> ✦\n<blockquote>{link}</blockquote>\n📤 «Ulashish» tugmasini bosing — kimga yuborishni tanlang, sizga anonim yozishadi 💌",
        "en": "✦ <b>Your personal link</b> ✦\n<blockquote>{link}</blockquote>\n📤 Tap «Share» — pick who to send it to, and people will message you anonymously 💌",
    },
    "link_done": {
        "ru": "✅ <b>Готово! Ваша ссылка</b> ✦\n<blockquote>{link}</blockquote>\n📤 Нажми «Поделиться», чтобы отправить её 💌",
        "uz": "✅ <b>Tayyor! Havolangiz</b> ✦\n<blockquote>{link}</blockquote>\n📤 Uni yuborish uchun «Ulashish» tugmasini bosing 💌",
        "en": "✅ <b>Done! Your link</b> ✦\n<blockquote>{link}</blockquote>\n📤 Tap «Share» to send it 💌",
    },
    "btn_share": {
        "ru": "✦ Поделиться",
        "uz": "✦ Ulashish",
        "en": "✦ Share",
    },
    "share_text": {
        "ru": "Напиши мне что-нибудь анонимно 👀",
        "uz": "Menga anonim biror narsa yozing 👀",
        "en": "Send me something anonymously 👀",
    },
    # === Анонимка (доп.) ===
    "anon_cancelled_menu": {
        "ru": "Отменено. Главное меню 👇",
        "uz": "Bekor qilindi. Asosiy menyu 👇",
        "en": "Cancelled. Main menu 👇",
    },
    # === Подписка (доп.) ===
    "sub_to_delete": {
        "ru": "Чтобы удалить сообщение, подпишись на канал(ы):\n\n",
        "uz": "Xabarni o'chirish uchun kanal(lar)ga obuna bo'ling:\n\n",
        "en": "To delete the message, subscribe to the channel(s):\n\n",
    },
    "sub_to_delete_short": {
        "ru": (
            "🔒 <b>Чтобы удалить сообщение — подпишись 👇</b>\n"
            "<i>Нажми на кнопки ниже, подпишись, вернись и нажми «✅ Проверить».</i>"
        ),
        "uz": (
            "🔒 <b>Xabarni o'chirish uchun — obuna bo'ling 👇</b>\n"
            "<i>Quyidagi tugmalarni bosing, obuna bo'ling, qayting va «✅ Tekshirish» ni bosing.</i>"
        ),
        "en": (
            "🔒 <b>To delete the message — subscribe 👇</b>\n"
            "<i>Tap the buttons below, subscribe, come back and press «✅ Check».</i>"
        ),
    },
    "btn_check_sub": {
        "ru": "✅ Проверить",
        "uz": "✅ Tekshirish",
        "en": "✅ Check",
    },
    "subgate_start": {
        "ru": (
            "🔒 <b>Чтобы пользоваться ботом — подпишись 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Нажми на кнопки ниже, подпишись, затем вернись и нажми «✅ Проверить».</i>"
        ),
        "uz": (
            "🔒 <b>Botdan foydalanish uchun — obuna bo'ling 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Quyidagi tugmalarni bosing, obuna bo'ling, keyin qaytib «✅ Tekshirish» ni bosing.</i>"
        ),
        "en": (
            "🔒 <b>To use the bot — subscribe 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Tap the buttons below, subscribe, then come back and press «✅ Check».</i>"
        ),
    },
    "link_limit_sub": {
        "ru": (
            "⏳ Менять ссылку можно раз в неделю (осталось {days} дн.).\n\n"
            "🔥 <b>Не хочешь ждать?</b> Подпишись на каналы ниже — и меняй ссылку <b>сколько хочешь, даже без VIP</b> 👇\n"
            "<i>После подписки снова нажми «✏️ Сменить ссылку».</i>"
        ),
        "uz": (
            "⏳ Havolani haftada bir marta o'zgartirish mumkin ({days} kun qoldi).\n\n"
            "🔥 <b>Kutishni xohlamaysizmi?</b> Quyidagi kanallarga obuna bo'ling — va havolani <b>xohlagancha, hatto VIPsiz</b> o'zgartiring 👇\n"
            "<i>Obunadan keyin yana «✏️ Havolani o'zgartirish» ni bosing.</i>"
        ),
        "en": (
            "⏳ You can change your link once a week ({days} days left).\n\n"
            "🔥 <b>Don't want to wait?</b> Subscribe to the channels below — and change your link <b>as often as you want, even without VIP</b> 👇\n"
            "<i>After subscribing, tap «✏️ Change link» again.</i>"
        ),
    },
    # === Профиль (доп.) ===
    "profile_full": {
        "ru": (
            "👤 <b>Ваш профиль</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Имя: <b>{name}</b>\n"
            "🚻 Пол: <b>{gender}</b>\n"
            "🎂 Возраст: <b>{age}</b>\n"
            "🎲 В чат-рулетке: <b>{roulette_time}</b>\n"
            "📤 Отправлено по ссылке: <b>{sent}</b>\n"
            "📥 Получено по ссылке: <b>{received}</b>\n"
            "👥 Приглашено друзей: <b>{invited}</b>\n"
            "🏆 Место в топе: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Коины: <b>{coins}</b>\n"
            "⭐ Потрачено звёзд (покупка коинов): <b>{stars}</b>\n"
            "📅 Регистрация: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "uz": (
            "👤 <b>Profilingiz</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Ism: <b>{name}</b>\n"
            "🚻 Jins: <b>{gender}</b>\n"
            "🎂 Yosh: <b>{age}</b>\n"
            "🎲 Chat-ruletkada: <b>{roulette_time}</b>\n"
            "📤 Havola orqali yuborilgan: <b>{sent}</b>\n"
            "📥 Havola orqali kelgan: <b>{received}</b>\n"
            "👥 Taklif qilingan do'stlar: <b>{invited}</b>\n"
            "🏆 Topdagi o'rin: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Coinlar: <b>{coins}</b>\n"
            "⭐ Sarflangan yulduzlar (coin xaridi): <b>{stars}</b>\n"
            "📅 Ro'yxatdan o'tgan: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "en": (
            "👤 <b>Your profile</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Name: <b>{name}</b>\n"
            "🚻 Gender: <b>{gender}</b>\n"
            "🎂 Age: <b>{age}</b>\n"
            "🎲 In chat roulette: <b>{roulette_time}</b>\n"
            "📤 Sent via link: <b>{sent}</b>\n"
            "📥 Received via link: <b>{received}</b>\n"
            "👥 Friends invited: <b>{invited}</b>\n"
            "🏆 Leaderboard place: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Coins: <b>{coins}</b>\n"
            "⭐ Stars spent (buying coins): <b>{stars}</b>\n"
            "📅 Registered: <b>{reg_date}</b>"
            "</blockquote>"
        ),
    },
    "vip_none": {"ru": "—", "uz": "—", "en": "—"},
    "profile_18plus_line": {
        "ru": "🔞 В 18+ чате: <b>{time}</b>",
        "uz": "🔞 18+ chatda: <b>{time}</b>",
        "en": "🔞 In 18+ chat: <b>{time}</b>",
    },
    "vip_until": {
        "ru": "до {date} 👑",
        "uz": "{date} gacha 👑",
        "en": "until {date} 👑",
    },
    "vip_forever": {
        "ru": "навсегда 👑",
        "uz": "abadiy 👑",
        "en": "forever 👑",
    },
    "you_were_banned": {
        "ru": "🚫 На вас поступила жалоба — на {days} дн. вы не сможете попасть к этому собеседнику в рулетке.",
        "uz": "🚫 Sizga shikoyat tushdi — {days} kun davomida ruletkada bu suhbatdoshga tusha olmaysiz.",
        "en": "🚫 You were reported — for {days} days you won't be matched with this person in roulette.",
    },
    "you_were_banned_forever": {
        "ru": "🚫 На вас поступила жалоба. Вы <b>навсегда</b> заблокированы для этого пользователя: писать ему нельзя. Другим — можно.",
        "uz": "🚫 Sizga shikoyat tushdi. Siz bu foydalanuvchi uchun <b>abadiy</b> bloklandingiz: unga yoza olmaysiz. Boshqalarga — mumkin.",
        "en": "🚫 You were reported. You are <b>permanently</b> blocked for this user: you can't message them. Others are fine.",
    },
    "anon_deleted_notice": {
        "ru": "🗑 Собеседник удалил своё анонимное сообщение.",
        "uz": "🗑 Suhbatdosh o'zining anonim xabarini o'chirdi.",
        "en": "🗑 The sender deleted their anonymous message.",
    },
    "no_contacts": {
        "ru": "🚫 Нельзя отправлять ссылки, @юзернеймы, номера, ID и упоминания соцсетей/каналов. Сообщение не отправлено.",
        "uz": "🚫 Havola, @username, raqam, ID va ijtimoiy tarmoq/kanal nomlarini yuborib bo'lmaydi. Xabar yuborilmadi.",
        "en": "🚫 You can't send links, @usernames, numbers, IDs or social/channel mentions. Message not sent.",
    },
    "cant_ban_staff": {
        "ru": "Нельзя забанить администратора или модератора. Жалоба отклонена.",
        "uz": "Administrator yoki moderatorni bloklab bo'lmaydi. Shikoyat rad etildi.",
        "en": "You can't ban an admin or moderator. The report was rejected.",
    },
    # === Рулетка (доп.) ===
    "roulette_who": {
        "ru": "🎲 Кого вы хотите найти?",
        "uz": "🎲 Kimni topmoqchisiz?",
        "en": "🎲 Who do you want to find?",
    },
    "roulette_chat_ended": {
        "ru": "Чат завершён ✅",
        "uz": "Chat yakunlandi ✅",
        "en": "Chat ended ✅",
    },
    "roulette_chat_stopped": {
        "ru": "Чат завершён.",
        "uz": "Chat yakunlandi.",
        "en": "Chat ended.",
    },
    "roulette_finding_new": {
        "ru": "Ищем нового собеседника… ⏳",
        "uz": "Yangi suhbatdosh qidirilmoqda… ⏳",
        "en": "Looking for a new partner… ⏳",
    },
    "roulette_already_short": {
        "ru": "Вы уже в чате.",
        "uz": "Siz allaqachon chatdasiz.",
        "en": "You are already in a chat.",
    },
    "roulette_finding_partner": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "session_not_found": {
        "ru": "Сессия не найдена.",
        "uz": "Sessiya topilmadi.",
        "en": "Session not found.",
    },
    "roulette_searching_new": {
        "ru": "Ищем нового собеседника...",
        "uz": "Yangi suhbatdosh qidirilmoqda...",
        "en": "Looking for a new partner...",
    },
    "btn_next": {
        "ru": "➡️ Далее",
        "uz": "➡️ Keyingi",
        "en": "➡️ Next",
    },
    "btn_stop": {
        "ru": "⏹️ Стоп",
        "uz": "⏹️ To'xtatish",
        "en": "⏹️ Stop",
    },
    "btn_new_search": {
        "ru": "🔍 Новый поиск",
        "uz": "🔍 Yangi qidiruv",
        "en": "🔍 New search",
    },
    "btn_complain": {
        "ru": "🚩 Пожаловаться",
        "uz": "🚩 Shikoyat qilish",
        "en": "🚩 Report",
    },

    # === Магазин (доп.) ===
    "shop_pick_item": {
        "ru": "Выберите товар на клавиатуре 👇",
        "uz": "Klaviaturadan mahsulotni tanlang 👇",
        "en": "Choose an item on the keyboard 👇",
    },
    "18plus_shop_pick_item": {
        "ru": "Выберите товар 18+ на клавиатуре 👇",
        "uz": "18+ mahsulotini klaviaturadan tanlang 👇",
        "en": "Choose a 18+ item on the keyboard 👇",
    },
    "item_unavailable": {
        "ru": "Товар недоступен.",
        "uz": "Mahsulot mavjud emas.",
        "en": "Item unavailable.",
    },
    "not_enough_coins": {
        "ru": "Недостаточно коинов 💎",
        "uz": "Coinlar yetarli emas 💎",
        "en": "Not enough coins 💎",
    },
    "shop_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» за {price}?",
        "uz": "«<b>{title}</b>»ni {price} ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» for {price}?",
    },
    "price_plain": {
        "ru": "<b>{price}</b> 💎",
        "uz": "<b>{price}</b> 💎",
        "en": "<b>{price}</b> 💎",
    },
    "price_vip": {
        "ru": "<b>{price}</b> 💎 (VIP-скидка, обычно {orig})",
        "uz": "<b>{price}</b> 💎 (VIP chegirma, odatda {orig})",
        "en": "<b>{price}</b> 💎 (VIP discount, usually {orig})",
    },
    "purchase_coins": {
        "ru": "✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b> 💎",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> <b>{amt}</b> 💎 qo'shildi",
        "en": "✅ <b>Purchase complete!</b> <b>{amt}</b> 💎 added",
    },
    "purchase_vip": {
        "ru": "✅ <b>Покупка совершена!</b> VIP активен на <b>{days}</b> дн. 👑",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> VIP <b>{days}</b> kun faol 👑",
        "en": "✅ <b>Purchase complete!</b> VIP active for <b>{days}</b> days 👑",
    },
    "purchase_manual": {
        "ru": "✅ <b>Покупка совершена!</b> Админ свяжется с вами и выдаст товар.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> Admin siz bilan bog'lanib, mahsulotni beradi.",
        "en": "✅ <b>Purchase complete!</b> The admin will contact you and deliver the item.",
    },
    "purchase_18plus": {
        "ru": "🔞 <b>Доступ к 18+ чату открыт на {days} дн.!</b> 🔥\nЗаходи в «🔞 18+ → 18+ рулетка» и общайся.",
        "uz": "🔞 <b>18+ chatga {days} kunga kirish ochildi!</b> 🔥\n«🔞 18+ → 18+ ruletka» ga kiring.",
        "en": "🔞 <b>18+ chat access granted for {days} days!</b> 🔥\nOpen «🔞 18+ → 18+ roulette» and chat.",
    },
    "purchase_18plus_forever": {
        "ru": "🔞 <b>Доступ к 18+ чату открыт навсегда!</b> 🔥\nЗаходи в «🔞 18+ → 18+ рулетка» и общайся.",
        "uz": "🔞 <b>18+ chatga abadiy kirish ochildi!</b> 🔥\n«🔞 18+ → 18+ ruletka» ga kiring.",
        "en": "🔞 <b>18+ chat access granted forever!</b> 🔥\nOpen «🔞 18+ → 18+ roulette» and chat.",
    },
    "eighteenplus_need_access": {
        "ru": (
            "🔒 <b>Нет доступа к 18+ чату</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Чтобы общаться в 18+ рулетке, купи доступ в <b>🔞 18+ магазине</b> 👇\n"
            "<i>Выбери товар с нужным сроком — доступ откроется сразу после покупки.</i>"
        ),
        "uz": (
            "🔒 <b>18+ chatga kirish yo'q</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "18+ ruletkada suhbatlashish uchun <b>🔞 18+ do'kondan</b> kirish sotib oling 👇\n"
            "<i>Kerakli muddatli mahsulotni tanlang — kirish darrov ochiladi.</i>"
        ),
        "en": (
            "🔒 <b>No access to the 18+ chat</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "To chat in the 18+ roulette, buy access in the <b>🔞 18+ shop</b> 👇\n"
            "<i>Pick an item with the duration you want — access opens right after purchase.</i>"
        ),
    },
    # === Подарки (18+ и коины) ===
    "gift18_ask_id": {
        "ru": (
            "🎁 <b>Подарить доступ 18+ другу</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Цена подарка: <b>{price}</b> 💎\n"
            "Срок доступа другу: <b>{days} дн.</b>\n\n"
            "Введите <b>Telegram ID</b> или <b>@username</b> друга, которому хотите подарить 👇\n"
            "<i>(друг должен быть запущен в боте)</i>"
        ),
        "uz": (
            "🎁 <b>Do'stga 18+ kirish sovg'a qilish</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Sovg'a narxi: <b>{price}</b> 💎\n"
            "Do'st uchun muddat: <b>{days} kun</b>\n\n"
            "Do'stning <b>Telegram ID</b> yoki <b>@username</b> ini kiriting 👇"
        ),
        "en": (
            "🎁 <b>Gift 18+ access to a friend</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Gift price: <b>{price}</b> 💎\n"
            "Access for friend: <b>{days} days</b>\n\n"
            "Enter the friend's <b>Telegram ID</b> or <b>@username</b> 👇"
        ),
    },
    "gift18_confirm": {
        "ru": "🎁 Подарить пользователю <code>{id}</code> доступ 18+ на <b>{days} дн.</b> за <b>{price}</b> 💎?",
        "uz": "🎁 <code>{id}</code> foydalanuvchiga <b>{days} kun</b>lik 18+ kirishni <b>{price}</b> 💎 ga sovg'a qilasizmi?",
        "en": "🎁 Gift user <code>{id}</code> 18+ access for <b>{days} days</b> for <b>{price}</b> 💎?",
    },
    "gift18_sent": {
        "ru": "✅ <b>Подарок отправлен!</b>\nПользователю <code>{id}</code> открыт доступ 18+ на {days} дн. 🎉",
        "uz": "✅ <b>Sovg'a yuborildi!</b>\n<code>{id}</code> ga 18+ {days} kunga ochildi 🎉",
        "en": "✅ <b>Gift sent!</b>\nUser <code>{id}</code> got 18+ access for {days} days 🎉",
    },
    "gift18_received": {
        "ru": "🎁 <b>Вам подарили доступ 18+!</b> 🔥\nОткрыт на <b>{days} дн.</b>\nЗаходи в «🔞 18+ → 18+ рулетка» 💋",
        "uz": "🎁 <b>Sizga 18+ kirish sovg'a qilindi!</b> 🔥\n<b>{days} kun</b>ga ochildi.\n«🔞 18+ → 18+ ruletka» ga kiring 💋",
        "en": "🎁 <b>You received 18+ access as a gift!</b> 🔥\nGranted for <b>{days} days</b>.\nOpen «🔞 18+ → 18+ roulette» 💋",
    },
    "gift_id_number": {
        "ru": "ID должен быть числом. Введите Telegram ID друга:",
        "uz": "ID raqam bo'lishi kerak. Do'stning Telegram ID sini kiriting:",
        "en": "ID must be a number. Enter the friend's Telegram ID:",
    },
    "gift_not_self": {
        "ru": "Нельзя подарить самому себе 🙂 Введите ID друга:",
        "uz": "O'zingizga sovg'a qila olmaysiz 🙂 Do'stning ID sini kiriting:",
        "en": "You can't gift yourself 🙂 Enter a friend's ID:",
    },
    "gift_user_not_found": {
        "ru": "Пользователь не найден (он должен быть запущен в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi (u botda bo'lishi kerak). ID yoki @username kiriting:",
        "en": "User not found (they must be in the bot). Enter ID or @username:",
    },
    "giftcoins_ask_id": {
        "ru": (
            "🎁 <b>Подарить коины другу</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Коины спишутся с твоего баланса и придут другу.\n\n"
            "Введите <b>Telegram ID</b> или <b>@username</b> друга 👇\n"
            "<i>(друг должен быть запущен в боте)</i>"
        ),
        "uz": (
            "🎁 <b>Do'stga coin sovg'a qilish</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coinlar balansingizdan yechiladi va do'stga o'tadi.\n\n"
            "Do'stning <b>Telegram ID</b> yoki <b>@username</b> ini kiriting 👇"
        ),
        "en": (
            "🎁 <b>Gift coins to a friend</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coins are deducted from your balance and go to your friend.\n\n"
            "Enter the friend's <b>Telegram ID</b> or <b>@username</b> 👇"
        ),
    },
    "giftcoins_ask_amount": {
        "ru": "💎 Сколько коинов подарить? (твой баланс: <b>{balance}</b> 💎)",
        "uz": "💎 Qancha coin sovg'a qilasiz? (balansingiz: <b>{balance}</b> 💎)",
        "en": "💎 How many coins to gift? (your balance: <b>{balance}</b> 💎)",
    },
    "giftcoins_amount_number": {
        "ru": "Введите положительное число коинов:",
        "uz": "Musbat coin sonini kiriting:",
        "en": "Enter a positive number of coins:",
    },
    "giftcoins_not_enough": {
        "ru": "Недостаточно коинов. Твой баланс: <b>{balance}</b> 💎. Введите меньшую сумму:",
        "uz": "Coin yetarli emas. Balansingiz: <b>{balance}</b> 💎. Kamroq summa kiriting:",
        "en": "Not enough coins. Your balance: <b>{balance}</b> 💎. Enter a smaller amount:",
    },
    "giftcoins_sent": {
        "ru": "✅ <b>Готово!</b> Подарено <b>{amount}</b> 💎 пользователю <code>{id}</code> 🎉",
        "uz": "✅ <b>Tayyor!</b> <code>{id}</code> ga <b>{amount}</b> 💎 sovg'a qilindi 🎉",
        "en": "✅ <b>Done!</b> Gifted <b>{amount}</b> 💎 to user <code>{id}</code> 🎉",
    },
    "giftcoins_received": {
        "ru": "🎁 <b>Вам подарили {amount} 💎!</b>\nКто-то перевёл тебе коины. Трать в магазине 🛒",
        "uz": "🎁 <b>Sizga {amount} 💎 sovg'a qilindi!</b>\nKimdir coin yubordi. Do'konda sarflang 🛒",
        "en": "🎁 <b>You received {amount} 💎 as a gift!</b>\nSomeone sent you coins. Spend in the shop 🛒",
    },
    # === Жалоба (доп., для пользователя) ===
    "report_confirmed_user": {
        "ru": "✅ Жалоба подтверждена. Этот пользователь не сможет беспокоить вас {days} дн.",
        "uz": "✅ Shikoyat tasdiqlandi. Bu foydalanuvchi sizni {days} kun bezovta qila olmaydi.",
        "en": "✅ Report confirmed. This user can't bother you for {days} days.",
    },
    "report_confirmed_forever": {
        "ru": "✅ Жалоба подтверждена. Этот пользователь больше <b>никогда</b> не сможет писать вам.",
        "uz": "✅ Shikoyat tasdiqlandi. Bu foydalanuvchi endi sizga <b>hech qachon</b> yoza olmaydi.",
        "en": "✅ Report confirmed. This user can <b>never</b> message you again.",
    },
    "report_rejected_user": {
        "ru": "Жалоба отклонена администратором.",
        "uz": "Shikoyat administrator tomonidan rad etildi.",
        "en": "The report was rejected by the administrator.",
    },
    "report_already_handled": {
        "ru": "Жалоба уже обработана.",
        "uz": "Shikoyat allaqachon ko'rib chiqilgan.",
        "en": "The report has already been handled.",
    },
    "report_confirmed_staff": {
        "ru": "Жалоба подтверждена, бан выдан ✅",
        "uz": "Shikoyat tasdiqlandi, ban berildi ✅",
        "en": "Report confirmed, ban issued ✅",
    },
    "report_rejected_staff": {
        "ru": "Жалоба отклонена ❌",
        "uz": "Shikoyat rad etildi ❌",
        "en": "Report rejected ❌",
    },
    "staff_only": {
        "ru": "Только для модерации.",
        "uz": "Faqat moderatorlar uchun.",
        "en": "Moderation only.",
    },
    "moder_form_gender": {
        "ru": "📝 <b>Анкета на модератора.</b>\n\nВаш пол?",
        "uz": "📝 <b>Moderatorlik anketasi.</b>\n\nJinsingiz?",
        "en": "📝 <b>Moderator application.</b>\n\nYour gender?",
    },
    "moder_form_age": {
        "ru": "Сколько вам лет?",
        "uz": "Yoshingiz nechada?",
        "en": "How old are you?",
    },
    "moder_form_tg": {
        "ru": "Сколько времени проводите в Telegram в день?",
        "uz": "Kuniga Telegramda qancha vaqt o'tkazasiz?",
        "en": "How much time do you spend on Telegram per day?",
    },
    "moder_form_avail": {
        "ru": "Сколько готовы уделять боту? Когда вы онлайн?",
        "uz": "Botga qancha vaqt ajrata olasiz? Qachon onlaynsiz?",
        "en": "How much time can you give the bot? When are you online?",
    },
    "moder_form_cancelled": {
        "ru": "Анкета отменена. Коины ({price} 💎) возвращены.",
        "uz": "Anketa bekor qilindi. Coinlar ({price} 💎) qaytarildi.",
        "en": "Application cancelled. Coins ({price} 💎) refunded.",
    },
    "moder_form_sent": {
        "ru": "✅ Анкета отправлена администратору. Ожидайте решения!",
        "uz": "✅ Anketa administratorga yuborildi. Qarorni kuting!",
        "en": "✅ Application sent to the administrator. Please wait for a decision!",
    },
    "moder_granted_user": {
        "ru": "🎉 Вам выдана роль модератора! В меню появилась кнопка «🛡 Модерка».",
        "uz": "🎉 Sizga moderator roli berildi! Menyuda «🛡 Moderator» tugmasi paydo bo'ldi.",
        "en": "🎉 You've been granted the moderator role! A «🛡 Moderation» button appeared in the menu.",
    },
    "moder_granted_shop": {
        "ru": "🎉 <b>Вы теперь Модер!</b> Добро пожаловать в команду.\nЗа бонусом напишите админу @ToxIc_0707 — он всё выдаст.",
        "uz": "🎉 <b>Endi siz Modersiz!</b> Jamoaga xush kelibsiz.\nBonus uchun @ToxIc_0707 adminiga yozing — u hammasini beradi.",
        "en": "🎉 <b>You're a Moder now!</b> Welcome to the team.\nFor a bonus, message the admin @ToxIc_0707 — he'll provide everything.",
    },
    "moder_rejected_user": {
        "ru": "К сожалению, заявка на модера отклонена. Коины ({coins} 💎) возвращены.",
        "uz": "Afsuski, moderlik arizasi rad etildi. Coinlar ({coins} 💎) qaytarildi.",
        "en": "Unfortunately, your moder application was rejected. Coins ({coins} 💎) refunded.",
    },
    "moder_taken_user": {
        "ru": "Роль модератора снята.",
        "uz": "Moderator roli olib tashlandi.",
        "en": "The moderator role has been removed.",
    },
    "admin_only": {
        "ru": "Только для админа.",
        "uz": "Faqat admin uchun.",
        "en": "Admin only.",
    },
    "cleanup_started": {
        "ru": "🧹 Очистка…",
        "uz": "🧹 Tozalash…",
        "en": "🧹 Cleanup…",
    },
    "cleanup_done": {
        "ru": "✅ Готово. Проверено: {checked}, удалено: {removed}",
        "uz": "✅ Tayyor. Tekshirildi: {checked}, o'chirildi: {removed}",
        "en": "✅ Done. Checked: {checked}, removed: {removed}",
    },
    "admin_vip_menu": {
        "ru": "👑 <b>Управление VIP по ID</b>\n\nВыдать или забрать VIP у пользователя 👇",
        "uz": "👑 <b>ID bo'yicha VIP boshqaruvi</b>\n\nFoydalanuvchiga VIP berish yoki olish 👇",
        "en": "👑 <b>VIP management by ID</b>\n\nGrant or revoke VIP for a user 👇",
    },
    "vip_ask_id": {
        "ru": "Введите <b>tg_id</b> или <b>@username</b> пользователя:",
        "uz": "Foydalanuvchining <b>tg_id</b> yoki <b>@username</b> ini kiriting:",
        "en": "Enter the user's <b>tg_id</b> or <b>@username</b>:",
    },
    "vip_ask_days": {
        "ru": "На сколько дней выдать VIP? (число)",
        "uz": "VIP necha kunga berilsin? (raqam)",
        "en": "For how many days to grant VIP? (number)",
    },
    "vip_id_number": {
        "ru": "ID должен быть числом. Попробуйте снова:",
        "uz": "ID raqam bo'lishi kerak. Qaytadan urinib ko'ring:",
        "en": "ID must be a number. Try again:",
    },
    "vip_days_number": {
        "ru": "Введите положительное число дней:",
        "uz": "Musbat kunlar sonini kiriting:",
        "en": "Enter a positive number of days:",
    },
    "vip_user_not_found": {
        "ru": "Пользователь не найден (он должен быть в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi (u botda bo'lishi kerak). ID yoki @username kiriting:",
        "en": "User not found (they must be in the bot). Enter ID or @username:",
    },
    "vip_granted_admin": {
        "ru": "✅ VIP выдан пользователю <code>{id}</code> на <b>{days}</b> дн.",
        "uz": "✅ <code>{id}</code> foydalanuvchiga VIP <b>{days}</b> kunga berildi.",
        "en": "✅ VIP granted to user <code>{id}</code> for <b>{days}</b> days.",
    },
    "vip_taken_admin": {
        "ru": "✅ VIP снят у пользователя <code>{id}</code>.",
        "uz": "✅ <code>{id}</code> foydalanuvchidan VIP olib tashlandi.",
        "en": "✅ VIP revoked from user <code>{id}</code>.",
    },
    "vip_granted_user": {
        "ru": "🎉 <b>Вам выдан VIP на {days} дней!</b> 👑\nНаслаждайтесь привилегиями.",
        "uz": "🎉 <b>Sizga {days} kunga VIP berildi!</b> 👑\nImtiyozlardan bahramand bo'ling.",
        "en": "🎉 <b>You've been granted VIP for {days} days!</b> 👑\nEnjoy the perks.",
    },
    "vip_taken_user": {
        "ru": "Ваш VIP-статус был снят администратором.",
        "uz": "VIP holatingiz administrator tomonidan olib tashlandi.",
        "en": "Your VIP status was revoked by the administrator.",
    },
    "adm_18plus_on": {
        "ru": "✅ <b>18+ доступ включён.</b> Раздел снова работает для всех совершеннолетних.",
        "uz": "✅ <b>18+ kirish yoqildi.</b> Bo'lim barcha kattalar uchun yana ishlaydi.",
        "en": "✅ <b>18+ access enabled.</b> The section works again for all adults.",
    },
    "adm_18plus_off": {
        "ru": "🚫 <b>18+ доступ выключен.</b> Кнопка остаётся видимой, но при входе пользователи увидят уведомление о недоступности.",
        "uz": "🚫 <b>18+ kirish o'chirildi.</b> Tugma ko'rinadi, lekin kirishda foydalanuvchilar mavjud emasligi haqida xabar ko'radi.",
        "en": "🚫 <b>18+ access disabled.</b> The button stays visible, but on entry users will see an unavailability notice.",
    },
    "18plus_disabled_notice": {
        "ru": "🔞 <b>Раздел 18+ временно недоступен</b>\n\nАдминистратор приостановил работу 18+ чата. Загляни позже 🙏",
        "uz": "🔞 <b>18+ bo'limi vaqtincha mavjud emas</b>\n\nAdministrator 18+ chatni to'xtatib qo'ydi. Keyinroq kiring 🙏",
        "en": "🔞 <b>The 18+ section is temporarily unavailable</b>\n\nThe administrator paused the 18+ chat. Check back later 🙏",
    },
    "moder_app_already": {
        "ru": "Заявка уже обработана.",
        "uz": "Ariza allaqachon ko'rib chiqilgan.",
        "en": "The application has already been handled.",
    },
    "moder_granted_staff": {
        "ru": "✅ Модерка выдана.",
        "uz": "✅ Moderlik berildi.",
        "en": "✅ Moderation granted.",
    },
    "moder_rejected_staff": {
        "ru": "❌ Заявка отклонена, коины возвращены.",
        "uz": "❌ Ariza rad etildi, coinlar qaytarildi.",
        "en": "❌ Application rejected, coins refunded.",
    },
    "gender_set_short": {
        "ru": "Пол сохранён: {g} ✅",
        "uz": "Jins saqlandi: {g} ✅",
        "en": "Gender saved: {g} ✅",
    },
    "ref_friend_joined": {
        "ru": "🎉 По твоей ссылке пришёл друг! Тебе начислено <b>+{reward}</b> 💎",
        "uz": "🎉 Havolangiz orqali do'st keldi! Sizga <b>+{reward}</b> 💎 qo'shildi",
        "en": "🎉 A friend joined via your link! You earned <b>+{reward}</b> 💎",
    },
    "referral_screen": {
        "ru": (
            "👥 <b>Приглашай друзей — зарабатывай коины!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "За каждого друга: <b>{reward}</b> 💎{bonus}\n"
            "Приглашено: <b>{total}</b>\n"
            "Заработано: <b>{earned}</b> 💎\n\n"
            "🔗 Твоя ссылка:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ Если друг заблокирует бота — коины за него спишутся обратно."
        ),
        "uz": (
            "👥 <b>Do'stlarni taklif qiling — coin ishlang!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Har bir do'st uchun: <b>{reward}</b> 💎{bonus}\n"
            "Taklif qilindi: <b>{total}</b>\n"
            "Ishlab topildi: <b>{earned}</b> 💎\n\n"
            "🔗 Havolangiz:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ Agar do'st botni bloklasa — uning coinlari qaytarib olinadi."
        ),
        "en": (
            "👥 <b>Invite friends — earn coins!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "For each friend: <b>{reward}</b> 💎{bonus}\n"
            "Invited: <b>{total}</b>\n"
            "Earned: <b>{earned}</b> 💎\n\n"
            "🔗 Your link:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ If a friend blocks the bot — their coins will be deducted back."
        ),
    },
    "referral_bonus_vip": {
        "ru": " 👑 (VIP-бонус)",
        "uz": " 👑 (VIP bonus)",
        "en": " 👑 (VIP bonus)",
    },
    "referral_bonus_normal": {
        "ru": " (у VIP — 50 💎)",
        "uz": " (VIP uchun — 50 💎)",
        "en": " (VIP gets 50 💎)",
    },
    "ref_rewards_title": {
        "ru": (
            "✦ <b>Награды за друзей</b> ✦\n"
            "Приведи друзей по ссылке (чтобы они создали свою ссылку) и забери:\n"
            "🎁 <b>VIP бесплатно</b> — за {vip_n} друзей ({vip_d} дн.)\n"
            "🛡 <b>Модерка на неделю</b> — за {mod_n} друзей ({mod_d} дн.)\n"
            "Жми кнопку, когда наберёшь 💕"
        ),
        "uz": (
            "✦ <b>Do'stlar uchun mukofotlar</b> ✦\n"
            "Havola orqali do'st taklif qiling (ular ham havola yaratsin) va oling:\n"
            "🎁 <b>Bepul VIP</b> — {vip_n} do'st uchun ({vip_d} kun)\n"
            "🛡 <b>Bir haftalik moder</b> — {mod_n} do'st uchun ({mod_d} kun)\n"
            "Yetkazganda tugmani bosing 💕"
        ),
        "en": (
            "✦ <b>Rewards for friends</b> ✦\n"
            "Invite friends via your link (they must create their own link) and claim:\n"
            "🎁 <b>Free VIP</b> — for {vip_n} friends ({vip_d} days)\n"
            "🛡 <b>Moderator for a week</b> — for {mod_n} friends ({mod_d} days)\n"
            "Tap a button once you reach it 💕"
        ),
    },
    "ref_claim_coins_btn": {
        "ru": "💎 {n} за друга · VIP {v} 💎",
        "uz": "💎 do'st uchun {n} · VIP {v} 💎",
        "en": "💎 {n} per friend · VIP {v} 💎",
    },
    "btn_share_ref": {
        "ru": "📤 Поделиться ссылкой",
        "uz": "📤 Havolani ulashish",
        "en": "📤 Share the link",
    },
    "ref_share_text": {
        "ru": "🔥 Залетай в анонимный бот! Тебе пишут тайно, чат-рулетка, подарки 🎁 Жми 👇",
        "uz": "🔥 Anonim botga kir! Sizga yashirin yozishadi, chat-ruletka, sovg'alar 🎁 Bosing 👇",
        "en": "🔥 Join the anonymous bot! Get secret messages, chat roulette, gifts 🎁 Tap 👇",
    },
    "ref_claim_vip_btn": {
        "ru": "🎁 VIP бесплатно ({have}/{need})",
        "uz": "🎁 Bepul VIP ({have}/{need})",
        "en": "🎁 Free VIP ({have}/{need})",
    },
    "ref_claim_moder_btn": {
        "ru": "🛡 Модерка на неделю ({have}/{need})",
        "uz": "🛡 Bir haftalik moder ({have}/{need})",
        "en": "🛡 Moderator for a week ({have}/{need})",
    },
    "ref_need_more": {
        "ru": "Нужно ещё {n} друзей (которые создали свою ссылку). Приглашено подходящих: {have}.",
        "uz": "Yana {n} ta do'st kerak (ular havola yaratgan bo'lishi kerak). Mos: {have}.",
        "en": "Need {n} more friends (who created their own link). Qualified: {have}.",
    },
    "ref_vip_granted": {
        "ru": "🎉 <b>VIP активирован на {days} дней</b> за приглашённых друзей! 👑",
        "uz": "🎉 <b>VIP {days} kunga faollashtirildi</b> — do'stlar uchun! 👑",
        "en": "🎉 <b>VIP activated for {days} days</b> for your invited friends! 👑",
    },
    "ref_moder_granted": {
        "ru": "🛡 <b>Модерка выдана на {days} дней</b> за {need} приглашённых друзей!\nПрочувствуй власть модератора 😎",
        "uz": "🛡 <b>Moderlik {days} kunga berildi</b> — {need} ta do'st uchun!\nModer kuchini his qiling 😎",
        "en": "🛡 <b>Moderator granted for {days} days</b> for {need} invited friends!\nFeel the power 😎",
    },
    "ref_info_alert": {
        "ru": "За каждого приглашённого друга: {n} 💎 (а если ты VIP — {v} 💎). Коины приходят автоматически, когда друг запускает бота.",
        "uz": "Har bir taklif qilingan do'st uchun: {n} 💎 (VIP bo'lsangiz — {v} 💎). Coinlar do'st botni ishga tushirganda avtomatik keladi.",
        "en": "For each invited friend: {n} 💎 (VIP gets {v} 💎). Coins arrive automatically when the friend starts the bot.",
    },
    "link_reward": {
        "ru": "🎁 <b>Бонус за активность по ссылке:</b> +{coins} 💎\nВсего действий: {n}. Так держать! 💕",
        "uz": "🎁 <b>Havola faolligi uchun bonus:</b> +{coins} 💎\nJami: {n}. Davom eting! 💕",
        "en": "🎁 <b>Activity bonus for your link:</b> +{coins} 💎\nTotal actions: {n}. Keep it up! 💕",
    },
    "ref_menu_hint": {
        "ru": "Меню «Пригласить» 👇",
        "uz": "«Taklif qilish» menyusi 👇",
        "en": "Invite menu 👇",
    },
    "mod_message": {
        "ru": "✉️ <b>Сообщение от модератора {name}</b>:\n{text}",
        "uz": "✉️ <b>{name} moderatordan xabar</b>:\n{text}",
        "en": "✉️ <b>Message from moderator {name}</b>:\n{text}",
    },
    "moder_help": {
        "ru": (
            "🛡 <b>Помощь по модерке</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Кнопки панели:</b>\n"
            "<blockquote>"
            "🚩 <b>Жалобы</b> — список жалоб, бан/отклонение\n"
            "🔨 <b>Бан / Разбан</b> — блок/разблок по ID\n"
            "📊 <b>Статистика</b> — цифры по боту\n"
            "📤 <b>Выгрузить пользователей</b> — список в .txt"
            "</blockquote>\n"
            "<b>Скрытые команды</b> (просто напиши в чат):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — мониторинг рулетки.\n"
            "Показывает активные сессии → введи ID участника → видишь их переписку вживую.\n"
            "Кнопки «🚫 Бан 1️⃣/2️⃣» — забанить. Когда сессия завершится — авто-переход к другой; «🚪 Выйти» — выйти.\n\n"
            "✉️ <b>/next</b> — написать любому пользователю.\n"
            "Введи ID → текст. Юзеру придёт «Сообщение от модератора <i>твоё имя</i>»."
            "</blockquote>\n"
            "ℹ️ <i>Сообщения и чаты могут проверяться для безопасности.</i>"
        ),
        "uz": (
            "🛡 <b>Moderator yordami</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel tugmalari:</b>\n"
            "<blockquote>"
            "🚩 <b>Shikoyatlar</b> — shikoyatlar ro'yxati\n"
            "🔨 <b>Ban / Unban</b> — ID bo'yicha blok/blokdan chiqarish\n"
            "📊 <b>Statistika</b> — bot raqamlari\n"
            "📤 <b>Foydalanuvchilarni yuklash</b> — .txt ro'yxat"
            "</blockquote>\n"
            "<b>Maxfiy buyruqlar</b> (chatga yozing):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — ruletka monitoringi. Faol sessiyalar → ishtirokchi ID sini kiriting → suhbatni jonli ko'rasiz. «🚫 Ban 1️⃣/2️⃣». «🚪 Chiqish».\n\n"
            "✉️ <b>/next</b> — istalgan foydalanuvchiga yozish. ID → matn."
            "</blockquote>\n"
            "ℹ️ <i>Xabarlar xavfsizlik uchun tekshirilishi mumkin.</i>"
        ),
        "en": (
            "🛡 <b>Moderator help</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel buttons:</b>\n"
            "<blockquote>"
            "🚩 <b>Reports</b> — review reports\n"
            "🔨 <b>Ban / Unban</b> — by ID\n"
            "📊 <b>Statistics</b> — bot numbers\n"
            "📤 <b>Export users</b> — .txt list"
            "</blockquote>\n"
            "<b>Hidden commands</b> (type in chat):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — roulette monitor. Active sessions → enter a participant ID → watch live. «🚫 Ban 1️⃣/2️⃣». «🚪 Exit».\n\n"
            "✉️ <b>/next</b> — message any user. ID → text."
            "</blockquote>\n"
            "ℹ️ <i>Messages and chats may be reviewed for safety.</i>"
        ),
    },
    "inactive_nudge": {
        "ru": (
            "👋 <b>Давно тебя не было в 𐌽ꤕ𐌗ተ!</b>\n"
            "⚠️ Чтобы не потерять свои данные (💎 коины, 👑 VIP, 🔗 ссылку) — "
            "просто нажми /start и загляни 🙂"
        ),
        "uz": (
            "👋 <b>Sizni 𐌽ꤕ𐌗ተ da ko'rmaganimizga ancha bo'ldi!</b>\n"
            "⚠️ Ma'lumotlaringizni (💎 coin, 👑 VIP, 🔗 havola) yo'qotmaslik uchun — "
            "/start ni bosing va kiring 🙂"
        ),
        "en": (
            "👋 <b>Haven't seen you in 𐌽ꤕ𐌗ተ for a while!</b>\n"
            "⚠️ So you don't lose your data (💎 coins, 👑 VIP, 🔗 link) — "
            "just tap /start and drop by 🙂"
        ),
    },
    "top_empty": {
        "ru": "Пока никто никого не пригласил. Будь первым! 🚀",
        "uz": "Hozircha hech kim hech kimni taklif qilmagan. Birinchi bo'ling! 🚀",
        "en": "No one has invited anyone yet. Be the first! 🚀",
    },
    "top_title": {
        "ru": "🏆 <b>Топ пригласивших</b>",
        "uz": "🏆 <b>Eng ko'p taklif qilganlar</b>",
        "en": "🏆 <b>Top inviters</b>",
    },
    "ref_coins_refunded": {
        "ru": "⚠️ Приглашённый друг заблокировал бота — <b>{n}</b> 💎 списаны обратно.",
        "uz": "⚠️ Taklif qilingan do'st botni blokladi — <b>{n}</b> 💎 qaytarib olindi.",
        "en": "⚠️ Your invited friend blocked the bot — <b>{n}</b> 💎 deducted back.",
    },
    "stars_unavailable": {
        "ru": "Покупка коинов пока недоступна.",
        "uz": "Coin sotib olish hozircha mavjud emas.",
        "en": "Buying coins is not available yet.",
    },
    "stars_pick_pkg": {
        "ru": "Выбери пакет на клавиатуре 👇",
        "uz": "Klaviaturadan paketni tanlang 👇",
        "en": "Choose a package on the keyboard 👇",
    },
    "pkg_unavailable": {
        "ru": "Пакет недоступен.",
        "uz": "Paket mavjud emas.",
        "en": "Package unavailable.",
    },
    "stars_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» ({coins} 💎) за <b>⭐{stars}</b>?",
        "uz": "«<b>{title}</b>» ({coins} 💎) ni <b>⭐{stars}</b> ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» ({coins} 💎) for <b>⭐{stars}</b>?",
    },
    "stars_invoice_sent": {
        "ru": "💳 Счёт выставлен ниже. Оплати кнопкой или вернись в меню 👇",
        "uz": "💳 Hisob-faktura quyida. Tugma orqali to'lang yoki menyuga qayting 👇",
        "en": "💳 The invoice is below. Pay with the button or return to the menu 👇",
    },
    "stars_pkg_desc": {
        "ru": "{coins} коинов для бота",
        "uz": "Bot uchun {coins} coin",
        "en": "{coins} coins for the bot",
    },
    "stars_paid": {
        "ru": "✅ <b>Оплата прошла!</b> Начислено <b>{coins}</b> 💎",
        "uz": "✅ <b>To'lov amalga oshdi!</b> <b>{coins}</b> 💎 qo'shildi",
        "en": "✅ <b>Payment successful!</b> <b>{coins}</b> 💎 added",
    },
    "msg_not_found": {
        "ru": "Сообщение не найдено 😕",
        "uz": "Xabar topilmadi 😕",
        "en": "Message not found 😕",
    },
    "reveal_profile_link": {
        "ru": "профиль",
        "uz": "profil",
        "en": "profile",
    },
    "btn_reveal_yes": {
        "ru": "✦ Да, раскрыть · 1⭐",
        "uz": "✦ Ha, aniqlash · 1⭐",
        "en": "✦ Yes, reveal · 1⭐",
    },
    "btn_cancel_accent": {
        "ru": "✦ Отмена",
        "uz": "✦ Bekor",
        "en": "✦ Cancel",
    },






    "vip_daily_bonus": {
        "ru": "🎁 Ежедневный VIP-бонус: <b>+{n}</b> 💎",
        "uz": "🎁 Kunlik VIP bonus: <b>+{n}</b> 💎",
        "en": "🎁 Daily VIP bonus: <b>+{n}</b> 💎",
    },
    "anon_write_prompt": {
        "ru": "Напишите ваш {label} текстом или отправьте голосовое сообщение:",
        "uz": "{label}ni matn bilan yozing yoki ovozli xabar yuboring:",
        "en": "Write your {label} as text or send a voice message:",
    },
    "anon_hdr_question": {
        "ru": "📩 <b>Вам пришёл анонимный вопрос</b>",
        "uz": "📩 <b>Sizga anonim savol keldi</b>",
        "en": "📩 <b>You received an anonymous question</b>",
    },
    "anon_hdr_valentine": {
        "ru": "💌 <b>Вам пришла анонимная валентинка</b>",
        "uz": "💌 <b>Sizga anonim valentinka keldi</b>",
        "en": "💌 <b>You received an anonymous valentine</b>",
    },
    "anon_hdr_reply": {
        "ru": "💬 <b>Вам ответили</b>",
        "uz": "💬 <b>Sizga javob berishdi</b>",
        "en": "💬 <b>You got a reply</b>",
    },
    "anon_hdr_new": {
        "ru": "📩 <b>Новое анонимное сообщение</b>",
        "uz": "📩 <b>Yangi anonim xabar</b>",
        "en": "📩 <b>New anonymous message</b>",
    },
    "anon_quote_reply": {
        "ru": "↩️ <i>в ответ на:</i>",
        "uz": "↩️ <i>javoban:</i>",
        "en": "↩️ <i>in reply to:</i>",
    },
    "preview_voice": {
        "ru": "🎤 голосовое сообщение",
        "uz": "🎤 ovozli xabar",
        "en": "🎤 voice message",
    },
    "preview_media": {
        "ru": "📎 медиа",
        "uz": "📎 media",
        "en": "📎 media",
    },
    "btn_reply": {
        "ru": "✦ Ответить",
        "uz": "✦ Javob",
        "en": "✦ Reply",
    },
    "btn_report": {
        "ru": "✦ Жалоба",
        "uz": "✦ Shikoyat",
        "en": "✦ Report",
    },
    "btn_reveal": {
        "ru": "✦ Узнать кто · 1⭐",
        "uz": "✦ Kim ekan · 1⭐",
        "en": "✦ Reveal who · 1⭐",
    },
    "btn_delete": {
        "ru": "✦ Удалить",
        "uz": "✦ O'chirish",
        "en": "✦ Delete",
    },
    "btn_subscribed": {
        "ru": "✅ Я подписался",
        "uz": "✅ Obuna bo'ldim",
        "en": "✅ I subscribed",
    },
    "anon_formats_vip": {
        "ru": ", фото, стикеры, гиф, видео",
        "uz": ", foto, stikerlar, gif, video",
        "en": ", photos, stickers, gifs, videos",
    },





    "gender_saved": {
        "ru": "✅ Готово! Ваш пол: <b>{g}</b>\n\nГлавное меню 👇",
        "uz": "✅ Tayyor! Jinsingiz: <b>{g}</b>\n\nAsosiy menyu 👇",
        "en": "✅ Done! Your gender: <b>{g}</b>\n\nMain menu 👇",
    },
    "lang_choose": {
        "ru": "🌐 Выберите язык интерфейса:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Choose the interface language:",
    },
    "lang_set": {
        "ru": "✅ Язык изменён на Русский 🇷🇺\n\nГлавное меню 👇",
        "uz": "✅ Til O'zbekchaga o'zgartirildi 🇺🇿\n\nAsosiy menyu 👇",
        "en": "✅ Language changed to English 🇬🇧\n\nMain menu 👇",
    },
    "welcome": {
        "ru": (
            "👋 <b>Привет, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — это анонимность без границ.\n"
            "<i>Тебе пишут тайно, а ты отвечаешь кому угодно.</i>\n\n"
            "<blockquote>🔗 Личная ссылка для анонимок\n"
            "🎲 Чат-рулетка по интересам\n"
            "🕵️ Никто не узнает, кто ты</blockquote>\n"
            "✨ Поехали — выбери свой пол 👇"
        ),
        "uz": (
            "👋 <b>Salom, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — chegarasiz anonimlik.\n"
            "<i>Sizga yashirin yozishadi, siz esa istalgan kishiga javob berasiz.</i>\n\n"
            "<blockquote>🔗 Anonim xabarlar uchun shaxsiy havola\n"
            "🎲 Qiziqish bo'yicha chat-ruletka\n"
            "🕵️ Hech kim siz kimligingizni bilmaydi</blockquote>\n"
            "✨ Boshladik — jinsingizni tanlang 👇"
        ),
        "en": (
            "👋 <b>Hi, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — anonymity without limits.\n"
            "<i>People message you secretly, and you reply to anyone.</i>\n\n"
            "<blockquote>🔗 Personal link for anonymous messages\n"
            "🎲 Chat roulette by interest\n"
            "🕵️ No one will know who you are</blockquote>\n"
            "✨ Let's go — choose your gender 👇"
        ),
    },
    "welcome_back": {
        "ru": (
            "✨ <b>С возвращением, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Рады видеть тебя снова в</i> <b>𐌽ꤕ𐌗ተ</b> 💙\n"
            "<blockquote>🔗 Делись ссылкой — лови анонимки\n"
            "🎲 Заходи в чат-рулетку\n"
            "👥 Зови друзей — забирай награды</blockquote>\n"
            "Главное меню 👇"
        ),
        "uz": (
            "✨ <b>Qaytganingiz bilan, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Sizni</i> <b>𐌽ꤕ𐌗ተ</b> <i>da yana ko'rganimizdan xursandmiz</i> 💙\n"
            "<blockquote>🔗 Havolani ulashing — anonim xabarlar oling\n"
            "🎲 Chat-ruletkaga kiring\n"
            "👥 Do'stlarni chaqiring — mukofot oling</blockquote>\n"
            "Asosiy menyu 👇"
        ),
        "en": (
            "✨ <b>Welcome back, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Glad to see you again in</i> <b>𐌽ꤕ𐌗ተ</b> 💙\n"
            "<blockquote>🔗 Share your link — get anonymous messages\n"
            "🎲 Jump into chat roulette\n"
            "👥 Invite friends — claim rewards</blockquote>\n"
            "Main menu 👇"
        ),
    },
    "help": {
        "ru": (
            "ℹ️ <b>Как пользоваться ботом 𐌽ꤕ𐌗ተ</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Здесь тебе пишут анонимно, и ты можешь общаться с незнакомцами. Всё просто 👇</i>\n\n"
            "📲 <b>Кнопки меню — что делают:</b>\n"
            "<blockquote>"
            "🔗 <b>Моя ссылка</b> — твоя личная ссылка. Кинь её в сторис или другу — и тебе будут писать анонимные сообщения. Ты не узнаешь кто (если не откроешь за ⭐).\n\n"
            "🎲 <b>Чат-рулетка</b> — нажми, выбери кого ищешь (парня/девушку) и бот соединит тебя со случайным собеседником. Не понравился — жми «Далее».\n\n"
            "👤 <b>Профиль</b> — тут твои данные: пол, возраст, коины 💎, статус VIP, сколько друзей пригласил.\n\n"
            "🛒 <b>Магазин</b> — здесь тратишь коины 💎 на VIP и другие штуки.\n\n"
            "👥 <b>Пригласить</b> — зови друзей по ссылке. За каждого друга <b>+20</b> 💎 (а если ты VIP — <b>+50</b> 💎).\n\n"
            "💎 <b>Купить коины</b> — пополнить баланс коинов через Telegram Stars ⭐.\n\n"
            "🔞 <b>18+</b> — зона для взрослых. Откроется <b>только если тебе есть 18</b>. Возраст указываешь при входе в бота.\n\n"
            "🌐 <b>Язык</b> — поменять язык: русский, узбекский, английский."
            "</blockquote>\n"
            "💎 <b>Что такое коины?</b>\n"
            "<i>Это внутренняя валюта бота. Зарабатывай их за друзей и активность или покупай за ⭐, а трать в магазине.</i>\n\n"
            "👑 <b>Что даёт VIP (премиум):</b>\n"
            "<blockquote>"
            "• пишешь анонимки <b>без ограничений</b> (у обычных — лимит 20 в день)\n"
            "• <b>−20%</b> на всё в магазине (цены сразу ниже)\n"
            "• <b>+5</b> 💎 в подарок каждый день\n"
            "• тебя находят в рулетке <b>быстрее</b> (приоритет)\n"
            "• можно слать фото, видео, гиф и стикеры в анонимках + корона 👑\n"
            "• меняй свою ссылку <b>сколько хочешь</b> (у обычных — раз в неделю)"
            "</blockquote>\n"
            "🛡 <i>Для безопасности переписки могут проверяться модераторами.</i>\n"
            "💬 <i>Выбери нужную кнопку в меню снизу 👇</i>"
        ),
        "uz": (
            "ℹ️ <b>𐌽ꤕ𐌗ተ botidan qanday foydalanish</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Bu yerda sizga anonim yozishadi va notanishlar bilan suhbatlashasiz. Hammasi oddiy 👇</i>\n\n"
            "📲 <b>Menyu tugmalari — nima qiladi:</b>\n"
            "<blockquote>"
            "🔗 <b>Havolam</b> — shaxsiy havolangiz. Uni storis yoki do'stga tashlang — sizga anonim xabar yozishadi. Kimligini bilmaysiz (⭐ evaziga ochmasangiz).\n\n"
            "🎲 <b>Chat-ruletka</b> — bosing, kimni qidirayotganingizni tanlang (yigit/qiz) va bot sizni tasodifiy suhbatdosh bilan bog'laydi. Yoqmasa — «Keyingi».\n\n"
            "👤 <b>Profil</b> — ma'lumotlaringiz: jins, yosh, coinlar 💎, VIP holati, nechta do'st taklif qilgansiz.\n\n"
            "🛒 <b>Do'kon</b> — bu yerda coinlarni 💎 VIP va boshqa narsalarga sarflaysiz.\n\n"
            "👥 <b>Taklif qilish</b> — do'stlarni havola orqali chaqiring. Har bir do'st uchun <b>+20</b> 💎 (VIP bo'lsangiz — <b>+50</b> 💎).\n\n"
            "💎 <b>Coin sotib olish</b> — Telegram Stars ⭐ orqali coin balansini to'ldirish.\n\n"
            "🔞 <b>18+</b> — kattalar zonasi. Faqat <b>18 yoshdan</b> ochiladi. Yoshni botga kirishda kiritasiz.\n\n"
            "🌐 <b>Til</b> — tilni o'zgartirish: rus, o'zbek, ingliz."
            "</blockquote>\n"
            "💎 <b>Coin nima?</b>\n"
            "<i>Bu botning ichki valyutasi. Do'stlar va faollik uchun ishlang yoki ⭐ ga sotib oling, do'konda sarflang.</i>\n\n"
            "👑 <b>VIP (premium) nima beradi:</b>\n"
            "<blockquote>"
            "• anonim xabarlarni <b>cheksiz</b> yozasiz (oddiylarda — kuniga 20 ta)\n"
            "• do'konda hammasiga <b>−20%</b> (narxlar darrov pastroq)\n"
            "• har kuni <b>+5</b> 💎 sovg'a\n"
            "• ruletkada sizni <b>tezroq</b> topishadi (ustunlik)\n"
            "• anonimlarda foto, video, gif, stiker + toj 👑\n"
            "• havolangizni <b>xohlagancha</b> o'zgartirasiz (oddiylarda — haftada bir)"
            "</blockquote>\n"
            "🛡 <i>Xavfsizlik uchun yozishmalar moderatorlar tomonidan tekshirilishi mumkin.</i>\n"
            "💬 <i>Pastdagi menyudan kerakli tugmani tanlang 👇</i>"
        ),
        "en": (
            "ℹ️ <b>How to use the 𐌽ꤕ𐌗ተ bot</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>People message you anonymously here, and you can chat with strangers. It's simple 👇</i>\n\n"
            "📲 <b>Menu buttons — what they do:</b>\n"
            "<blockquote>"
            "🔗 <b>My link</b> — your personal link. Post it in stories or send to a friend — people will message you anonymously. You won't know who (unless you reveal for ⭐).\n\n"
            "🎲 <b>Chat roulette</b> — tap it, choose who you want (a guy/a girl) and the bot connects you with a random partner. Don't like them — tap «Next».\n\n"
            "👤 <b>Profile</b> — your info: gender, age, coins 💎, VIP status, how many friends you invited.\n\n"
            "🛒 <b>Shop</b> — spend your coins 💎 on VIP and other items here.\n\n"
            "👥 <b>Invite</b> — invite friends via your link. <b>+20</b> 💎 per friend (VIP gets <b>+50</b> 💎).\n\n"
            "💎 <b>Buy coins</b> — top up your coin balance with Telegram Stars ⭐.\n\n"
            "🔞 <b>18+</b> — an adult zone. Opens <b>only if you're 18+</b>. You set your age when you enter the bot.\n\n"
            "🌐 <b>Language</b> — change language: Russian, Uzbek, English."
            "</blockquote>\n"
            "💎 <b>What are coins?</b>\n"
            "<i>It's the bot's in-app currency. Earn them for friends and activity or buy with ⭐, and spend in the shop.</i>\n\n"
            "👑 <b>What VIP (premium) gives:</b>\n"
            "<blockquote>"
            "• send anonymous messages <b>with no limit</b> (regular users — 20 per day)\n"
            "• <b>−20%</b> off everything in the shop (prices shown lower right away)\n"
            "• <b>+5</b> 💎 gift every day\n"
            "• you get matched <b>faster</b> in roulette (priority)\n"
            "• send photos, videos, gifs and stickers in anon messages + crown 👑\n"
            "• change your link <b>as often as you want</b> (regular — once a week)"
            "</blockquote>\n"
            "🛡 <i>For safety, conversations may be reviewed by moderators.</i>\n"
            "💬 <i>Pick the button you need in the menu below 👇</i>"
        ),
    },
    # === Профиль ===
    "profile_text": {
        "ru": "👤 <b>Ваш профиль</b>\n\nПол: <b>{gender}</b>\nПоиск в рулетке: <b>{pref}</b>\nКоины: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
        "uz": "👤 <b>Profilingiz</b>\n\nJins: <b>{gender}</b>\nRuletkada qidiruv: <b>{pref}</b>\nCoinlar: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
        "en": "👤 <b>Your profile</b>\n\nGender: <b>{gender}</b>\nRoulette search: <b>{pref}</b>\nCoins: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
    },
    "choose_action": {
        "ru": "Выберите действие на клавиатуре 👇",
        "uz": "Klaviaturadan amalni tanlang 👇",
        "en": "Choose an action on the keyboard 👇",
    },
    "choose_new_gender": {
        "ru": "Выберите новый пол:",
        "uz": "Yangi jinsni tanlang:",
        "en": "Choose new gender:",
    },
    # === Ссылка ===
    "link_menu": {
        "ru": "Выберите действие на клавиатуре 👇",
        "uz": "Klaviaturadan amalni tanlang 👇",
        "en": "Choose an action on the keyboard 👇",
    },
    "link_no_link": {
        "ru": "У вас ещё нет ссылки.\nПридумайте код (до 10 символов: латиница, цифры, «-», «_»):",
        "uz": "Sizda hali havola yo'q.\nKod kiriting (10 ta belgigacha: lotin, raqam, «-», «_»):",
        "en": "You don't have a link yet.\nCreate a code (up to 10 characters: latin, digits, «-», «_»):",
    },
    "link_change": {
        "ru": "Придумайте новый код (до 10 символов: латиница, цифры, «-», «_»).\nСтарая ссылка сразу перестанет работать.",
        "uz": "Yangi kod kiriting (10 ta belgigacha: lotin, raqam, «-», «_»).\nEski havola darhol ishlamay qoladi.",
        "en": "Enter a new code (up to 10 characters: latin, digits, «-», «_»).\nThe old link will stop working immediately.",
    },
    "link_invalid": {
        "ru": "Код должен быть до 10 символов (латиница, цифры, «-», «_»). Попробуйте ещё раз:",
        "uz": "Kod 10 ta belgigacha bo'lishi kerak (lotin, raqam, «-», «_»). Qayta urinib ko'ring:",
        "en": "Code must be up to 10 characters (latin, digits, «-», «_»). Try again:",
    },
    "link_taken": {
        "ru": "Этот код уже занят, попробуйте другой:",
        "uz": "Bu kod band, boshqasini kiriting:",
        "en": "This code is already taken, try another one:",
    },
    "link_limit": {
        "ru": "Ссылку можно сменить через {days} дн. Или купи VIP для снятия ограничения 👑",
        "uz": "Havolani {days} kundan keyin o'zgartirish mumkin. Yoki cheklovni olib tashlash uchun VIP sotib oling 👑",
        "en": "You can change the link in {days} days. Or buy VIP to remove the limit 👑",
    },
    "cancelled": {
        "ru": "Отменено.",
        "uz": "Bekor qilindi.",
        "en": "Cancelled.",
    },
    # === Анонимка ===
    "anon_what_send": {
        "ru": "Что хотите отправить?",
        "uz": "Nima yubormoqchisiz?",
        "en": "What would you like to send?",
    },
    "anon_write": {
        "ru": "Напишите ваш {label} текстом или отправьте голосовое сообщение:",
        "uz": "{label}ni matn yoki ovozli xabar sifatida yuboring:",
        "en": "Write your {label} as text or send a voice message:",
    },
    "anon_label_question": {
        "ru": "вопрос",
        "uz": "savol",
        "en": "question",
    },
    "anon_label_valentine": {
        "ru": "валентинку",
        "uz": "valentinka",
        "en": "valentine",
    },
    "anon_sent": {
        "ru": "✅ Отправлено",
        "uz": "✅ Yuborildi",
        "en": "✅ Sent",
    },
    "anon_failed": {
        "ru": "Не удалось доставить сообщение получателю 😕",
        "uz": "Xabarni yetkazib bo'lmadi 😕",
        "en": "Failed to deliver the message 😕",
    },
    "anon_reply_prompt": {
        "ru": "Напиши ответ (текст или голосовое):",
        "uz": "Javob yozing (matn yoki ovozli):",
        "en": "Write your reply (text or voice):",
    },
    "anon_reply_sent": {
        "ru": "Ответ отправлен ✅",
        "uz": "Javob yuborildi ✅",
        "en": "Reply sent ✅",
    },
    "anon_reply_failed": {
        "ru": "Не удалось доставить ответ 😕",
        "uz": "Javobni yetkazib bo'lmadi 😕",
        "en": "Failed to deliver the reply 😕",
    },
    "anon_not_found": {
        "ru": "Сообщение не найдено.",
        "uz": "Xabar topilmadi.",
        "en": "Message not found.",
    },
    "anon_limit": {
        "ru": "Лимит {n} сообщений в сутки исчерпан. VIP снимает это ограничение 👑 (см. Магазин).",
        "uz": "Kuniga {n} ta xabar limiti tugadi. VIP bu cheklovni olib tashlaydi 👑 (Do'konga qarang).",
        "en": "Daily limit of {n} messages reached. VIP removes this limit 👑 (see Shop).",
    },
    "anon_vip_media": {
        "ru": "📷 Фото/стикеры/гиф/видео могут отправлять только VIP 👑 (см. Магазин).\nОтправь текст или голосовое.",
        "uz": "📷 Foto/stikerlar/gif/video faqat VIP 👑 yuborishi mumkin (Do'konga qarang).\nMatn yoki ovozli yuboring.",
        "en": "📷 Photos/stickers/gifs/videos can only be sent by VIP 👑 (see Shop).\nSend text or voice.",
    },
    "anon_formats": {
        "ru": "Поддерживается текст, голосовое{vip}.",
        "uz": "Matn, ovozli{vip} qo'llab-quvvatlanadi.",
        "en": "Supported: text, voice{vip}.",
    },
    "anon_invalid_link": {
        "ru": "Эта ссылка недействительна 😕",
        "uz": "Bu havola yaroqsiz 😕",
        "en": "This link is invalid 😕",
    },
    "anon_own_link": {
        "ru": "Это ваша собственная ссылка 🙂 Самому себе писать нельзя.",
        "uz": "Bu sizning shaxsiy havolangiz 🙂 O'zingizga yozib bo'lmaydi.",
        "en": "This is your own link 🙂 You can't write to yourself.",
    },
    "anon_banned": {
        "ru": "Вы временно не можете писать этому пользователю 🚫",
        "uz": "Siz bu foydalanuvchiga vaqtincha yoza olmaysiz 🚫",
        "en": "You are temporarily unable to write to this user 🚫",
    },
    # === Удаление ===
    "del_both": {
        "ru": "Удалено у обоих ✅",
        "uz": "Ikkalasida ham o'chirildi ✅",
        "en": "Deleted for both ✅",
    },
    "del_only_me": {
        "ru": "Удалено у тебя. У собеседника не вышло (старше 48ч?).",
        "uz": "Sizda o'chirildi. Suhbatdoshda iloji bo'lmadi (48 soatdan eski?).",
        "en": "Deleted for you. Couldn't delete for the other (older than 48h?).",
    },
    "del_stale": {
        "ru": "Сообщение устарело (нет в базе) — удалено только у тебя.",
        "uz": "Xabar eskirgan (bazada yo'q) — faqat sizda o'chirildi.",
        "en": "Message is stale (not in DB) — deleted only for you.",
    },
    # === Рулетка ===
    "roulette_searching": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "roulette_found": {
        "ru": (
            "🎲✨ <b>СОБЕСЕДНИК НАЙДЕН</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Пиши первым — не стесняйся!</i>\n"
            "<blockquote>"
            "🙈 Полная анонимность\n"
            "📎 Можно слать фото, голосовые и стикеры"
            "</blockquote>\n"
            "<i>«➡️ Далее» — другой собеседник · «⏹️ Стоп» — выйти</i>"
        ),
        "uz": (
            "🎲✨ <b>SUHBATDOSH TOPILDI</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Birinchi bo'lib yozing — uyalmang!</i>\n"
            "<blockquote>"
            "🙈 To'liq anonimlik\n"
            "📎 Foto, ovozli xabar va stikerlar yuborish mumkin"
            "</blockquote>\n"
            "<i>«➡️ Keyingi» — boshqa suhbatdosh · «⏹️ To'xtatish» — chiqish</i>"
        ),
        "en": (
            "🎲✨ <b>A PARTNER IS FOUND</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Write first — don't be shy!</i>\n"
            "<blockquote>"
            "🙈 Full anonymity\n"
            "📎 You can send photos, voice and stickers"
            "</blockquote>\n"
            "<i>«➡️ Next» — another partner · «⏹️ Stop» — exit</i>"
        ),
    },
    "roulette_left": {
        "ru": "Собеседник покинул чат.",
        "uz": "Suhbatdosh chatni tark etdi.",
        "en": "Partner left the chat.",
    },
    "roulette_already_chat": {
        "ru": "Вы уже в чате. Пишите собеседнику или используйте кнопки ниже 👇",
        "uz": "Siz allaqachon chatsiz. Suhbatdoshga yozing yoki pastdagi tugmalardan foydalaning 👇",
        "en": "You are already in a chat. Write to your partner or use the buttons below 👇",
    },
    "roulette_already_searching": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "roulette_stop": {
        "ru": "Поиск отменён.",
        "uz": "Qidiruv bekor qilindi.",
        "en": "Search cancelled.",
    },
    # === Жалоба ===
    "report_choose": {
        "ru": "Выбери причину жалобы:",
        "uz": "Shikoyat sababini tanlang:",
        "en": "Choose the report reason:",
    },
    "report_sent": {
        "ru": "Жалоба отправлена админу на рассмотрение 🚩",
        "uz": "Shikoyat adminга ko'rib chiqish uchun yuborildi 🚩",
        "en": "Report sent to admin for review 🚩",
    },
    "report_cancelled": {
        "ru": "Жалоба отменена.",
        "uz": "Shikoyat bekor qilindi.",
        "en": "Report cancelled.",
    },
    # === Подписка ===
    "sub_required": {
        "ru": "Чтобы продолжить, подпишись на канал(ы):\n\n",
        "uz": "Davom etish uchun kanal(lar)ga obuna bo'ling:\n\n",
        "en": "To continue, subscribe to the channel(s):\n\n",
    },
    "sub_not_found": {
        "ru": "Подписка не найдена, проверь ещё раз 🙏",
        "uz": "Obuna topilmadi, qayta tekshiring 🙏",
        "en": "Subscription not found, check again 🙏",
    },
    # === Магазин ===
    "shop_title": {
        "ru": "🛒 <b>Магазин</b>\nВыберите товар 👇",
        "uz": "🛒 <b>Do'kon</b>\nMahsulotni tanlang 👇",
        "en": "🛒 <b>Shop</b>\nChoose an item 👇",
    },
    "shop_empty": {
        "ru": "🛒 <b>Магазин пока пуст.</b>",
        "uz": "🛒 <b>Do'kon hali bo'sh.</b>",
        "en": "🛒 <b>The shop is empty.</b>",
    },
    "shop_vip_note": {
        "ru": "👑 <i>Цены показаны с твоей VIP-скидкой −20%.</i>",
        "uz": "👑 <i>Narxlar VIP chegirmangiz −20% bilan ko'rsatilgan.</i>",
        "en": "👑 <i>Prices shown with your VIP −20% discount.</i>",
    },
    "18plus_shop_title": {
        "ru": "🔞 <b>18+ Магазин</b>\nВыберите товар 👇",
        "uz": "🔞 <b>18+ Do'kon</b>\nMahsulotni tanlang 👇",
        "en": "🔞 <b>18+ Shop</b>\nChoose an item 👇",
    },
    "18plus_shop_empty": {
        "ru": "🔞 <b>Магазин 18+ пока пуст.</b>",
        "uz": "🔞 <b>18+ do'kon hali bo'sh.</b>",
        "en": "🔞 <b>The 18+ shop is empty.</b>",
    },
    "stars_title": {
        "ru": "💎 <b>Покупка коинов за Telegram Stars</b>\nВыбери пакет 👇",
        "uz": "💎 <b>Telegram Stars uchun coin sotib olish</b>\nPaketni tanlang 👇",
        "en": "💎 <b>Buy coins with Telegram Stars</b>\nChoose a package 👇",
    },
    # === Рефералы ===
    "reveal_title": {
        "ru": "👁 Раскрыть отправителя",
        "uz": "👁 Yuboruvchini aniqlash",
        "en": "👁 Reveal sender",
    },
    "reveal_desc": {
        "ru": "Узнай, кто отправил тебе это анонимное сообщение",
        "uz": "Sizga bu anonim xabarni kim yuborganini biling",
        "en": "Find out who sent you this anonymous message",
    },
    "reveal_result": {
        "ru": "👁 <b>Отправитель раскрыт!</b>\n\nИмя: <b>{name}</b>\nНик: {uname}\nID: <code>{tid}</code>",
        "uz": "👁 <b>Yuboruvchi aniqlandi!</b>\n\nIsm: <b>{name}</b>\nNik: {uname}\nID: <code>{tid}</code>",
        "en": "👁 <b>Sender revealed!</b>\n\nName: <b>{name}</b>\nUsername: {uname}\nID: <code>{tid}</code>",
    },
    "reveal_confirm": {
        "ru": "👁 Раскрыть отправителя этого сообщения за <b>1 ⭐ Star</b>?",
        "uz": "👁 Ushbu xabar yuboruvchini <b>1 ⭐ Star</b> uchun aniqlaysizmi?",
        "en": "👁 Reveal the sender of this message for <b>1 ⭐ Star</b>?",
    },
    "reveal_paying": {
        "ru": "⏳ Оплатите инвойс ниже...",
        "uz": "⏳ Quyidagi hisob-fakturani to'lang...",
        "en": "⏳ Pay the invoice below...",
    },
    "reveal_only_recipient": {
        "ru": "Только получатель может раскрыть отправителя.",
        "uz": "Faqat qabul qiluvchi yuboruvchini aniqlay oladi.",
        "en": "Only the recipient can reveal the sender.",
    },
    "invite_text": {
        "ru": "👥 <b>Пригласи друзей и получи коины!</b>\n\n🔗 Твоя реф-ссылка:\n{link}\n\n+{bonus} 💎 за каждого друга.",
        "uz": "👥 <b>Do'stlarni taklif qiling va coin oling!</b>\n\n🔗 Ref-havolangiz:\n{link}\n\n+{bonus} 💎 har bir do'st uchun.",
        "en": "👥 <b>Invite friends and earn coins!</b>\n\n🔗 Your referral link:\n{link}\n\n+{bonus} 💎 for each friend.",
    },
    # === 18+ ===
    "age_gate_title": {
        "ru": "🔞 <b>Возрастной портал</b> 🔞\n\nЭтот раздел доступен только пользователям 18+",
        "uz": "🔞 <b>Yosh portali</b> 🔞\n\nBu bo'lim faqat 18+ yoshdagi foydalanuvchilar uchun",
        "en": "🔞 <b>Age Gate</b> 🔞\n\nThis section is only for users 18+",
    },
    "age_gate_intro": {
        "ru": (
            "Добро пожаловать в 18+ зону! 🎉\n"
            "Здесь только взрослые собеседники и контент.\n"
            "Перед входом подтвердите свой возраст."
        ),
        "uz": (
            "18+ zonaga xush kelibsiz! 🎉\n"
            "Bu yerda faqat kattalar suhbatdoshlari va kontent bor.\n"
            "Kirishdan oldin yoshingizni tasdiqlang."
        ),
        "en": (
            "Welcome to the 18+ zone! 🎉\n"
            "Here you'll find only adult partners and content.\n"
            "Please verify your age before entering."
        ),
    },
    "age_consent_text": {
        "ru": (
            "🔞 <b>18+ ЧАТ ДЛЯ ВЗРОСЛЫХ</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Добро пожаловать! Это <b>не обычный Next</b> — это зона для взрослых 18+.\n\n"
            "<b>✅ Здесь можно:</b>\n"
            "<blockquote>"
            "• общаться свободно на любые темы для взрослых\n"
            "• отправлять фото, видео, стикеры, голосовые\n"
            "• быть откровенным — это чат для взрослых"
            "</blockquote>\n"
            "<b>🚫 Здесь нельзя:</b>\n"
            "<blockquote>"
            "• контент с несовершеннолетними (строгий бан)\n"
            "• насилие, угрозы, шантаж\n"
            "• мошенничество и спам\n"
            "• продажа запрещённых веществ"
            "</blockquote>\n"
            "🛡 <i>Чаты могут проверяться модераторами. За нарушения — вечный бан.</i>\n\n"
            "Нажимая «Согласиться», вы подтверждаете, что вам <b>18+</b> и принимаете правила 👇"
        ),
        "uz": (
            "🔞 <b>18+ KATTALAR CHATI</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Xush kelibsiz! Bu <b>oddiy Next emas</b> — bu 18+ kattalar zonasi.\n\n"
            "<b>✅ Bu yerda mumkin:</b>\n"
            "<blockquote>"
            "• kattalar uchun istalgan mavzuda erkin muloqot\n"
            "• foto, video, stiker, ovozli xabar yuborish\n"
            "• ochiq bo'lish — bu kattalar chati"
            "</blockquote>\n"
            "<b>🚫 Bu yerda mumkin emas:</b>\n"
            "<blockquote>"
            "• voyaga yetmaganlar bilan kontent (qattiq ban)\n"
            "• zo'ravonlik, tahdid, shantaj\n"
            "• firibgarlik va spam\n"
            "• taqiqlangan moddalar savdosi"
            "</blockquote>\n"
            "🛡 <i>Chatlar moderatorlar tomonidan tekshirilishi mumkin. Buzilish uchun — abadiy ban.</i>\n\n"
            "«Roziman» tugmasini bosib, siz <b>18+</b> ekanligingizni tasdiqlaysiz 👇"
        ),
        "en": (
            "🔞 <b>18+ ADULT CHAT</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome! This is <b>not the usual Next</b> — it's an adult 18+ zone.\n\n"
            "<b>✅ Here you can:</b>\n"
            "<blockquote>"
            "• chat freely on any adult topics\n"
            "• send photos, videos, stickers, voice\n"
            "• be open — it's an adult chat"
            "</blockquote>\n"
            "<b>🚫 Here you cannot:</b>\n"
            "<blockquote>"
            "• content with minors (strict ban)\n"
            "• violence, threats, blackmail\n"
            "• fraud and spam\n"
            "• selling illegal substances"
            "</blockquote>\n"
            "🛡 <i>Chats may be reviewed by moderators. Violations = permanent ban.</i>\n\n"
            "By tapping «I agree» you confirm you are <b>18+</b> and accept the rules 👇"
        ),
    },
    "age_verify_ask_photo": {
        "ru": (
            "📷 <b>Подтверждение возраста</b>\n\n"
            "Отправьте фото документа, подтверждающего ваш возраст (можно прикрыть личные данные, оставьте дату рождения).\n"
            "Администратор проверит и откроет доступ."
        ),
        "uz": (
            "📷 <b>Yoshni tasdiqlash</b>\n\n"
            "Yoshingizni tasdiqlovchi hujjat fotosini yuboring (shaxsiy ma'lumotlarni yoping, tug'ilgan sanani qoldiring).\n"
            "Administrator tekshirib, kirishni ochadi."
        ),
        "en": (
            "📷 <b>Age verification</b>\n\n"
            "Send a photo of a document confirming your age (you may hide personal data, leave the birth date).\n"
            "The administrator will review and grant access."
        ),
    },
    "roulette_found_18plus": {
        "ru": (
            "🔞✨ <b>СОБЕСЕДНИК 18+ НАЙДЕН</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>Это закрытый чат для взрослых.</i>\n"
            "<blockquote>"
            "✅ Можно: общаться свободно, слать фото, видео, голосовые\n"
            "🚫 Нельзя: то, что запрещено правилами"
            "</blockquote>\n"
            "🔥 <b>Приятного общения!</b>\n"
            "<i>«➡️ Далее» — сменить собеседника · «⏹️ Стоп» — выйти</i>"
        ),
        "uz": (
            "🔞✨ <b>18+ SUHBATDOSH TOPILDI</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>Bu kattalar uchun yopiq chat.</i>\n"
            "<blockquote>"
            "✅ Mumkin: erkin muloqot, foto, video, ovozli xabar\n"
            "🚫 Mumkin emas: qoidalar bilan taqiqlangan narsalar"
            "</blockquote>\n"
            "🔥 <b>Yoqimli muloqot!</b>\n"
            "<i>«➡️ Keyingi» — suhbatdoshni almashtirish · «⏹️ To'xtatish» — chiqish</i>"
        ),
        "en": (
            "🔞✨ <b>AN 18+ PARTNER IS FOUND</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>This is a private adult chat.</i>\n"
            "<blockquote>"
            "✅ Allowed: chat freely, send photos, videos, voice\n"
            "🚫 Forbidden: anything against the rules"
            "</blockquote>\n"
            "🔥 <b>Enjoy!</b>\n"
            "<i>«➡️ Next» — change partner · «⏹️ Stop» — exit</i>"
        ),
    },
    "age_select_title": {
        "ru": "📅 <b>Ваш возраст?</b>",
        "uz": "📅 <b>Sizning yoshingiz?</b>",
        "en": "📅 <b>How old are you?</b>",
    },
    "age_search_title": {
        "ru": "🔎 <b>Кого ищем по возрасту?</b>\nВыберите диапазон 👇",
        "uz": "🔎 <b>Qaysi yoshdagini qidiramiz?</b>\nDiapazonni tanlang 👇",
        "en": "🔎 <b>What age are you looking for?</b>\nChoose a range 👇",
    },
    "age_register_ask": {
        "ru": "📅 <b>Сколько вам лет?</b>\n\nНапишите ваш возраст числом (например: 21).\nЭто нужно для доступа к разделу 🔞 18+. Если меньше 18 — раздел будет недоступен.",
        "uz": "📅 <b>Yoshingiz nechada?</b>\n\nYoshingizni raqam bilan yozing (masalan: 21).\nBu 🔞 18+ bo'limiga kirish uchun kerak. 18 dan kichik bo'lsa — bo'lim yopiq bo'ladi.",
        "en": "📅 <b>How old are you?</b>\n\nType your age as a number (e.g. 21).\nNeeded for access to the 🔞 18+ section. If under 18 — the section will be unavailable.",
    },
    "age_enter_number": {
        "ru": "Введите ваш возраст числом (например: 21):",
        "uz": "Yoshingizni raqam bilan kiriting (masalan: 21):",
        "en": "Enter your age as a number (e.g. 21):",
    },
    "age_saved": {
        "ru": "✅ Возраст сохранён: <b>{age}</b>\n\nГлавное меню 👇",
        "uz": "✅ Yosh saqlandi: <b>{age}</b>\n\nAsosiy menyu 👇",
        "en": "✅ Age saved: <b>{age}</b>\n\nMain menu 👇",
    },
    "age_under18_saved": {
        "ru": "Понятно. Раздел 🔞 18+ будет недоступен.\nЕсли вам исполнилось 18 — измените возраст в Профиле и подтвердите его.\n\nГлавное меню 👇",
        "uz": "Tushunarli. 🔞 18+ bo'limi yopiq bo'ladi.\nAgar 18 yoshga to'lgan bo'lsangiz — Profilda yoshni o'zgartiring va tasdiqlang.\n\nAsosiy menyu 👇",
        "en": "Got it. The 🔞 18+ section will be unavailable.\nIf you've turned 18 — change your age in Profile and verify it.\n\nMain menu 👇",
    },
    "age_18_20": {
        "ru": "18/20",
        "uz": "18/20",
        "en": "18/20",
    },
    "age_20_22": {
        "ru": "20/22",
        "uz": "20/22",
        "en": "20/22",
    },
    "age_22_25": {
        "ru": "22/25",
        "uz": "22/25",
        "en": "22/25",
    },
    "age_25_30": {
        "ru": "25/30",
        "uz": "25/30",
        "en": "25/30",
    },
    "age_30_plus": {
        "ru": "30+",
        "uz": "30+",
        "en": "30+",
    },
    "age_under_18": {
        "ru": "Менее 18",
        "uz": "18 dan kichik",
        "en": "Under 18",
    },
    "age_gate_button": {
        "ru": "🔞 18+ контент",
        "uz": "🔞 18+ kontent",
        "en": "🔞 18+ content",
    },
    "age_verification_required": {
        "ru": (
            "⏳ <b>Ваш возраст: {age}</b>\n\n"
            "Этот контент доступен только пользователям 18+.\n"
            "Если вам меньше 18, вы можете запросить подтверждение возраста, загрузив фото."
        ),
        "uz": (
            "⏳ <b>Sizning yoshingiz: {age}</b>\n\n"
            "Bu kontent faqat 18+ foydalanuvchilar uchun.\n"
            "Agar siz 18 yoshdan kichik bo'lsangiz, foto yuklab yoshingizni tasdiqlash so'rovi yubora olasiz."
        ),
        "en": (
            "⏳ <b>Your age: {age}</b>\n\n"
            "This content is only for users 18+.\n"
            "If you're under 18, you can request age verification by uploading a photo."
        ),
    },
    "age_under_18_deny": {
        "ru": (
            "🚫 <b>Доступ закрыт</b>\n\n"
            "К сожалению, вы не можете использовать 18+ контент.\n"
            "Вам должно быть минимум 18 лет."
        ),
        "uz": (
            "🚫 <b>Kirish mumkin emas</b>\n\n"
            "Afsuski, 18+ kontentdan foydalana olmaysiz.\n"
            "Sizda kamida 18 yosh bo'lishi kerak."
        ),
        "en": (
            "🚫 <b>Access Denied</b>\n\n"
            "Unfortunately, you cannot access 18+ content.\n"
            "You must be at least 18 years old."
        ),
    },
    "age_verification_sent": {
        "ru": (
            "✅ <b>Заявка отправлена!</b>\n\n"
            "Администратор рассмотрит ваш запрос.\n"
            "Пожалуйста, подождите ответа."
        ),
        "uz": (
            "✅ <b>So'rov yuborildi!</b>\n\n"
            "Administrator so'rovingizni ko'rib chiqadi.\n"
            "Iltimos, javobni kuting."
        ),
        "en": (
            "✅ <b>Request sent!</b>\n\n"
            "The administrator will review your request.\n"
            "Please wait for a response."
        ),
    },
    "age_verification_pending": {
        "ru": "⏳ <b>Ваш запрос на подтверждение возраста находится на рассмотрении</b>",
        "uz": "⏳ <b>Yoshingizni tasdiqlash so'rovingiz ko'rib chiqilmoqda</b>",
        "en": "⏳ <b>Your age verification request is being reviewed</b>",
    },
    "age_verification_approved": {
        "ru": (
            "✅ <b>Ваш возраст подтверждён!</b>\n"
            "Теперь у вас есть доступ к 18+ контенту."
        ),
        "uz": (
            "✅ <b>Yoshingiz tasdiqlandi!</b>\n"
            "Endi 18+ kontentdan foydalana olasiz."
        ),
        "en": (
            "✅ <b>Your age has been verified!</b>\n"
            "You now have access to 18+ content."
        ),
    },
    "age_verification_rejected": {
        "ru": (
            "❌ <b>Ваш запрос на подтверждение возраста отклонён</b>\n\n"
            "{reason}"
        ),
        "uz": (
            "❌ <b>Yoshingizni tasdiqlash so'rovi rad etildi</b>\n\n"
            "{reason}"
        ),
        "en": (
            "❌ <b>Your age verification request was rejected</b>\n\n"
            "{reason}"
        ),
    },
    "age_verify_already": {
        "ru": "Заявка уже обработана.",
        "uz": "Ariza allaqachon ko'rib chiqilgan.",
        "en": "The request has already been handled.",
    },
    "age_verify_approved_staff": {
        "ru": "✅ Возраст подтверждён, доступ к 18+ открыт.",
        "uz": "✅ Yosh tasdiqlandi, 18+ ochildi.",
        "en": "✅ Age verified, 18+ access granted.",
    },
    "age_verify_rejected_staff": {
        "ru": "❌ Заявка на 18+ отклонена.",
        "uz": "❌ 18+ arizasi rad etildi.",
        "en": "❌ 18+ request rejected.",
    },
    "age_18_plus_item": {
        "ru": "🔞 18+ товар",
        "uz": "🔞 18+ mahsulot",
        "en": "🔞 18+ item",
    },
    "18plus_purchase_coins": {
        "ru": "✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b> 💎",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> <b>{amt}</b> 💎 qo'shildi",
        "en": "✅ <b>Purchase complete!</b> <b>{amt}</b> 💎 added",
    },
    "18plus_purchase_manual": {
        "ru": "✅ <b>Покупка совершена!</b> Админ свяжется с вами.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> Admin siz bilan bog'lanadi.",
        "en": "✅ <b>Purchase complete!</b> The admin will contact you.",
    },
    "18plus_admin_menu": {
        "ru": "🔞 <b>Админка: 18+ магазин</b>\n\nВыберите действие 👇",
        "uz": "🔞 <b>Admin: 18+ do'kon</b>\n\nAmalni tanlang 👇",
        "en": "🔞 <b>Admin: 18+ shop</b>\n\nChoose an action 👇",
    },
    "18plus_add_item": {
        "ru": "➕ Добавить товар 18+",
        "uz": "➕ 18+ mahsulot qo'shish",
        "en": "➕ Add 18+ item",
    },
    "18plus_list_items": {
        "ru": "📋 Список товаров 18+",
        "uz": "📋 18+ mahsulotlar ro'yxati",
        "en": "📋 18+ items list",
    },
    "18plus_item_added": {
        "ru": "✅ Товар добавлен!",
        "uz": "✅ Mahsulot qo'shildi!",
        "en": "✅ Item added!",
    },
    "18plus_item_deleted": {
        "ru": "✅ Товар удалён!",
        "uz": "✅ Mahsulot o'chirildi!",
        "en": "✅ Item deleted!",
    },
    "18plus_confirm_delete": {
        "ru": "Вы уверены, что хотите удалить товар «<b>{title}</b>»?",
        "uz": "«<b>{title}</b>» mahsulotini o'chirmoqchimisiz?",
        "en": "Are you sure you want to delete item «<b>{title}</b>»?",
    },
}


def t(key, **kw):
    d = T.get(key, {})
    s = d.get(cur_lang()) or d.get("ru") or key
    return s.format(**kw) if kw else s


def language_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇺🇿 O'zbekcha")],
        [KeyboardButton("🇬🇧 English")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


async def show_language_menu(update, context):
    context.user_data["state"] = "language"
    await nav(update, context, t("lang_choose"), language_menu_kb())


async def language_router(update, context):
    text = canon(update.message.text)
    if canon(text) == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    lang = LANG_BUTTONS.get(text)
    if not lang:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=language_menu_kb())
        return
    set_lang(update.effective_user.id, lang)
    set_cur_lang(lang)
    context.user_data["state"] = None
    await nav(update, context, t("lang_set"), main_menu_kb(update.effective_user.id))


async def set_lang_context(update, context):
    """Подставляет язык пользователя в ContextVar текущего апдейта."""
    try:
        uid = update.effective_user.id if update.effective_user else None
        set_cur_lang(get_lang(uid) if uid else "ru")
    except Exception:
        set_cur_lang("ru")


def main_menu_kb(tg_id):
    rows = [
        [KeyboardButton("🔗 Моя ссылка"), KeyboardButton("🎲 Чат-рулетка")],
        [KeyboardButton("👤 Профиль"), KeyboardButton("🛒 Магазин")],
        [KeyboardButton("👥 Пригласить"), KeyboardButton("ℹ️ Помощь")],
        [KeyboardButton("🌐 Язык")],
    ]
    # Кнопка покупки коинов за Stars — стилизована как premium
    if conn.execute("SELECT 1 FROM star_packages WHERE active=1 LIMIT 1").fetchone():
        star_label = styled(tr_btn("💎 Купить коины"), "premium")
        rows.append([KeyboardButton(star_label)])
    # Кнопка 18+ — только у подтверждённых совершеннолетних (возраст >= 18)
    if is_adult(get_user(tg_id)):
        rows.append([KeyboardButton("🔞 18+")])
    if is_admin(tg_id):
        rows.append([KeyboardButton("🛠 Админка")])
    else:
        u = get_user(tg_id)
        if is_moder(u):
            rows.append([KeyboardButton("🛡 Модерка")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


def yes_no_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("✅ Да"), KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def reward_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("💎 Коины"), KeyboardButton("⏳ VIP")],
        [KeyboardButton("🛡 Модер"), KeyboardButton("📦 Вручную")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def admin_menu_kb():
    enabled = get_setting("18plus_enabled", "1") == "1"
    toggle_label = "🔞 18+ доступ: ВКЛ" if enabled else "🔞 18+ доступ: ВЫКЛ"
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("💰 Начислить коины"), KeyboardButton("👑 VIP по ID")],
        [KeyboardButton("📢 Обязательные каналы"), KeyboardButton("📣 Реклама")],
        [KeyboardButton("✉️ Рассылка"), KeyboardButton("🛡 Модеры")],
        [KeyboardButton("🔨 Бан / Разбан"), KeyboardButton("⭐ Коины за Stars")],
        [KeyboardButton(toggle_label)],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def admin_vip_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Выдать VIP"), KeyboardButton("➖ Забрать VIP")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def eighteen_plus_admin_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить товар")],
        [KeyboardButton("📋 Список товаров"), KeyboardButton("🗑 Удалить товар")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def star_admin_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить пакет коинов")],
        [KeyboardButton("🗑 Удалить пакет коинов")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def moder_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🚩 Жалобы"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("📢 Обязательные каналы")],
        [KeyboardButton("ℹ️ Помощь")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def moder_decision_kb(app_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Выдать", callback_data=f"modapp:ok:{app_id}"),
        InlineKeyboardButton("❌ Отказ", callback_data=f"modapp:no:{app_id}"),
    ]])


def gender_kb(with_back=False):
    rows = [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")]]
    if with_back:
        rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


def link_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔗 Показать ссылку"), KeyboardButton("✏️ Сменить ссылку")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def roulette_pref_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку"), KeyboardButton("🤷 Любого")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def eighteen_plus_age_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("18/20"), KeyboardButton("20/22"), KeyboardButton("22/25")],
        [KeyboardButton("25/30"), KeyboardButton("30+")],
        [KeyboardButton("🔞 Мне нет 18")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def eighteen_plus_consent_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("✅ Согласиться")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def eighteen_plus_verify_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📷 Отправить фото")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def anon_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("❓ Вопрос"), KeyboardButton("💌 Валентинка")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True))


def report_reason_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🤬 Мат"), KeyboardButton("💰 Мошенничество")],
        [KeyboardButton("😡 Оскорбление"), KeyboardButton("🔞 18+ стикеры")],
        [KeyboardButton("👎 Не нравится")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True))


async def clean_screen(update, context):
    """Удаляет нажатую пользователем кнопку, доп. сообщения (карточки) и предыдущее меню бота."""
    try:
        await update.message.delete()
    except TelegramError:
        pass
    for mid in context.user_data.pop("extra_msg_ids", []):
        await try_delete_message(context, update.effective_chat.id, mid)
    mid = context.user_data.pop("last_menu_msg_id", None)
    if mid:
        await try_delete_message(context, update.effective_chat.id, mid)


def track_extra(context, msg):
    """Запоминает доп. сообщение (например карточку ссылки) для удаления при следующей навигации."""
    context.user_data.setdefault("extra_msg_ids", []).append(msg.message_id)


async def send_menu(update, context, text, reply_markup, parse_mode=None):
    """Отправляет новое меню и запоминает его id для последующей очистки."""
    msg = await context.bot.send_message(update.effective_chat.id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    context.user_data["last_menu_msg_id"] = msg.message_id
    return msg


async def nav(update, context, text, reply_markup=None, parse_mode=None):
    """Единый «экран»: удаляет нажатие пользователя и прошлое меню, показывает одно новое сообщение."""
    await clean_screen(update, context)
    return await send_menu(update, context, text, reply_markup, parse_mode)


async def go_home(update, context):
    """Кнопка «🏠 Меню» — мгновенный возврат в главное меню из любой глубины + очистка."""
    context.user_data["state"] = None
    await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))


def profile_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("✏️ Сменить пол"), KeyboardButton("✏️ Изменить возраст")],
        [KeyboardButton("🎁 Подарить коины")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


async def grant_daily_bonus(uid, context):
    """Ежедневный бонус VIP: +VIP_DAILY_BONUS коинов раз в день."""
    u = get_user(uid)
    if not is_vip(u):
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if u["last_bonus"] == today:
        return
    conn.execute("UPDATE users SET coins = coins + ?, last_bonus=? WHERE tg_id=?", (VIP_DAILY_BONUS, today, uid))
    conn.commit()
    try:
        await context.bot.send_message(uid, t("vip_daily_bonus", n=VIP_DAILY_BONUS), parse_mode="HTML")
    except TelegramError:
        pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    existed = get_user(tg_user.id) is not None
    user = ensure_user(tg_user.id, tg_user.username, tg_user.first_name)
    if is_banned(user):
        await update.message.reply_text(t("banned"))
        return
    await grant_daily_bonus(tg_user.id, context)
    args = context.args

    if args:
        code = args[0]
        if code.startswith("ref_"):
            await handle_referral(update, context, code, existed)
            # дальше продолжаем обычный старт (приветствие/меню)
        else:
            await handle_incoming_link(update, context, code)
            return

    # 🔒 Принудительная подписка для входа (если включена админом)
    if get_setting("subgate_enabled", "0") == "1" and not is_admin(tg_user.id):
        chans = await get_mandatory_channels()
        if chans and not await user_subscribed_all(context, tg_user.id, chans):
            await update.message.reply_text(
                t("subgate_start"), parse_mode="HTML",
                reply_markup=subscribe_gate_kb(chans),
            )
            return

    if not user["gender"]:
        context.user_data["state"] = "set_gender_first"
        name = tg_user.first_name or "друг"
        await update.message.reply_text(
            t("welcome", name=html.escape(name)),
            parse_mode="HTML",
            reply_markup=gender_kb(),
        )
        return

    # Пол есть, но возраст ещё не задан (например, старые аккаунты) — спрашиваем возраст
    if user["age"] is None:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove(),
        )
        return

    name = tg_user.first_name or "друг"
    await update.message.reply_text(
        t("welcome_back", name=html.escape(name)),
        parse_mode="HTML",
        reply_markup=main_menu_kb(tg_user.id),
    )


async def eighteen_plus_menu(update, context):
    """Показывает меню 18+ контента (с возрастным барьером и согласием)."""
    user = get_user(update.effective_user.id)
    await clean_screen(update, context)
    # Глобальный запрет 18+ админом — кнопка видна, но раздел не работает
    if get_setting("18plus_enabled", "1") != "1" and not is_admin(update.effective_user.id):
        context.user_data["state"] = None
        await send_menu(update, context, t("18plus_disabled_notice"),
                        main_menu_kb(update.effective_user.id), parse_mode="HTML")
        return
    if not is_adult(user):
        # Доступ закрыт (кнопка не должна показываться, но на всякий случай)
        context.user_data["state"] = None
        await send_menu(update, context, t("age_under_18_deny"), main_menu_kb(update.effective_user.id), parse_mode="HTML")
        return
    # Согласие уже дано ранее — сразу в 18+ меню, не спрашиваем повторно
    if user["age_consent"]:
        context.user_data["state"] = "18plus_menu"
        await send_menu(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    # Первый вход — показываем приветствие/согласие
    context.user_data["state"] = "18plus_consent"
    await send_menu(update, context, t("age_consent_text"), eighteen_plus_consent_kb(), parse_mode="HTML")


async def eighteen_plus_consent_router(update, context):
    """Обработка согласия с правилами 18+ (запоминается)."""
    text = canon(update.message.text)
    if text == "⬅️ Назад" or text == "🏠 Меню":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if text == "✅ Согласиться":
        conn.execute("UPDATE users SET age_consent=1 WHERE tg_id=?", (update.effective_user.id,))
        conn.commit()
        context.user_data["state"] = "18plus_menu"
        await nav(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    await update.message.reply_text(t("choose_on_kb"), reply_markup=eighteen_plus_consent_kb())


async def eighteen_plus_age_router(update, context):
    """Обработка выбора возраста в 18+ рулетке."""
    text = canon(update.message.text)
    if text == "🏠 Меню":
        await go_home(update, context)
        return
    if text == "❌ Отмена" or text == "⬅️ Назад":
        # Шаг назад: к меню 18+
        context.user_data["state"] = "18plus_menu"
        await nav(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    # Несовершеннолетний — сохраняем и предлагаем верификацию
    if text == "🔞 Мне нет 18":
        conn.execute("UPDATE users SET age='under18' WHERE tg_id=?", (update.effective_user.id,))
        conn.commit()
        context.user_data["state"] = "18plus_verify_offer"
        await nav(update, context, t("age_under_18_deny"), eighteen_plus_verify_kb(), parse_mode="HTML")
        return
    age_ranges = {
        "18/20": "18-20",
        "20/22": "20-22",
        "22/25": "22-25",
        "25/30": "25-30",
        "30+": "30+",
    }
    age = age_ranges.get(text)
    if not age:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=eighteen_plus_age_kb())
        return
    conn.execute("UPDATE users SET age=? WHERE tg_id=?", (age, update.effective_user.id))
    conn.commit()
    # Возраст подтверждён (18+) — показываем экран согласия
    context.user_data["state"] = "18plus_consent"
    await nav(update, context, t("age_consent_text"), eighteen_plus_consent_kb(), parse_mode="HTML")


async def eighteen_plus_verify_offer_router(update, context):
    """Несовершеннолетний: предложение отправить фото для подтверждения возраста."""
    text = canon(update.message.text)
    if text == "⬅️ Назад" or text == "🏠 Меню":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if text == "📷 Отправить фото":
        # Проверим, нет ли уже заявки на рассмотрении
        pending = conn.execute(
            "SELECT 1 FROM age_verification_requests WHERE user_id=? AND status='pending' LIMIT 1",
            (update.effective_user.id,),
        ).fetchone()
        if pending:
            await update.message.reply_text(t("age_verification_pending"), parse_mode="HTML")
            return
        context.user_data["state"] = "18plus_verify_upload"
        await update.message.reply_text(t("age_verify_ask_photo"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    await update.message.reply_text(t("choose_on_kb"), reply_markup=eighteen_plus_verify_kb())


async def eighteen_plus_menu_router(update, context):
    """Обработка кнопок 18+ меню."""
    text = canon(update.message.text)
    if text == "⬅️ Назад" or text == "🏠 Меню":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    # Показать 18+ рулетку
    if text == "18+ магазин":
        await show_eighteen_plus_shop(update, context)
        return
    if text == "🎁 Подарить 18+":
        await start_gift_18plus(update, context)
        return
    if text == "18+ рулетка":
        user = get_user(update.effective_user.id)
        if user["age"]:
            await show_eighteen_plus_roulette(update, context)
        else:
            context.user_data["state"] = "18plus_age_select"
            await nav(update, context, t("age_select_title"), eighteen_plus_age_kb())
        return
    await update.message.reply_text(t("choose_on_kb"), reply_markup=eighteen_plus_menu_kb())


def gift_price_for(user_row):
    """Цена подарка 18+ с учётом VIP."""
    return GIFT_18PLUS_PRICE_VIP if is_vip(user_row) else GIFT_18PLUS_PRICE


async def start_gift_18plus(update, context):
    """Начало дарения 18+ доступа другу — спрашиваем ID."""
    uid = update.effective_user.id
    user = get_user(uid)
    price = gift_price_for(user)
    context.user_data["state"] = "gift18_id"
    await nav(update, context, t("gift18_ask_id", price=price, days=GIFT_18PLUS_DAYS), cancel_reply_kb(), parse_mode="HTML")


async def gift_18plus_router(update, context):
    """Дарение 18+ доступа: ввод ID → подтверждение → перевод."""
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    if canon(text) in ("❌ Отмена", "⬅️ Назад"):
        context.user_data["state"] = "18plus_menu"
        await nav(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    if state == "gift18_id":
        target = resolve_user_ref(text)
        if target is None:
            await update.message.reply_text(t("gift_user_not_found"), reply_markup=cancel_reply_kb())
            return
        if target == uid:
            await update.message.reply_text(t("gift_not_self"), reply_markup=cancel_reply_kb())
            return
        context.user_data["gift18_target"] = target
        context.user_data["state"] = "gift18_confirm"
        price = gift_price_for(get_user(uid))
        await nav(update, context, t("gift18_confirm", id=target, price=price, days=GIFT_18PLUS_DAYS),
                  yes_no_kb(), parse_mode="HTML")
        return
    if state == "gift18_confirm":
        if canon(text) != "✅ Да":
            await update.message.reply_text(t("choose_on_kb"), reply_markup=yes_no_kb())
            return
        target = context.user_data.get("gift18_target")
        user = get_user(uid)
        price = gift_price_for(user)
        if not is_unlimited(user) and (user["coins"] or 0) < price:
            context.user_data["state"] = "18plus_menu"
            await nav(update, context, t("not_enough_coins"), eighteen_plus_menu_kb())
            return
        if not is_unlimited(user):
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (price, uid))
            conn.commit()
        grant_18plus_access(target, GIFT_18PLUS_DAYS)
        context.user_data["state"] = None
        context.user_data.pop("gift18_target", None)
        # Уведомляем получателя
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("gift18_received", days=GIFT_18PLUS_DAYS),
                                           parse_mode="HTML", reply_markup=main_menu_kb(target))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await nav(update, context, t("gift18_sent", id=target, days=GIFT_18PLUS_DAYS),
                  main_menu_kb(uid), parse_mode="HTML")
        return


async def show_eighteen_plus_roulette(update, context):
    """Показывает 18+ рулетку."""
    user = get_user(update.effective_user.id)
    active = get_active_session(user["tg_id"])
    await clean_screen(update, context)
    if active:
        UD[user["tg_id"]]["state"] = "18plus_rchat"
        await context.bot.send_message(update.effective_chat.id, t("roulette_already_chat"), reply_markup=in_chat_kb())
        return
    # 18+ рулетка доступна только тем, кто купил доступ в 18+ магазине (или админ/модер)
    if not is_eighteenplus_active(user):
        context.user_data["state"] = "18plus_menu"
        await send_menu(update, context, t("eighteenplus_need_access"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    in_queue = conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=? AND mode='18plus'", (user["tg_id"],)).fetchone()
    if in_queue:
        await context.bot.send_message(update.effective_chat.id, t("roulette_searching"), reply_markup=searching_kb())
        return
    context.user_data["state"] = "18plus_pref"
    await send_menu(update, context, t("roulette_who"), eighteen_plus_roulette_pref_kb())


async def eighteen_plus_pref_router(update, context):
    """Обработка выбора пола в 18+ рулетке."""
    text = canon(update.message.text)
    if text == "🏠 Меню":
        await go_home(update, context)
        return
    if text == "⬅️ Назад":
        # Шаг назад: к меню 18+
        context.user_data["state"] = "18plus_menu"
        await nav(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        return
    pref = {"👨 Парня": "m", "👩 Девушку": "f", "🤷 Любого": "any"}.get(text)
    if not pref:
        await context.bot.send_message(update.effective_chat.id, t("pick_on_kb"), reply_markup=eighteen_plus_roulette_pref_kb())
        return
    user = get_user(update.effective_user.id)
    conn.execute("UPDATE users SET search_pref=? WHERE tg_id=?", (pref, user["tg_id"]))
    # Запоминаем выбор пола и переходим к выбору диапазона возраста
    context.user_data["18plus_pref_gender"] = pref
    context.user_data["state"] = "18plus_age_search"
    await clean_screen(update, context)
    await send_menu(update, context, t("age_search_title"), eighteen_plus_age_search_kb())


async def eighteen_plus_age_search_router(update, context):
    """Выбор диапазона возраста для поиска в 18+ рулетке, затем постановка в очередь."""
    text = canon(update.message.text)
    if text == "🏠 Меню":
        await go_home(update, context)
        return
    if text == "⬅️ Назад":
        # Шаг назад: к выбору пола собеседника
        context.user_data["state"] = "18plus_pref"
        await nav(update, context, t("roulette_who"), eighteen_plus_roulette_pref_kb())
        return
    if text == "🤷 Любой возраст":
        age_min, age_max = 18, 200
    elif text in AGE_SEARCH_RANGES:
        age_min, age_max = AGE_SEARCH_RANGES[text]
    else:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=eighteen_plus_age_search_kb())
        return
    user = get_user(update.effective_user.id)
    pref = context.user_data.get("18plus_pref_gender", "any")
    my_age = user_age_int(user) or 18
    conn.execute(
        "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, actual_age, age_min, age_max, joined_at) "
        "VALUES (?, ?, ?, ?, '18plus', ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, "
        "mode=excluded.mode, actual_age=excluded.actual_age, age_min=excluded.age_min, age_max=excluded.age_max, joined_at=excluded.joined_at",
        (user["tg_id"], user["gender"], pref, 1 if is_vip(user) else 0, my_age, age_min, age_max, now_iso()),
    )
    conn.commit()
    context.user_data["state"] = None
    await clean_screen(update, context)
    await context.bot.send_message(update.effective_chat.id, t("roulette_finding_partner"), reply_markup=searching_kb())


def eighteen_plus_age_search_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("18/20"), KeyboardButton("20/22"), KeyboardButton("22/24")],
        [KeyboardButton("24/26"), KeyboardButton("26/28"), KeyboardButton("28/30")],
        [KeyboardButton("30+"), KeyboardButton("🤷 Любой возраст")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def eighteen_plus_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("18+ рулетка"), KeyboardButton("18+ магазин")],
        [KeyboardButton("🎁 Подарить 18+")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def eighteen_plus_roulette_pref_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку"), KeyboardButton("🤷 Любого")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def eighteen_plus_shop_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("18+ магазин")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


async def set_gender_from_text(update, context):
    """Обработка выбора/смены пола через reply-клавиатуру."""
    text = canon(update.message.text)
    state = context.user_data.get("state")
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    gender = {"👨 Мужской": "m", "👩 Женский": "f"}.get(text)
    if not gender:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=gender_kb(state == "set_gender_profile"))
        return
    conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (gender, update.effective_user.id))
    conn.commit()
    g = {"m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
         "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"}}[gender][cur_lang()]
    user = get_user(update.effective_user.id)
    # При первичной регистрации после пола спрашиваем возраст (если ещё не задан)
    if state == "set_gender_first" and not user["age"]:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(
            t("gender_set_short", g=g), parse_mode="HTML",
        )
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove(),
        )
        return
    context.user_data["state"] = None
    await update.message.reply_text(
        t("gender_saved", g=g),
        parse_mode="HTML",
        reply_markup=main_menu_kb(update.effective_user.id),
    )


async def set_age_from_text(update, context):
    """Ввод возраста ЧИСЛОМ при регистрации (set_age_first) и смене в профиле (set_age_profile)."""
    text = (update.message.text or "").strip()
    ctext = canon(text)
    state = context.user_data.get("state")
    uid = update.effective_user.id
    user = get_user(uid)
    # Отмена/назад — только в профиле
    if ctext in ("⬅️ Назад", "❌ Отмена") and state == "set_age_profile":
        await show_profile(update, context)
        return
    # Ожидаем число
    if not text.isdigit():
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return
    new_age = int(text)
    if new_age < 5 or new_age > 99:
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return
    cur_age = user_age_int(user)
    # Меньше 18 — сохраняем, доступ к 18+ закрыт
    if new_age < 18:
        conn.execute("UPDATE users SET age=?, age_consent=0 WHERE tg_id=?", (str(new_age), uid))
        conn.commit()
        context.user_data["state"] = None
        await update.message.reply_text(
            t("age_under18_saved"), parse_mode="HTML",
            reply_markup=main_menu_kb(uid),
        )
        return
    # Хочет 18+, но раньше был отмечен младше 18 (в профиле) — нужна верификация
    if state == "set_age_profile" and cur_age is not None and cur_age < 18:
        pending = conn.execute(
            "SELECT 1 FROM age_verification_requests WHERE user_id=? AND status='pending' LIMIT 1",
            (uid,),
        ).fetchone()
        if pending:
            context.user_data["state"] = None
            await update.message.reply_text(t("age_verification_pending"), parse_mode="HTML",
                                             reply_markup=main_menu_kb(uid))
            return
        context.user_data["state"] = "18plus_verify_upload"
        context.user_data["pending_age"] = new_age
        await update.message.reply_text(t("age_verify_ask_photo"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    # Иначе — просто сохраняем (доверяем при регистрации / смене среди 18+)
    conn.execute("UPDATE users SET age=? WHERE tg_id=?", (str(new_age), uid))
    conn.commit()
    context.user_data["state"] = None
    await update.message.reply_text(
        t("age_saved", age=new_age), parse_mode="HTML",
        reply_markup=main_menu_kb(uid),
    )



async def on_back_main(update, context):
    query = update.callback_query
    await query.answer()
    await try_delete_message(context, query.message.chat_id, query.message.message_id)
    await context.bot.send_message(
        query.from_user.id,
        t("main_menu"),
        reply_markup=main_menu_kb(query.from_user.id)
    )


LINK_ALPHABET = string.ascii_letters + string.digits + "_-"


def valid_link_code(code: str) -> bool:
    return 1 <= len(code) <= 10 and all(c in LINK_ALPHABET for c in code)


# === Персистентное состояние анона по ссылке (переживает рестарт процесса) ===
LINK_FLOW_TTL_HOURS = 6  # незавершённый флоу старше этого — игнорируем


def save_link_flow(user_id, target_id, state, msg_type=None):
    """Сохраняет/обновляет незавершённый флоу анона по ссылке в БД."""
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.execute(
            "INSERT INTO link_flow (user_id, target_id, msg_type, state, updated_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, target_id, msg_type, state, now_iso()),
        )
        conn.commit()
    except Exception as e:  # noqa
        log.warning("save_link_flow: %s", e)


def load_link_flow(user_id):
    """Возвращает строку незавершённого флоу (если не протух), иначе None."""
    try:
        row = conn.execute("SELECT * FROM link_flow WHERE user_id=?", (user_id,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        if now_dt() - datetime.fromisoformat(row["updated_at"]) > timedelta(hours=LINK_FLOW_TTL_HOURS):
            clear_link_flow(user_id)
            return None
    except Exception:
        pass
    return row


def clear_link_flow(user_id):
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.commit()
    except Exception as e:  # noqa
        log.warning("clear_link_flow: %s", e)


def share_kb(link, text):
    """Инлайн-кнопка «Поделиться» — открывает в Telegram выбор чата для пересылки ссылки."""
    share_url = ("https://t.me/share/url?url=" + urllib.parse.quote(link, safe="")
                 + "&text=" + urllib.parse.quote(text, safe=""))
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_share"), url=share_url)]])


_BOT_USERNAME = None


async def get_bot_username(context):
    """Кэшируем @username бота — чтобы не дёргать get_me() на каждое сообщение."""
    global _BOT_USERNAME
    if _BOT_USERNAME is None:
        _BOT_USERNAME = (await context.bot.get_me()).username
    return _BOT_USERNAME


async def build_start_link(context, code):
    """Единый билдер deep-link на бота в формате t.me/<bot>?start=<code>."""
    return f"t.me/{await get_bot_username(context)}?start={code}"


# === Авто-перевод (для названий товаров магазина) ===
def _translate_sync(text, target):
    """Перевод через бесплатный публичный эндпоинт Google. При ошибке вернёт исходный текст."""
    if not text or not text.strip():
        return text
    try:
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
               "&sl=auto&tl=" + urllib.parse.quote(target)
               + "&dt=t&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return out.strip() or text
    except Exception as e:  # noqa
        log.warning("translate(%s): %s", target, e)
        return text


async def translate_to_all(text):
    """Возвращает (ru, uz, en) для текста на любом языке. Не блокирует event loop."""
    ru = await asyncio.to_thread(_translate_sync, text, "ru")
    uz = await asyncio.to_thread(_translate_sync, text, "uz")
    en = await asyncio.to_thread(_translate_sync, text, "en")
    return ru or text, uz or text, en or text


def item_title(item):
    """Название товара на текущем языке (с откатом к русскому)."""
    lang = cur_lang()
    try:
        if lang == "uz" and item["title_uz"]:
            return item["title_uz"]
        if lang == "en" and item["title_en"]:
            return item["title_en"]
    except (KeyError, IndexError, TypeError):
        pass
    return item["title"]


def can_change_link(user_row):
    if is_vip(user_row):
        return True, None
    if not user_row["link_changed_at"]:
        return True, None
    try:
        last_change = datetime.fromisoformat(user_row["link_changed_at"])
        cooldown_end = last_change + timedelta(days=LINK_CHANGE_COOLDOWN_DAYS)
        if now_dt() >= cooldown_end:
            return True, None
        else:
            days_left = (cooldown_end - now_dt()).days + 1
            return False, t("link_limit", days=days_left)
    except ValueError:
        return True, None



async def show_link_menu(update, context):
    await clean_screen(update, context)
    context.user_data["state"] = "link_menu"
    await send_menu(update, context, t("link_section"), link_menu_kb(), parse_mode="HTML")


async def link_menu_router(update, context):
    text = canon(update.message.text)
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if text == "🔗 Показать ссылку":
        await show_my_link(update, context)
        return
    if text == "✏️ Сменить ссылку":
        await start_change_link(update, context)
        return
    await update.message.reply_text(t("link_menu"), reply_markup=link_menu_kb())


async def show_my_link(update, context):
    user = get_user(update.effective_user.id)
    if not user["custom_link"]:
        context.user_data["state"] = "awaiting_link_code"
        await nav(update, context, t("link_no_link"), link_code_kb())
        return
    # Стираем нажатие «Показать ссылку» и прошлый экран, показываем карточку.
    await clean_screen(update, context)
    link = await build_start_link(context, user["custom_link"])
    msg = await context.bot.send_message(
        update.effective_chat.id,
        t("link_show", link=html.escape(link)),
        parse_mode="HTML",
        reply_markup=share_kb(link, t("share_text")),
    )
    track_extra(context, msg)
    # Гарантируем нижние кнопки [Показать/Сменить][Назад] под карточкой
    await send_menu(update, context, t("link_section"), link_menu_kb(), parse_mode="HTML")


async def start_change_link(update, context):
    user = get_user(update.effective_user.id)
    can_change, error_msg = can_change_link(user)
    if not can_change:
        # Подписка на обязательные каналы снимает недельный лимит (даже без VIP)
        chans = await get_mandatory_channels()
        if chans and await user_subscribed_all(context, update.effective_user.id, chans):
            can_change = True
        else:
            # Предлагаем подписаться, чтобы менять без ожидания
            days = 7
            try:
                last = datetime.fromisoformat(user["link_changed_at"])
                days = max(1, (last + timedelta(days=LINK_CHANGE_COOLDOWN_DAYS) - now_dt()).days + 1)
            except (ValueError, TypeError):
                pass
            await clean_screen(update, context)
            if chans:
                msg = await context.bot.send_message(
                    update.effective_chat.id, t("link_limit_sub", days=days),
                    parse_mode="HTML", reply_markup=subscribe_gate_kb(chans))
                track_extra(context, msg)
                await send_menu(update, context, t("link_section"), link_menu_kb(), parse_mode="HTML")
            else:
                await send_menu(update, context, error_msg, link_menu_kb())
            return
    context.user_data["state"] = "awaiting_link_code"
    await nav(update, context, t("link_change"), link_code_kb())


async def process_link_code(update, context, code):
    code = (code or "").strip()
    if canon(code) in ("❌ Отмена", "⬅️ Назад"):
        context.user_data["state"] = "link_menu"
        await show_link_menu(update, context)
        return
    if not valid_link_code(code):
        await update.message.reply_text(
            t("link_invalid"),
            reply_markup=link_code_kb(),
        )
        return
    exists = conn.execute("SELECT tg_id FROM users WHERE custom_link=?", (code,)).fetchone()
    if exists and exists["tg_id"] != update.effective_user.id:
        await update.message.reply_text(t("link_taken"), reply_markup=link_code_kb())
        return
    conn.execute(
        "UPDATE users SET custom_link=?, link_changed_at=? WHERE tg_id=?",
        (code, now_iso(), update.effective_user.id),
    )
    conn.commit()
    context.user_data["state"] = "link_menu"
    # Стираем введённый код и прошлый экран; показываем карточку + меню ссылки.
    await clean_screen(update, context)
    link = await build_start_link(context, code)
    card = await context.bot.send_message(
        update.effective_chat.id,
        t("link_done", link=html.escape(link)),
        parse_mode="HTML",
        reply_markup=share_kb(link, t("share_text")),
    )
    track_extra(context, card)
    await send_menu(update, context, t("link_menu"), link_menu_kb())


async def handle_incoming_link(update, context, code):
    sender_id = update.effective_user.id
    sender_row = ensure_user(sender_id, update.effective_user.username, update.effective_user.first_name)
    if is_banned(sender_row):
        await update.message.reply_text(t("banned"))
        return
    owner = conn.execute("SELECT * FROM users WHERE custom_link=?", (code,)).fetchone()
    if not owner:
        await update.message.reply_text(t("anon_invalid_link"))
        await deliver_start_menu(context, sender_id)
        return
    if owner["tg_id"] == sender_id:
        await update.message.reply_text(
            t("anon_own_link"),
            reply_markup=main_menu_kb(sender_id),
        )
        return
    ban = conn.execute(
        "SELECT * FROM bans WHERE owner_id=? AND banned_id=? AND until>?",
        (owner["tg_id"], sender_id, now_iso()),
    ).fetchone()
    if ban:
        await update.message.reply_text(t("anon_banned"))
        await deliver_start_menu(context, sender_id)
        return
    context.user_data["state"] = "awaiting_anon_type"
    context.user_data["anon_target"] = owner["tg_id"]
    save_link_flow(sender_id, owner["tg_id"], "awaiting_anon_type")
    await update.message.reply_text(t("anon_what_send"), reply_markup=anon_type_kb())



async def on_anon_type_text(update, context):
    text = canon(update.message.text)
    if text == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("anon_target", None)
        clear_link_flow(update.effective_user.id)
        # Авто-/start после отмены: приветствие + регистрация (если новый) или меню
        await deliver_start_menu(context, update.effective_user.id)
        return
    if text == "❓ Вопрос":
        msg_type = "question"
    elif text == "💌 Валентинка":
        msg_type = "valentine"
    else:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=anon_type_kb())
        return
    context.user_data["anon_type"] = msg_type
    context.user_data["state"] = "awaiting_anon_content"
    target = context.user_data.get("anon_target")
    if target:
        save_link_flow(update.effective_user.id, target, "awaiting_anon_content", msg_type)
    label = t("anon_label_question") if msg_type == "question" else t("anon_label_valentine")
    await update.message.reply_text(
        t("anon_write_prompt", label=label),
        reply_markup=ReplyKeyboardRemove()
    )


# Заголовки доставляемого анонимного сообщения по типу (локализуются на лету)
def anon_header(msg_type):
    return {
        "question": t("anon_hdr_question"),
        "valentine": t("anon_hdr_valentine"),
        "reply": t("anon_hdr_reply"),
    }.get(msg_type, t("anon_hdr_new"))


# Превью содержимого сообщения для цитаты в треде
def anon_preview(row):
    if not row:
        return ""
    if row["content_type"] == "text" and row["text"]:
        p = row["text"]
    elif row["content_type"] == "voice":
        p = t("preview_voice")
    else:
        p = t("preview_media")
    if len(p) > 150:
        p = p[:150] + "…"
    return p


# Универсальная доставка анонимного сообщения (вопрос/валентинка/ответ).
# Создаёт запись, шлёт получателю с цитатой родителя + кнопкой «Ответить» (и опц. «Пожаловаться»),
# а автору — подтверждение с кнопкой удаления. Так строится бесконечный двусторонний тред.
async def deliver_anon(context, author_id, recipient_id, msg_type, content_type,
                       text=None, voice_file_id=None, src_chat_id=None, src_message_id=None,
                       parent_id=None, allow_report=True, vip_badge=False):
    cur = conn.execute(
        "INSERT INTO anon_messages (from_id, to_id, msg_type, content_type, text, voice_file_id, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (author_id, recipient_id, msg_type, content_type, text, voice_file_id, parent_id, now_iso()),
    )
    conn.commit()
    mid = cur.lastrowid

    # Сообщение для получателя рендерим на ЕГО языке
    _saved_lang = cur_lang()
    set_cur_lang(get_lang(recipient_id))

    # Цитата родительского сообщения — чтобы не путаться, на что отвечают
    quote = ""
    if parent_id:
        parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (parent_id,)).fetchone()
        prev = anon_preview(parent)
        if prev:
            quote = f"{t('anon_quote_reply')}\n<blockquote>{html.escape(prev)}</blockquote>\n"

    badge = "👑 " if vip_badge else ""
    header = badge + anon_header(msg_type)
    buttons = [[
        InlineKeyboardButton(t("btn_reply"), callback_data=f"reply:{mid}"),
        InlineKeyboardButton(t("btn_report"), callback_data=f"report_anon:{mid}"),
    ]]
    # Кнопка раскрытия отправителя за 1 Star (только для первого сообщения, не для ответов)
    if msg_type != "reply":
        buttons.append([InlineKeyboardButton(t("btn_reveal"), callback_data=f"reveal:{mid}")])
    kb = InlineKeyboardMarkup(buttons)

    try:
        if content_type == "text":
            sent = await context.bot.send_message(
                recipient_id,
                f"{quote}{header}:\n<blockquote>{html.escape(text or '')}</blockquote>",
                parse_mode="HTML", reply_markup=kb,
            )
        elif content_type == "voice":
            sent = await context.bot.send_voice(
                recipient_id, voice_file_id,
                caption=f"{quote}{header}:", parse_mode="HTML", reply_markup=kb,
            )
        else:  # media (VIP) — копируем исходное сообщение с медиа одним сообщением
            sent = await context.bot.copy_message(
                recipient_id, src_chat_id, src_message_id,
                caption=f"{quote}{header}:", parse_mode="HTML", reply_markup=kb,
            )
    except TelegramError:
        set_cur_lang(_saved_lang)
        return None

    conn.execute("UPDATE anon_messages SET owner_chat_message_id=? WHERE id=?", (sent.message_id, mid))
    conn.commit()

    # Возвращаем язык автора для подтверждения
    set_cur_lang(_saved_lang)

    # Подтверждение автору + кнопка удаления (сотрёт обе копии)
    del_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_delete"), callback_data=f"del:{mid}")]])
    try:
        author_msg = await context.bot.send_message(author_id, t("anon_sent"), reply_markup=del_kb)
        conn.execute("UPDATE anon_messages SET sender_chat_message_id=? WHERE id=?", (author_msg.message_id, mid))
        conn.commit()
    except TelegramError:
        pass
    return mid


# Извлекает тип/текст/медиа из входящего сообщения. Возвращает (content_type, text, voice_file_id) либо None при ошибке.
async def extract_anon_content(update, is_v):
    m = update.message
    is_media = bool(m.photo or m.sticker or m.animation or m.video or m.video_note or m.document)
    if m.text:
        return "text", m.text, None
    if m.voice:
        return "voice", None, m.voice.file_id
    if is_media:
        if not is_v:
            await update.message.reply_text(
                t("anon_vip_media"),
            )
            return None
        return "media", None, None
    await update.message.reply_text(
        t("anon_formats", vip=t("anon_formats_vip") if is_v else "")
    )
    return None


async def process_anon_content(update, context):
    sender = update.effective_user
    sender_row = ensure_user(sender.id, sender.username, sender.first_name)
    target_id = context.user_data.get("anon_target")
    msg_type = context.user_data.get("anon_type")
    is_v = is_vip(sender_row)
    if not is_v:
        since = (now_dt() - timedelta(days=1)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) c FROM anon_messages WHERE from_id=? AND created_at>?",
            (sender.id, since),
        ).fetchone()["c"]
        if count >= DAILY_LIMIT:
            await update.message.reply_text(
                t("anon_limit", n=DAILY_LIMIT),
                reply_markup=main_menu_kb(sender.id)
            )
            context.user_data["state"] = None
            clear_link_flow(sender.id)
            return
    extracted = await extract_anon_content(update, is_v)
    if extracted is None:
        return
    content_type, text, voice_file_id = extracted
    # Анти-спам: запрет контактов/ссылок/соцсетей (кроме персонала)
    if content_type == "text" and not is_staff(sender.id) and has_forbidden_contacts(text):
        await update.message.reply_text(t("no_contacts"))
        return
    m = update.message
    mid = await deliver_anon(
        context, author_id=sender.id, recipient_id=target_id, msg_type=msg_type,
        content_type=content_type, text=text, voice_file_id=voice_file_id,
        src_chat_id=m.chat_id, src_message_id=m.message_id,
        parent_id=None, allow_report=True, vip_badge=is_v,
    )
    context.user_data["state"] = None
    context.user_data.pop("anon_target", None)
    context.user_data.pop("anon_type", None)
    clear_link_flow(sender.id)
    if mid is None:
        await context.bot.send_message(sender.id, t("anon_failed"))
        # Авто-/start: приветствие + регистрация (если новый) или меню
        await deliver_start_menu(context, sender.id)
        return
    await reward_link_activity(context, sender.id, "sent")
    # После отправки анонимки автоматически запускаем /start:
    # новому пользователю — приветствие и регистрация, остальным — главное меню.
    await deliver_start_menu(context, sender.id)


async def on_reply_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    context.user_data["state"] = "awaiting_reply"
    context.user_data["reply_target_msg"] = msg_id
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    reply_to = row["owner_chat_message_id"] if row else None
    # Привязываем запрос ответа как цитату к исходному сообщению (видно, на какой вопрос отвечаешь)
    try:
        await context.bot.send_message(
            query.from_user.id,
            t("anon_reply_prompt"),
            reply_to_message_id=reply_to,
        )
    except TelegramError:
        await context.bot.send_message(query.from_user.id, t("anon_reply_prompt"))



async def process_reply_content(update, context):
    replier = update.effective_user
    replier_row = ensure_user(replier.id, replier.username, replier.first_name)
    msg_id = context.user_data.get("reply_target_msg")
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    if not parent:
        await update.message.reply_text(t("anon_not_found"), reply_markup=main_menu_kb(replier.id))
        context.user_data["state"] = None
        return
    # Получатель ответа — это другая сторона переписки (не тот, кто сейчас отвечает)
    recipient_id = parent["from_id"] if replier.id == parent["to_id"] else parent["to_id"]
    is_v = is_vip(replier_row)
    extracted = await extract_anon_content(update, is_v)
    if extracted is None:
        return
    content_type, text, voice_file_id = extracted
    # Анти-спам: запрет контактов/ссылок/соцсетей (кроме персонала)
    if content_type == "text" and not is_staff(replier.id) and has_forbidden_contacts(text):
        await update.message.reply_text(t("no_contacts"))
        return
    # Сохраняем ответ в родителя (для истории/жалоб) и помечаем отвеченным
    if content_type == "text":
        conn.execute("UPDATE anon_messages SET answer_text=?, answered=1 WHERE id=?", (text, msg_id))
    elif content_type == "voice":
        conn.execute("UPDATE anon_messages SET answer_voice_file_id=?, answered=1 WHERE id=?", (voice_file_id, msg_id))
    else:
        conn.execute("UPDATE anon_messages SET answered=1 WHERE id=?", (msg_id,))
    conn.commit()
    m = update.message
    mid = await deliver_anon(
        context, author_id=replier.id, recipient_id=recipient_id, msg_type="reply",
        content_type=content_type, text=text, voice_file_id=voice_file_id,
        src_chat_id=m.chat_id, src_message_id=m.message_id,
        parent_id=msg_id, allow_report=True, vip_badge=is_v,
    )
    context.user_data["state"] = None
    context.user_data.pop("reply_target_msg", None)
    if mid is None:
        await update.message.reply_text(t("anon_reply_failed"), reply_markup=main_menu_kb(replier.id))
        return
    await reward_link_activity(context, replier.id, "answered")
    await update.message.reply_text(t("anon_reply_sent"), reply_markup=main_menu_kb(replier.id))



async def get_mandatory_channels():
    return conn.execute("SELECT * FROM mandatory_channels").fetchall()


def channel_url(raw):
    """Строит кликабельную ссылку из @username / t.me/... / полной ссылки."""
    raw = (raw or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return "https://" + raw
    return "https://t.me/" + raw.lstrip("@")


def channel_title(ch):
    """Название кнопки канала: кастомное или из ссылки."""
    try:
        ttl = ch["title"]
    except (KeyError, IndexError, TypeError):
        ttl = None
    if ttl:
        return ttl
    raw = (ch["chat_username"] or "").strip()
    name = raw.lstrip("@").rstrip("/").split("/")[-1]
    return "📢 " + (name or "Канал")


def _chat_ref_for_check(raw):
    """Возвращает @username для проверки подписки или None, если проверить нельзя
    (приватная ссылка-приглашение, бот и т.п.)."""
    raw = (raw or "").strip()
    if raw.startswith("@"):
        return raw
    low = raw.lower()
    if "t.me/" in low:
        tail = raw.split("t.me/", 1)[1].strip("/")
        # приватные инвайты (+xxx / joinchat) проверить нельзя
        if tail.startswith("+") or tail.lower().startswith("joinchat"):
            return None
        tail = tail.split("?")[0].split("/")[0]
        return "@" + tail if tail else None
    if raw and not raw.startswith("http"):
        return "@" + raw.lstrip("@")
    return None


def subscribe_kb(msg_id, channels):
    """Инлайн-кнопки: каждый канал — кнопка-ссылка (со стрелкой) + кнопка «Проверить»."""
    rows = []
    for c in channels:
        rows.append([InlineKeyboardButton(channel_title(c), url=channel_url(c["chat_username"]))])
    rows.append([InlineKeyboardButton(t("btn_check_sub"), callback_data=f"subcheck:{msg_id}")])
    return InlineKeyboardMarkup(rows)


def subscribe_gate_kb(channels):
    """Инлайн-кнопки подписки для входа в бота (+ «Проверить» с callback subgate)."""
    rows = [[InlineKeyboardButton(channel_title(c), url=channel_url(c["chat_username"]))] for c in channels]
    rows.append([InlineKeyboardButton(t("btn_check_sub"), callback_data="subgate")])
    return InlineKeyboardMarkup(rows)


async def deliver_start_menu(context, uid):
    """Показывает приветствие/меню после прохождения гейта подписки (учитывает регистрацию)."""
    user = get_user(uid)
    _sl = cur_lang(); set_cur_lang(get_lang(uid))
    name = html.escape(user["first_name"] or "друг")
    try:
        if not user["gender"]:
            UD[uid]["state"] = "set_gender_first"
            await context.bot.send_message(uid, t("welcome", name=name), parse_mode="HTML", reply_markup=gender_kb())
        elif user["age"] is None:
            UD[uid]["state"] = "set_age_first"
            await context.bot.send_message(uid, t("age_register_ask"), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        else:
            await context.bot.send_message(uid, t("welcome_back", name=name), parse_mode="HTML", reply_markup=main_menu_kb(uid))
    finally:
        set_cur_lang(_sl)


async def on_subgate_check(update, context):
    """Проверка подписки для входа в бота."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    chans = await get_mandatory_channels()
    if chans and not await user_subscribed_all(context, uid, chans):
        await query.answer(t("sub_not_found"), show_alert=True)
        return
    try:
        await query.message.delete()
    except TelegramError:
        pass
    await deliver_start_menu(context, uid)


async def user_subscribed_all(context, user_id, channels):
    for ch in channels:
        ref = _chat_ref_for_check(ch["chat_username"])
        if ref is None:
            continue  # проверить нельзя (бот/приватная ссылка) — не блокируем
        try:
            member = await context.bot.get_chat_member(ref, user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except TelegramError:
            continue  # бот не админ в канале/не нашёл — пропускаем, не блокируем намертво
    return True


async def on_delete_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    channels = await get_mandatory_channels()
    if channels:
        ok = await user_subscribed_all(context, query.from_user.id, channels)
        if not ok:
            await query.message.reply_text(
                t("sub_to_delete_short"), parse_mode="HTML",
                reply_markup=subscribe_kb(msg_id, channels),
            )
            return
    await do_delete_message(query, context, msg_id)


async def on_subcheck_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    channels = await get_mandatory_channels()
    ok = await user_subscribed_all(context, query.from_user.id, channels)
    if not ok:
        await query.answer(t("sub_not_found"), show_alert=True)
        return
    await do_delete_message(query, context, msg_id)


async def do_delete_message(query, context, msg_id):
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    if not row:
        # Запись потеряна (например, после сброса БД на хостинге) — стираем хотя бы нажатое сообщение
        try:
            await query.message.delete()
        except TelegramError:
            pass
        try:
            await query.answer(t("del_stale"), show_alert=True)
        except TelegramError:
            pass
        return
    deleted_recipient = False
    # удалить у получателя
    if row["owner_chat_message_id"]:
        try:
            await context.bot.delete_message(row["to_id"], row["owner_chat_message_id"])
            deleted_recipient = True
        except TelegramError:
            pass
    # удалить свою копию (у отправителя)
    if row["sender_chat_message_id"]:
        try:
            await context.bot.delete_message(row["from_id"], row["sender_chat_message_id"])
        except TelegramError:
            pass
    # подстраховка: стираем само нажатое сообщение, если это не учтённая копия
    try:
        await query.message.delete()
    except TelegramError:
        pass
    conn.execute("UPDATE anon_messages SET deleted=1 WHERE id=?", (msg_id,))
    conn.commit()
    # Уведомляем получателя, что отправитель удалил своё сообщение (на его языке)
    if deleted_recipient:
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(row["to_id"]))
            await context.bot.send_message(row["to_id"], t("anon_deleted_notice"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
    try:
        if deleted_recipient:
            await query.answer(t("del_both"), show_alert=True)
        else:
            await query.answer(t("del_only_me"), show_alert=True)
    except TelegramError:
        pass



async def on_report_anon(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    if not row:
        return
    context.user_data["state"] = "awaiting_report_reason"
    context.user_data["report_context"] = "anon"
    context.user_data["report_ref_id"] = msg_id
    context.user_data["reported_id"] = row["from_id"]
    await query.message.reply_text(t("report_choose"), reply_markup=report_reason_kb())


async def process_report_reason(update, context):
    text = canon(update.message.text)
    if text == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("report_context", None)
        context.user_data.pop("report_ref_id", None)
        context.user_data.pop("reported_id", None)
        await update.message.reply_text(
            t("report_cancelled"),
            reply_markup=main_menu_kb(update.effective_user.id)
        )
        return
    reason_map = {
        "🤬 Мат": "Мат",
        "💰 Мошенничество": "Мошенничество",
        "😡 Оскорбление": "Оскорбление",
        "🔞 18+ стикеры": "18+ стикеры",
        "👎 Не нравится": "Не нравится"
    }
    reason = reason_map.get(text)
    if not reason:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=report_reason_kb())
        return
    ctx = context.user_data.get("report_context")
    ref_id = context.user_data.get("report_ref_id")
    reported_id = context.user_data.get("reported_id")
    cur = conn.execute(
        "INSERT INTO reports (reporter_id, reported_id, context, reason, ref_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (update.effective_user.id, reported_id, ctx, reason, ref_id, now_iso()),
    )
    conn.commit()
    report_id = cur.lastrowid
    await update.message.reply_text(
        t("report_sent"),
        reply_markup=main_menu_kb(update.effective_user.id)
    )
    context.user_data["state"] = None
    context.user_data.pop("report_context", None)
    context.user_data.pop("report_ref_id", None)
    context.user_data.pop("reported_id", None)

    if ctx == "anon":
        msg = conn.execute("SELECT * FROM anon_messages WHERE id=?", (ref_id,)).fetchone()
        content_preview = msg["text"] if msg["content_type"] == "text" else "[голосовое сообщение]"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔨 Бан навсегда", callback_data=f"repadm:ok:{report_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"repadm:no:{report_id}"),
        ]])
        await notify_staff(
            context,
            f"🚩 Жалоба на анонимное сообщение #{ref_id}\n"
            f"Причина: {reason}\n"
            f"Тип: {msg['msg_type']}\nСодержание: {content_preview}",
            reply_markup=kb,
        )
    else:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔨 Бан 30 дн.", callback_data=f"repadm:ok:{report_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"repadm:no:{report_id}"),
        ]])
        await notify_staff(
            context,
            f"🚩 Жалоба после рулетки (сессия #{ref_id})\nПричина: {reason}",
            reply_markup=kb,
        )


async def on_report_admin_decision(update, context):
    query = update.callback_query
    await query.answer()
    if not is_staff(query.from_user.id):
        await query.answer(t("staff_only"), show_alert=True)
        return
    _, decision, report_id = query.data.split(":")
    report_id = int(report_id)
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not report or report["status"] != "pending":
        await query.edit_message_text(t("report_already_handled"))
        return
    if decision == "ok":
        # Админа/модера нельзя забанить по жалобе
        if is_staff(report["reported_id"]):
            conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (report_id,))
            conn.commit()
            await query.edit_message_text(t("cant_ban_staff"))
            return
        until = (now_dt() + timedelta(days=BAN_DAYS)).isoformat()
        is_anon = report["context"] == "anon"
        if is_anon:
            until = ANON_BAN_FOREVER          # анонимка → бан навсегда (попарно)
        else:
            until = (now_dt() + timedelta(days=ROULETTE_BAN_DAYS)).isoformat()  # рулетка → месяц
        conn.execute(
            "INSERT INTO bans (owner_id, banned_id, until, created_at) VALUES (?, ?, ?, ?)",
            (report["reporter_id"], report["reported_id"], until, now_iso()),
        )
        conn.execute("UPDATE reports SET status='confirmed' WHERE id=?", (report_id,))
        conn.commit()
        # Уведомляем жалобщика (на его языке)
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(report["reporter_id"]))
            await context.bot.send_message(
                report["reporter_id"],
                t("report_confirmed_forever") if is_anon else t("report_confirmed_user", days=ROULETTE_BAN_DAYS),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        # Уведомляем самого заблокированного пользователя (на его языке)
        try:
            _sl2 = cur_lang()
            set_cur_lang(get_lang(report["reported_id"]))
            await context.bot.send_message(
                report["reported_id"],
                t("you_were_banned_forever") if is_anon else t("you_were_banned", days=ROULETTE_BAN_DAYS),
            )
            set_cur_lang(_sl2)
        except TelegramError:
            pass
        await query.edit_message_text(t("report_confirmed_staff"))
    else:
        conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (report_id,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(report["reporter_id"]))
            await context.bot.send_message(report["reporter_id"], t("report_rejected_user"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await query.edit_message_text(t("report_rejected_staff"))



def fmt_duration(seconds):
    """Человекочитаемая длительность на текущем языке."""
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    lang = cur_lang()
    hu = {"ru": "ч", "uz": "soat", "en": "h"}.get(lang, "h")
    mu = {"ru": "мин", "uz": "daq", "en": "min"}.get(lang, "min")
    if h > 0:
        return f"{h} {hu} {m} {mu}"
    return f"{m} {mu}"


async def show_profile(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if is_unlimited(user):
        vip_status = t("vip_forever")
        coins_display = "∞"
    elif is_vip(user):
        vip_status = t("vip_until", date=user['vip_until'][:10])
        coins_display = user['coins']
    else:
        vip_status = t("vip_none")
        coins_display = user['coins']
    # Время в чат-рулетке (раздельно: обычная и 18+)
    secs = 0
    secs_18 = 0
    for s in conn.execute(
        "SELECT started_at, ended_at, mode FROM roulette_sessions WHERE user1_id=? OR user2_id=?",
        (uid, uid),
    ).fetchall():
        try:
            start = datetime.fromisoformat(s["started_at"])
            end = datetime.fromisoformat(s["ended_at"]) if s["ended_at"] else now_dt()
            dur = max(0, (end - start).total_seconds())
        except (ValueError, TypeError):
            continue
        try:
            smode = s["mode"] or "normal"
        except (KeyError, IndexError, TypeError):
            smode = "normal"
        if smode == "18plus":
            secs_18 += dur
        else:
            secs += dur
    # Сообщения по ссылке (анонимки question/valentine)
    sent = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE from_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    received = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE to_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    # Потрачено звёзд на покупку коинов
    stars_spent = conn.execute(
        "SELECT COALESCE(SUM(stars),0) s FROM star_purchases WHERE user_id=?",
        (uid,),
    ).fetchone()["s"]
    # Приглашено друзей и место в топе пригласивших
    invited = conn.execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)
    ).fetchone()["c"]
    if invited > 0:
        higher = conn.execute(
            "SELECT COUNT(*) c FROM (SELECT referrer_id, COUNT(*) c FROM referrals "
            "WHERE active=1 GROUP BY referrer_id) WHERE c > ?",
            (invited,),
        ).fetchone()["c"]
        rank = f"#{higher + 1}"
    else:
        rank = "—"
    # Дата регистрации
    try:
        reg_date = datetime.fromisoformat(user["created_at"]).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        reg_date = "—"
    name = user["first_name"] or "—"
    if user["username"]:
        name += f" (@{user['username']})"
    _age_int = user_age_int(user)
    age_display = str(_age_int) if _age_int is not None else "—"
    text = t(
        "profile_full",
        id=uid,
        name=html.escape(name),
        gender=gender_label(user['gender']),
        age=age_display,
        roulette_time=fmt_duration(secs),
        sent=sent,
        received=received,
        invited=invited,
        rank=rank,
        coins=coins_display,
        vip=vip_status,
        stars=stars_spent,
        reg_date=reg_date,
    )
    # Для совершеннолетних — строка о времени в 18+ чате
    if is_adult(user):
        text += "\n" + t("profile_18plus_line", time=fmt_duration(secs_18))
    await clean_screen(update, context)
    context.user_data["state"] = "profile"
    await send_menu(update, context, text, profile_kb(), parse_mode="HTML")


async def profile_router(update, context):
    text = canon(update.message.text)
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if text == "✏️ Сменить пол":
        context.user_data["state"] = "set_gender_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("choose_new_gender"), gender_kb(with_back=True))
        return
    if text == "✏️ Изменить возраст":
        context.user_data["state"] = "set_age_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("age_register_ask"), age_back_kb(), parse_mode="HTML")
        return
    if text == "🎁 Подарить коины":
        context.user_data["state"] = "giftcoins_id"
        await clean_screen(update, context)
        await send_menu(update, context, t("giftcoins_ask_id"), cancel_reply_kb(), parse_mode="HTML")
        return
    await context.bot.send_message(update.effective_chat.id, t("choose_action"), reply_markup=profile_kb())


async def gift_coins_router(update, context):
    """Дарение коинов другу: ввод ID → сумма → перевод с баланса."""
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    if canon(text) in ("❌ Отмена", "⬅️ Назад"):
        context.user_data["state"] = None
        await show_profile(update, context)
        return
    if state == "giftcoins_id":
        target = resolve_user_ref(text)
        if target is None:
            await update.message.reply_text(t("gift_user_not_found"), reply_markup=cancel_reply_kb())
            return
        if target == uid:
            await update.message.reply_text(t("gift_not_self"), reply_markup=cancel_reply_kb())
            return
        context.user_data["giftcoins_target"] = target
        context.user_data["state"] = "giftcoins_amount"
        bal = get_user(uid)["coins"]
        await update.message.reply_text(t("giftcoins_ask_amount", balance=bal), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    if state == "giftcoins_amount":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text(t("giftcoins_amount_number"), reply_markup=cancel_reply_kb())
            return
        amount = int(text)
        user = get_user(uid)
        if not is_unlimited(user) and (user["coins"] or 0) < amount:
            await update.message.reply_text(t("giftcoins_not_enough", balance=user["coins"]), reply_markup=cancel_reply_kb())
            return
        target = context.user_data.get("giftcoins_target")
        if not is_unlimited(user):
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (amount, uid))
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amount, target))
        conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("giftcoins_target", None)
        # Уведомляем получателя
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("giftcoins_received", amount=amount),
                                           parse_mode="HTML", reply_markup=main_menu_kb(target))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await nav(update, context, t("giftcoins_sent", id=target, amount=amount),
                  main_menu_kb(uid), parse_mode="HTML")
        return


def age_back_kb():
    """Клавиатура смены возраста в профиле — только кнопка возврата (ввод числом)."""
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))


def searching_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⛔ Отменить поиск")]], resize_keyboard=True))


def cancel_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))


def link_code_kb():
    """Клавиатура ввода кода ссылки — с постоянной кнопкой «Назад»."""
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))


def bcast_audience_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👥 Всем")],
        [KeyboardButton("👨 Мужчинам"), KeyboardButton("👩 Женщинам")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def in_chat_kb():
    """Reply-клавиатура управления чатом — закреплена ВНИЗУ экрана (не уезжает с перепиской)."""
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➡️ Далее"), KeyboardButton("⏹️ Стоп")],
    ], resize_keyboard=True))


def left_chat_kb():
    """Reply-клавиатура после ухода собеседника: новый поиск / жалоба / меню."""
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Новый поиск")],
        [KeyboardButton("🚩 Пожаловаться"), KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def get_active_session(user_id):
    return conn.execute(
        "SELECT * FROM roulette_sessions WHERE active=1 AND (user1_id=? OR user2_id=?)",
        (user_id, user_id),
    ).fetchone()



async def show_roulette_entry(update, context):
    user = get_user(update.effective_user.id)
    active = get_active_session(user["tg_id"])
    await clean_screen(update, context)
    if active:
        UD[user["tg_id"]]["state"] = "rchat"
        await context.bot.send_message(update.effective_chat.id, t("roulette_already_chat"), reply_markup=in_chat_kb())
        return
    in_queue = conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (user["tg_id"],)).fetchone()
    if in_queue:
        await context.bot.send_message(update.effective_chat.id, t("roulette_searching"), reply_markup=searching_kb())
        return
    context.user_data["state"] = "roulette_pref"
    await send_menu(update, context, t("roulette_who"), roulette_pref_reply_kb())


async def roulette_pref_router(update, context):
    text = canon(update.message.text)
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    pref = {"👨 Парня": "m", "👩 Девушку": "f", "🤷 Любого": "any"}.get(text)
    if not pref:
        await context.bot.send_message(update.effective_chat.id, t("pick_on_kb"), reply_markup=roulette_pref_reply_kb())
        return
    user = get_user(update.effective_user.id)
    conn.execute("UPDATE users SET search_pref=? WHERE tg_id=?", (pref, user["tg_id"]))
    conn.execute(
        "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, joined_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, joined_at=excluded.joined_at",
        (user["tg_id"], user["gender"], pref, 1 if is_vip(user) else 0, now_iso()),
    )
    conn.commit()
    context.user_data["state"] = None
    await clean_screen(update, context)
    await context.bot.send_message(update.effective_chat.id, t("roulette_finding_partner"), reply_markup=searching_kb())


async def on_roulette_cancel(update, context):
    query = update.callback_query
    await query.answer()
    conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (query.from_user.id,))
    conn.commit()
    await query.edit_message_text(t("roulette_stop"))
    await context.bot.send_message(query.from_user.id, t("main_menu"), reply_markup=main_menu_kb(query.from_user.id))


def compatible(a, b):
    a_ok = a["pref"] == "any" or a["pref"] == b["gender"]
    b_ok = b["pref"] == "any" or b["pref"] == a["gender"]
    return a_ok and b_ok


def _q_int(row, key):
    """Безопасно достаёт целое поле из строки очереди."""
    try:
        v = row[key]
        return int(v) if v is not None else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def age_match(a, b):
    """Взаимный фильтр по возрасту для 18+: возраст каждого попадает в диапазон другого."""
    a_age = _q_int(a, "actual_age")
    b_age = _q_int(b, "actual_age")
    a_min = _q_int(a, "age_min") or 18
    a_max = _q_int(a, "age_max") or 200
    b_min = _q_int(b, "age_min") or 18
    b_max = _q_int(b, "age_max") or 200
    # Если возраст неизвестен — не блокируем (совместимость по умолчанию)
    a_ok = (b_age is None) or (a_min <= b_age <= a_max)
    b_ok = (a_age is None) or (b_min <= a_age <= b_max)
    return a_ok and b_ok


def is_banned_pair(u1, u2):
    row = conn.execute(
        "SELECT 1 FROM bans WHERE until>? AND "
        "((owner_id=? AND banned_id=?) OR (owner_id=? AND banned_id=?))",
        (now_iso(), u1, u2, u2, u1),
    ).fetchone()
    return row is not None



async def roulette_matchmaker(context: ContextTypes.DEFAULT_TYPE):
    rows = conn.execute("SELECT * FROM roulette_queue ORDER BY is_vip DESC, joined_at ASC").fetchall()
    matched_ids = set()

    async def _pair(a, b, a_mode):
        conn.execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", (a["user_id"], b["user_id"]))
        conn.execute(
            "INSERT INTO roulette_sessions (user1_id, user2_id, active, mode, started_at) VALUES (?, ?, 1, ?, ?)",
            (a["user_id"], b["user_id"], a_mode, now_iso()),
        )
        conn.commit()
        matched_ids.add(a["user_id"]); matched_ids.add(b["user_id"])
        is_18 = (a_mode == "18plus")
        for uid in (a["user_id"], b["user_id"]):
            try:
                _sl = cur_lang(); set_cur_lang(get_lang(uid))
                if is_18:
                    await context.bot.send_message(uid, t("roulette_found_18plus"), parse_mode="HTML", reply_markup=in_chat_kb())
                    UD[uid]["state"] = "18plus_rchat"
                else:
                    await context.bot.send_message(uid, t("roulette_found"), parse_mode="HTML", reply_markup=in_chat_kb())
                    UD[uid]["state"] = "rchat"
                set_cur_lang(_sl)
            except TelegramError:
                pass

    # strict_age=True — учитываем взаимный фильтр по возрасту (только для 18+).
    # Второй проход (strict_age=False) соединяет оставшихся 18+ по полу, чтобы люди находились.
    async def run_pass(strict_age):
        for i, a in enumerate(rows):
            if a["user_id"] in matched_ids:
                continue
            for b in rows[i + 1:]:
                if b["user_id"] in matched_ids:
                    continue
                a_mode = (a["mode"] if "mode" in a.keys() else None) or "normal"
                b_mode = (b["mode"] if "mode" in b.keys() else None) or "normal"
                if a_mode != b_mode:
                    continue
                if a_mode == "18plus" and strict_age and not age_match(a, b):
                    continue
                if compatible(a, b) and not is_banned_pair(a["user_id"], b["user_id"]):
                    await _pair(a, b, a_mode)
                    break

    await run_pass(strict_age=True)
    await run_pass(strict_age=False)


async def end_roulette_session(context, ender_id, requeue_ender=False):
    session = get_active_session(ender_id)
    if not session:
        return None
    other_id = session["user2_id"] if session["user1_id"] == ender_id else session["user1_id"]
    conn.execute(
        "UPDATE roulette_sessions SET active=0, ended_by=?, ended_at=? WHERE id=?",
        (ender_id, now_iso(), session["id"]),
    )
    conn.commit()
    # Уведомить модераторов-наблюдателей и перекинуть их на другую сессию
    await handle_spectators_on_end(context, session["id"])
    # Второму участнику: сообщение «собеседник ушёл» + reply-клавиатура снизу (на его языке)
    _smode = "normal"
    try:
        _smode = session["mode"] or "normal"
    except (KeyError, IndexError, TypeError):
        _smode = "normal"
    UD[other_id]["state"] = "rleft"
    UD[other_id]["last_session"] = session["id"]
    UD[other_id]["last_mode"] = _smode
    _sl = cur_lang()
    set_cur_lang(get_lang(other_id))
    try:
        await context.bot.send_message(other_id, t("roulette_left"), reply_markup=left_chat_kb())
    except TelegramError:
        pass
    set_cur_lang(_sl)
    if requeue_ender:
        user = get_user(ender_id)
        sess_mode = "normal"
        try:
            sess_mode = session["mode"] or "normal"
        except (KeyError, IndexError, TypeError):
            sess_mode = "normal"
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, mode=excluded.mode, joined_at=excluded.joined_at",
            (ender_id, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, sess_mode, now_iso()),
        )
        conn.commit()
    return session


async def _requeue_and_search(context, uid, mode="normal"):
    """Ставит пользователя в очередь с его прежними настройками и показывает экран поиска."""
    user = get_user(uid)
    if mode == "18plus":
        my_age = user_age_int(user) or 18
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, actual_age, age_min, age_max, joined_at) "
            "VALUES (?, ?, ?, ?, '18plus', ?, 18, 200, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, "
            "mode=excluded.mode, actual_age=excluded.actual_age, age_min=excluded.age_min, age_max=excluded.age_max, joined_at=excluded.joined_at",
            (uid, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, my_age, now_iso()),
        )
    else:
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, mode=excluded.mode, joined_at=excluded.joined_at",
            (uid, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, mode, now_iso()),
        )
    conn.commit()
    UD[uid]["state"] = None
    await context.bot.send_message(uid, t("roulette_finding_partner"), reply_markup=searching_kb())


# ── Управление чат-рулеткой через reply-кнопки (снизу) ──

async def rchat_next(update, context):
    """Кнопка «Далее»: завершить чат и искать нового с теми же настройками."""
    uid = update.effective_user.id
    sess = get_active_session(uid)
    sess_mode = "normal"
    if sess:
        try:
            sess_mode = sess["mode"] or "normal"
        except (KeyError, IndexError, TypeError):
            sess_mode = "normal"
    await end_roulette_session(context, uid, requeue_ender=False)
    context.user_data["state"] = None
    await _requeue_and_search(context, uid, mode=sess_mode)


async def rchat_stop(update, context):
    """Кнопка «Стоп»: завершить чат и вернуться к выбору, кого искать."""
    uid = update.effective_user.id
    sess = get_active_session(uid)
    sess_mode = "normal"
    if sess:
        try:
            sess_mode = sess["mode"] or "normal"
        except (KeyError, IndexError, TypeError):
            sess_mode = "normal"
    await end_roulette_session(context, uid, requeue_ender=False)
    if sess_mode == "18plus":
        context.user_data["state"] = "18plus_pref"
        await context.bot.send_message(uid, t("roulette_who"), reply_markup=eighteen_plus_roulette_pref_kb())
    else:
        context.user_data["state"] = "roulette_pref"
        await context.bot.send_message(uid, t("roulette_who"), reply_markup=roulette_pref_reply_kb())


async def rleft_research(update, context):
    """Кнопка «Новый поиск» у того, кого покинули."""
    uid = update.effective_user.id
    last_mode = context.user_data.get("last_mode", "normal")
    context.user_data["state"] = None
    context.user_data.pop("last_session", None)
    context.user_data.pop("last_mode", None)
    if get_active_session(uid):
        return
    if conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (uid,)).fetchone():
        await context.bot.send_message(uid, t("roulette_finding_partner"), reply_markup=searching_kb())
        return
    await _requeue_and_search(context, uid, mode=last_mode)


async def rleft_report(update, context):
    """Кнопка «Пожаловаться» у того, кого покинули."""
    uid = update.effective_user.id
    sid = context.user_data.get("last_session")
    session = conn.execute("SELECT * FROM roulette_sessions WHERE id=?", (sid,)).fetchone() if sid else None
    if not session:
        context.user_data["state"] = None
        await update.message.reply_text(t("session_not_found"), reply_markup=main_menu_kb(uid))
        return
    reported_id = session["user2_id"] if uid == session["user1_id"] else session["user1_id"]
    context.user_data["state"] = "awaiting_report_reason"
    context.user_data["report_context"] = "roulette"
    context.user_data["report_ref_id"] = sid
    context.user_data["reported_id"] = reported_id
    context.user_data.pop("last_session", None)
    await update.message.reply_text(t("report_choose"), reply_markup=report_reason_kb())



async def relay_roulette_message(update, context):
    session = get_active_session(update.effective_user.id)
    if not session:
        return False
    other_id = session["user2_id"] if session["user1_id"] == update.effective_user.id else session["user1_id"]
    # Режим сессии: в 18+ чате разрешено отправлять всё (фильтр не применяется)
    try:
        sess_mode = session["mode"] or "normal"
    except (KeyError, IndexError, TypeError):
        sess_mode = "normal"
    # Анти-спам: блокируем контакты/ссылки/соцсети в обычной рулетке (кроме персонала и 18+ чата)
    txt = update.message.text if update.message else None
    if (sess_mode != "18plus" and txt and not is_staff(update.effective_user.id)
            and has_forbidden_contacts(txt)):
        try:
            await update.message.reply_text(t("no_contacts"))
        except TelegramError:
            pass
        return True
    try:
        await context.bot.copy_message(other_id, update.effective_chat.id, update.message.message_id)
    except TelegramError:
        pass
    # Трансляция модераторам-наблюдателям (/tg), если они есть
    await relay_to_spectators(context, session, update.effective_user.id,
                              update.effective_chat.id, update.message.message_id)
    return True


async def on_roulette_report(update, context):
    query = update.callback_query
    await query.answer()
    session_id = int(query.data.split(":")[1])
    session = conn.execute("SELECT * FROM roulette_sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        await query.answer(t("session_not_found"), show_alert=True)
        return
    reporter_id = query.from_user.id
    # reporter — тот, кому ушёл собеседник (он получил кнопку «Жалоба»)
    # reported — тот, кто ушёл (ended_by)
    ended_by = session["ended_by"]
    # Определяем reported_id: тот участник сессии, который НЕ является репортером
    if reporter_id == session["user1_id"]:
        reported_id = session["user2_id"]
    elif reporter_id == session["user2_id"]:
        reported_id = session["user1_id"]
    else:
        # Кнопку нажал посторонний — игнорируем
        return
    if reporter_id == reported_id:
        return
    context.user_data["state"] = "awaiting_report_reason"
    context.user_data["report_context"] = "roulette"
    context.user_data["report_ref_id"] = session_id
    context.user_data["reported_id"] = reported_id
    await query.message.reply_text(t("report_choose"), reply_markup=report_reason_kb())


# === Модераторский мониторинг рулетки (/tg) ===
SPECTATORS = {}                          # mod_id -> session_id
SESSION_SPECTATORS = defaultdict(set)    # session_id -> {mod_id}


def tg_watch_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("🚪 Выйти")]], resize_keyboard=True)


def tg_ban_kb(session):
    u1 = get_user(session["user1_id"]); u2 = get_user(session["user2_id"])
    n1 = (u1["first_name"] if u1 else None) or str(session["user1_id"])
    n2 = (u2["first_name"] if u2 else None) or str(session["user2_id"])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🚫 Бан 1️⃣ {n1[:12]}", callback_data=f"tgban:{session['id']}:1"),
        InlineKeyboardButton(f"🚫 Бан 2️⃣ {n2[:12]}", callback_data=f"tgban:{session['id']}:2"),
    ]])


def detach_spectator(mod_id):
    sid = SPECTATORS.pop(mod_id, None)
    if sid is not None:
        SESSION_SPECTATORS[sid].discard(mod_id)
        if not SESSION_SPECTATORS[sid]:
            SESSION_SPECTATORS.pop(sid, None)


async def attach_spectator(context, mod_id, session, auto=False):
    detach_spectator(mod_id)
    SPECTATORS[mod_id] = session["id"]
    SESSION_SPECTATORS[session["id"]].add(mod_id)
    UD[mod_id]["state"] = "tg_watch"
    u1 = get_user(session["user1_id"]); u2 = get_user(session["user2_id"])
    head = "🔄 <b>Новая сессия для наблюдения</b>" if auto else "👁 <b>Вы наблюдаете за сессией</b>"
    info = (f"{head}\n1️⃣ {user_mention(u1)}\n2️⃣ {user_mention(u2)}\n\n"
            "Сообщения участников приходят сюда. Кнопки ниже — забанить.")
    try:
        await context.bot.send_message(mod_id, info, parse_mode="HTML", reply_markup=tg_watch_kb())
        await context.bot.send_message(mod_id, "Действия 👇", reply_markup=tg_ban_kb(session))
    except TelegramError:
        pass


async def relay_to_spectators(context, session, sender_id, from_chat_id, message_id):
    specs = SESSION_SPECTATORS.get(session["id"])
    if not specs:
        return
    tag = "1️⃣" if sender_id == session["user1_id"] else "2️⃣"
    for mod_id in list(specs):
        try:
            await context.bot.send_message(mod_id, f"{tag} пишет:")
            await context.bot.copy_message(mod_id, from_chat_id, message_id)
        except TelegramError:
            pass


async def handle_spectators_on_end(context, session_id):
    specs = SESSION_SPECTATORS.pop(session_id, None)
    if not specs:
        return
    for mod_id in list(specs):
        SPECTATORS.pop(mod_id, None)
        nxt = conn.execute(
            "SELECT * FROM roulette_sessions WHERE active=1 AND id<>? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        try:
            await context.bot.send_message(mod_id, "⏹ Наблюдаемая сессия завершена.")
            if nxt:
                await attach_spectator(context, mod_id, nxt, auto=True)
            else:
                UD[mod_id]["state"] = "tg_watch"
                await context.bot.send_message(
                    mod_id, "Других активных сессий нет. Нажмите 🚪 Выйти.", reply_markup=tg_watch_kb())
        except TelegramError:
            pass


def active_sessions_list_text():
    rows = conn.execute(
        "SELECT * FROM roulette_sessions WHERE active=1 ORDER BY id DESC LIMIT 30"
    ).fetchall()
    if not rows:
        return None
    lines = ["🎲 <b>Активные сессии рулетки</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for s in rows:
        u1 = get_user(s["user1_id"]); u2 = get_user(s["user2_id"])
        g1 = gender_label(u1["gender"]) if u1 and u1["gender"] else "—"
        g2 = gender_label(u2["gender"]) if u2 and u2["gender"] else "—"
        lines.append(
            f"#{s['id']}: 1️⃣ <code>{s['user1_id']}</code> ({g1}) ↔ 2️⃣ <code>{s['user2_id']}</code> ({g2})"
        )
    lines.append("\n👁 Введите ID одного из участников, чтобы наблюдать:")
    return "\n".join(lines)


async def tg_start(update, context):
    text = active_sessions_list_text()
    uid = update.effective_user.id
    if not text:
        await update.message.reply_text(
            "Сейчас нет активных сессий рулетки.", reply_markup=main_menu_kb(uid))
        return
    context.user_data["state"] = "tg_pick"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=cancel_reply_kb())


async def process_tg_pick(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if not text.isdigit():
        await update.message.reply_text("Введите ID числом (или «❌ Отмена»):", reply_markup=cancel_reply_kb())
        return
    session = get_active_session(int(text))
    if not session:
        await update.message.reply_text(
            "Активная сессия с таким участником не найдена. Попробуйте другой ID:",
            reply_markup=cancel_reply_kb())
        return
    await attach_spectator(context, uid, session)


async def on_tg_ban(update, context):
    query = update.callback_query
    await query.answer()
    if not is_staff(query.from_user.id):
        return
    _, sid, which = query.data.split(":")
    session = conn.execute("SELECT * FROM roulette_sessions WHERE id=?", (int(sid),)).fetchone()
    if not session:
        await query.answer("Сессия не найдена", show_alert=True)
        return
    target = session["user1_id"] if which == "1" else session["user2_id"]
    if is_admin(target) or is_moder(get_user(target)):
        await query.answer("Нельзя забанить персонал", show_alert=True)
        return
    conn.execute("UPDATE users SET is_banned=1 WHERE tg_id=?", (target,))
    conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (target,))
    conn.commit()
    try:
        await context.bot.send_message(target, "🚫 Вы заблокированы в боте.")
    except TelegramError:
        pass
    await query.answer(f"Пользователь {target} забанен ✅", show_alert=True)
    try:
        await context.bot.send_message(query.from_user.id, f"🚫 Забанен {which}️⃣ (ID <code>{target}</code>).", parse_mode="HTML")
    except TelegramError:
        pass


# === Сообщение пользователю от модератора (/next) ===
async def modmsg_start(update, context):
    context.user_data["state"] = "modmsg_id"
    await update.message.reply_text(
        "✉️ Введите ID пользователя, которому написать:", reply_markup=cancel_reply_kb())


async def process_modmsg_id(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if not text.isdigit():
        await update.message.reply_text("ID должен быть числом:", reply_markup=cancel_reply_kb())
        return
    if not get_user(int(text)):
        await update.message.reply_text("Пользователь не найден.", reply_markup=cancel_reply_kb())
        return
    context.user_data["modmsg_target"] = int(text)
    context.user_data["state"] = "modmsg_text"
    await update.message.reply_text("Введите сообщение для пользователя:", reply_markup=cancel_reply_kb())


async def process_modmsg_text(update, context):
    raw = update.message.text or ""
    uid = update.effective_user.id
    if canon(raw.strip()) == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("modmsg_target", None)
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    target = context.user_data.get("modmsg_target")
    moder = get_user(uid)
    moder_name = (moder["first_name"] if moder else None) or "Модератор"
    ok = False
    try:
        _sl = cur_lang(); set_cur_lang(get_lang(target))
        await context.bot.send_message(
            target, t("mod_message", name=html.escape(moder_name), text=html.escape(raw)),
            parse_mode="HTML")
        set_cur_lang(_sl)
        ok = True
    except TelegramError:
        pass
    context.user_data["state"] = None
    context.user_data.pop("modmsg_target", None)
    await update.message.reply_text(
        "✅ Отправлено." if ok else "❌ Не удалось отправить (возможно, юзер заблокировал бота).",
        reply_markup=main_menu_kb(uid))


async def show_shop(update, context):
    items = conn.execute("SELECT * FROM shop_items WHERE active=1 AND is_18plus=0").fetchall()
    context.user_data["state"] = "shop"
    context.user_data["shop_is_18plus"] = False
    viewer = get_user(update.effective_user.id)
    shop_map = {}
    rows = []
    for it in items:
        disp = effective_price(it["price"], viewer)
        label = f"{item_title(it)} — {disp} 💎"
        shop_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    context.user_data["shop_map"] = shop_map
    if is_admin(update.effective_user.id):
        rows.append([KeyboardButton("➕ Добавить товар"), KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])
    base = t("shop_title") if items else t("shop_empty")
    if items and is_vip(viewer) and not is_admin(update.effective_user.id):
        base += "\n" + t("shop_vip_note")
    await nav(update, context, base, tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)), parse_mode="HTML")


async def show_eighteen_plus_shop(update, context):
    """Магазин 18+ товаров (та же таблица shop_items, но is_18plus=1)."""
    items = conn.execute("SELECT * FROM shop_items WHERE active=1 AND is_18plus=1").fetchall()
    context.user_data["state"] = "shop"
    context.user_data["shop_is_18plus"] = True
    viewer = get_user(update.effective_user.id)
    shop_map = {}
    rows = []
    for it in items:
        disp = effective_price(it["price"], viewer)
        label = f"{item_title(it)} — {disp} 💎"
        shop_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    context.user_data["shop_map"] = shop_map
    if is_admin(update.effective_user.id):
        rows.append([KeyboardButton("➕ Добавить товар"), KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")])
    base = t("18plus_shop_title") if items else t("18plus_shop_empty")
    if items and is_vip(viewer) and not is_admin(update.effective_user.id):
        base += "\n" + t("shop_vip_note")
    await nav(update, context, base, tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)), parse_mode="HTML")


async def back_to_shop(update, context):
    """Возврат в нужный магазин (обычный или 18+) по контексту."""
    if context.user_data.get("shop_is_18plus"):
        await show_eighteen_plus_shop(update, context)
    else:
        await show_shop(update, context)


async def shop_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "🏠 Меню":
        context.user_data["shop_is_18plus"] = False
        await go_home(update, context)
        return
    if text == "⬅️ Назад":
        if context.user_data.get("shop_is_18plus"):
            # Шаг назад: из 18+ магазина в меню 18+
            context.user_data["shop_is_18plus"] = False
            context.user_data["state"] = "18plus_menu"
            await nav(update, context, t("age_gate_intro"), eighteen_plus_menu_kb(), parse_mode="HTML")
        else:
            context.user_data["state"] = None
            await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    if text == "➕ Добавить товар" and is_admin(uid):
        context.user_data["state"] = "shop_add_title"
        context.user_data["new_item"] = {}
        await nav(update, context, "📝 Название товара (текст кнопки):", cancel_reply_kb())
        return
    if text == "✏️ Изменить" and is_admin(uid):
        await shop_edit_list(update, context)
        return
    item_id = context.user_data.get("shop_map", {}).get(text)
    if item_id is None:
        await nav(update, context, t("shop_pick_item"), tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)))
        return
    item = conn.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        await nav(update, context, t("item_unavailable"), main_menu_kb(uid))
        return
    context.user_data["pending_item"] = item_id
    context.user_data["state"] = "shop_confirm"
    price = effective_price(item["price"], get_user(uid))
    if price != item["price"]:
        price_txt = t("price_vip", price=price, orig=item['price'])
    else:
        price_txt = t("price_plain", price=price)
    await nav(
        update, context,
        t("shop_buy_confirm", title=html.escape(item_title(item)), price=price_txt),
        yes_no_kb(), parse_mode="HTML",
    )


async def shop_confirm_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "❌ Отмена":
        if context.user_data.get("shop_is_18plus"):
            await show_eighteen_plus_shop(update, context)
        else:
            await show_shop(update, context)
        return
    if text != "✅ Да":
        await update.message.reply_text(t("choose_on_kb"), reply_markup=yes_no_kb())
        return
    item_id = context.user_data.get("pending_item")
    item = conn.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        context.user_data["state"] = None
        await update.message.reply_text(t("item_unavailable"), reply_markup=main_menu_kb(uid))
        return
    await do_purchase(update, context, item)


async def do_purchase(update, context, item):
    uid = update.effective_user.id
    user = get_user(uid)
    price = effective_price(item["price"], user)
    unlimited = is_unlimited(user)
    # У админа/модера — бесконечные коины: не проверяем баланс и не списываем
    if not unlimited:
        if user["coins"] < price:
            context.user_data["state"] = None
            await nav(update, context, t("not_enough_coins"), main_menu_kb(uid))
            return
        conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (price, uid))
    conn.execute(
        "INSERT INTO purchases (user_id, item_id, price_paid, created_at) VALUES (?, ?, ?, ?)",
        (uid, item["id"], price, now_iso()),
    )
    conn.commit()
    user = get_user(uid)
    discount_note = f" (со скидкой VIP, обычно {item['price']})" if price != item["price"] else ""
    await notify_staff(
        context,
        f"💰 Покупка!\nПользователь: {user_mention(user)}\n"
        f"Товар: {html.escape(item['title'])}\nЦена: {price} 💎{discount_note}",
        parse_mode="HTML",
    )
    rt = item["reward_type"] or "manual"
    if rt == "manual" and item["is_vip"]:
        rt = "vip"
    if rt == "coins":
        amt = item["reward_amount"] or 0
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, uid))
        conn.commit()
        context.user_data["state"] = None
        await nav(update, context, t("purchase_coins", amt=amt), main_menu_kb(uid), parse_mode="HTML")
    elif rt == "vip":
        days = item["reward_amount"] or item["duration_days"] or 30
        base = max(now_dt(), datetime.fromisoformat(user["vip_until"])) if user["vip_until"] else now_dt()
        new_until = base + timedelta(days=days)
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (new_until.isoformat(), uid))
        conn.commit()
        context.user_data["state"] = None
        await nav(update, context, t("purchase_vip", days=days), main_menu_kb(uid), parse_mode="HTML")
    elif rt == "moder":
        context.user_data["moder_price"] = price
        context.user_data["moder_item_id"] = item["id"]
        context.user_data["moder_app"] = {}
        context.user_data["state"] = "moder_q_gender"
        await nav(
            update, context,
            t("moder_form_gender"),
            tr_kb(ReplyKeyboardMarkup(
                [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")], [KeyboardButton("❌ Отмена")]],
                resize_keyboard=True,
            )),
            parse_mode="HTML",
        )
    elif rt == "eighteenplus":
        # Покупка доступа к 18+ чату на срок (0 = бессрочно)
        days = item["reward_amount"] if item["reward_amount"] is not None else 0
        grant_18plus_access(uid, days)
        context.user_data["state"] = None
        txt = t("purchase_18plus", days=days) if (days and days > 0) else t("purchase_18plus_forever")
        await nav(update, context, txt, main_menu_kb(uid), parse_mode="HTML")
    else:  # manual
        context.user_data["state"] = None
        await nav(
            update, context,
            t("purchase_manual"),
            main_menu_kb(uid), parse_mode="HTML",
        )


async def moder_q_router(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "❌ Отмена":
        price = context.user_data.get("moder_price", 0)
        if price:
            conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (price, uid))
            conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("moder_app", None)
        await update.message.reply_text(
            t("moder_form_cancelled", price=price),
            reply_markup=main_menu_kb(uid),
        )
        return
    app = context.user_data.setdefault("moder_app", {})
    if state == "moder_q_gender":
        app["gender"] = text
        context.user_data["state"] = "moder_q_age"
        await update.message.reply_text(t("moder_form_age"), reply_markup=cancel_reply_kb())
    elif state == "moder_q_age":
        app["age"] = text
        context.user_data["state"] = "moder_q_tgtime"
        await update.message.reply_text(t("moder_form_tg"), reply_markup=cancel_reply_kb())
    elif state == "moder_q_tgtime":
        app["tg_time"] = text
        context.user_data["state"] = "moder_q_avail"
        await update.message.reply_text(t("moder_form_avail"), reply_markup=cancel_reply_kb())
    elif state == "moder_q_avail":
        app["availability"] = text
        await submit_moder_app(update, context)


async def submit_moder_app(update, context):
    uid = update.effective_user.id
    app = context.user_data.get("moder_app", {})
    price = context.user_data.get("moder_price", 0)
    item_id = context.user_data.get("moder_item_id")
    cur = conn.execute(
        "INSERT INTO moder_apps (user_id, item_id, price_paid, gender, age, tg_time, availability, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (uid, item_id, price, app.get("gender"), app.get("age"), app.get("tg_time"), app.get("availability"), now_iso()),
    )
    conn.commit()
    app_id = cur.lastrowid
    context.user_data["state"] = None
    context.user_data.pop("moder_app", None)
    user = get_user(uid)
    text = (
        f"🛡 Заявка на модератора #{app_id}\n"
        f"Пользователь: {user_mention(user)}\n"
        f"Пол: {html.escape(app.get('gender') or '—')}\n"
        f"Возраст: {html.escape(app.get('age') or '—')}\n"
        f"Время в ТГ/день: {html.escape(app.get('tg_time') or '—')}\n"
        f"Доступность: {html.escape(app.get('availability') or '—')}\n"
        f"Оплачено: {price} 💎"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=moder_decision_kb(app_id))
        except TelegramError:
            pass
    await update.message.reply_text(
        t("moder_form_sent"),
        reply_markup=main_menu_kb(uid),
    )


async def on_moder_app_decision(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer(t("admin_only"), show_alert=True)
        return
    _, decision, app_id = query.data.split(":")
    app_id = int(app_id)
    app = conn.execute("SELECT * FROM moder_apps WHERE id=?", (app_id,)).fetchone()
    if not app or app["status"] != "pending":
        await query.edit_message_text(t("moder_app_already"))
        return
    buyer_id = app["user_id"]
    if decision == "ok":
        conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=?", (buyer_id,))
        conn.execute("UPDATE moder_apps SET status='approved' WHERE id=?", (app_id,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(buyer_id))
            await context.bot.send_message(
                buyer_id,
                t("moder_granted_shop"),
                parse_mode="HTML",
                reply_markup=main_menu_kb(buyer_id),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await query.edit_message_text(t("moder_granted_staff"))
    else:
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (app["price_paid"], buyer_id))
        conn.execute("UPDATE moder_apps SET status='rejected' WHERE id=?", (app_id,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(buyer_id))
            await context.bot.send_message(
                buyer_id,
                t("moder_rejected_user", coins=app['price_paid']),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await query.edit_message_text(t("moder_rejected_staff"))


async def on_age_verify_decision(update, context):
    """Админ одобряет/отклоняет заявку на подтверждение возраста 18+."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer(t("admin_only"), show_alert=True)
        return
    _, decision, uid = query.data.split(":")
    uid = int(uid)
    req = conn.execute(
        "SELECT * FROM age_verification_requests WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (uid,),
    ).fetchone()
    if not req:
        await query.answer(t("age_verify_already"), show_alert=True)
        try:
            await query.edit_message_caption(caption=t("age_verify_already"))
        except TelegramError:
            pass
        return
    if decision == "ok":
        # Возраст подтверждён — ставим 18 (числовой, чтобы открылся доступ к 18+)
        conn.execute("UPDATE users SET age='18' WHERE tg_id=?", (uid,))
        conn.execute("UPDATE age_verification_requests SET status='approved', responded_at=? WHERE id=?",
                     (now_iso(), req["id"]))
        conn.commit()
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(uid))
            await context.bot.send_message(uid, t("age_verification_approved"), parse_mode="HTML",
                                           reply_markup=main_menu_kb(uid))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        try:
            await query.edit_message_caption(caption=t("age_verify_approved_staff"))
        except TelegramError:
            pass
    else:
        conn.execute("UPDATE age_verification_requests SET status='rejected', responded_at=? WHERE id=?",
                     (now_iso(), req["id"]))
        conn.commit()
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(uid))
            await context.bot.send_message(uid, t("age_verification_rejected", reason=""), parse_mode="HTML")
            set_cur_lang(_sl)
        except TelegramError:
            pass
        try:
            await query.edit_message_caption(caption=t("age_verify_rejected_staff"))
        except TelegramError:
            pass


async def process_shop_add(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    item = context.user_data.setdefault("new_item", {})
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(update.effective_user.id))
        await back_to_shop(update, context)
        return
    if state == "shop_add_title":
        await update.message.reply_text("⏳ Перевожу название на 3 языка…")
        ru, uz, en = await translate_to_all(text)
        item["title"] = ru
        item["title_uz"] = uz
        item["title_en"] = en
        context.user_data["state"] = "shop_add_price"
        await update.message.reply_text(
            f"📝 Название сохранено:\n🇷🇺 {ru}\n🇺🇿 {uz}\n🇬🇧 {en}\n\n💰 Цена в коинах:",
            reply_markup=cancel_reply_kb(),
        )
    elif state == "shop_add_price":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        item["price"] = int(text)
        # В 18+ магазине — товар = доступ к 18+ чату на срок (без VIP/Модер/Коины)
        if context.user_data.get("shop_is_18plus"):
            item["reward_type"] = "eighteenplus"
            context.user_data["state"] = "shop_add_18plus_days"
            await update.message.reply_text(
                "⏳ На сколько дней открывать доступ к 18+ чату при покупке?\n(например: 7, 30. Введите 0 — бессрочно/навсегда)",
                reply_markup=cancel_reply_kb(),
            )
            return
        context.user_data["state"] = "shop_add_reward"
        await update.message.reply_text("🎁 Что получит покупатель при покупке?", reply_markup=reward_type_kb())
    elif state == "shop_add_18plus_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней (0 — навсегда):", reply_markup=cancel_reply_kb())
            return
        item["reward_amount"] = int(text)   # 0 = бессрочно
        await _finalize_new_item(update, context)
    elif state == "shop_add_reward":
        mp = {"💎 Коины": "coins", "⏳ VIP": "vip", "🛡 Модер": "moder", "📦 Вручную": "manual"}
        rt = mp.get(text)
        if not rt:
            await update.message.reply_text("Выберите тип награды 👇", reply_markup=reward_type_kb())
            return
        item["reward_type"] = rt
        if rt == "coins":
            context.user_data["state"] = "shop_add_amount"
            await update.message.reply_text("Сколько коинов начислять при покупке?", reply_markup=cancel_reply_kb())
        elif rt == "vip":
            context.user_data["state"] = "shop_add_days"
            await update.message.reply_text("На сколько дней давать VIP?", reply_markup=cancel_reply_kb())
        else:
            await _finalize_new_item(update, context)
    elif state == "shop_add_amount":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        item["reward_amount"] = int(text)
        await _finalize_new_item(update, context)
    elif state == "shop_add_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней:", reply_markup=cancel_reply_kb())
            return
        item["reward_amount"] = int(text)
        await _finalize_new_item(update, context)


async def _finalize_new_item(update, context):
    """Сохраняет товар в ТОТ магазин, где админ сейчас (обычный или 18+) — без лишнего вопроса о разделе."""
    item = context.user_data.get("new_item", {})
    item["is_18plus"] = 1 if context.user_data.get("shop_is_18plus") else 0
    save_new_item(item)
    context.user_data["state"] = None
    is18 = item.get("is_18plus")
    if is18:
        days = item.get("reward_amount") or 0
        srok = f"на {days} дн." if days else "бессрочно"
        msg = f"✅ Товар 18+ добавлен!\n⏳ Доступ к 18+ чату: <b>{srok}</b>"
    else:
        msg = "✅ Товар добавлен в магазин!"
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_menu_kb(update.effective_user.id))
    if is18:
        await show_eighteen_plus_shop(update, context)
    else:
        await show_shop(update, context)


def shop_category_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🛒 Обычный товар")],
        [KeyboardButton("🔞 Товар 18+")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def save_new_item(item):
    rt = item.get("reward_type", "manual")
    conn.execute(
        "INSERT INTO shop_items (title, title_uz, title_en, price, is_vip, duration_days, reward_type, reward_amount, is_18plus, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            item["title"], item.get("title_uz"), item.get("title_en"), item["price"],
            1 if rt == "vip" else 0,
            item.get("reward_amount") if rt == "vip" else None,
            rt,
            item.get("reward_amount"),
            item.get("is_18plus", 0),
        ),
    )
    conn.commit()


async def shop_edit_list(update, context):
    is18 = 1 if context.user_data.get("shop_is_18plus") else 0
    items = conn.execute("SELECT * FROM shop_items WHERE active=1 AND is_18plus=?", (is18,)).fetchall()
    if not items:
        context.user_data["state"] = None
        await update.message.reply_text("Нет товаров для редактирования.", reply_markup=main_menu_kb(update.effective_user.id))
        return
    edit_map = {}
    rows = []
    for it in items:
        label = f"{it['title']} — {it['price']} 💎"
        edit_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    rows.append([KeyboardButton("⬅️ Назад")])
    context.user_data["edit_map"] = edit_map
    context.user_data["state"] = "shop_edit_pick"
    await update.message.reply_text("Выберите товар для изменения 👇", reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)))


def shop_edit_item_kb(item):
    rows = [[KeyboardButton("📝 Название"), KeyboardButton("💰 Цена")]]
    if item["reward_type"] == "coins":
        rows.append([KeyboardButton("💎 Сумма коинов")])
    elif item["reward_type"] == "vip" or item["is_vip"]:
        rows.append([KeyboardButton("⏳ Срок VIP")])
    elif item["reward_type"] == "eighteenplus":
        rows.append([KeyboardButton("⏳ Срок доступа")])
    rows.append([KeyboardButton("🗑 Удалить товар")])
    rows.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def shop_edit_router(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text)
    uid = update.effective_user.id
    if state == "shop_edit_pick":
        if text == "⬅️ Назад":
            await back_to_shop(update, context)
            return
        item_id = context.user_data.get("edit_map", {}).get(text)
        if item_id is None:
            await update.message.reply_text("Выберите товар на клавиатуре 👇")
            return
        context.user_data["edit_item_id"] = item_id
        context.user_data["state"] = "shop_edit_menu"
        item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
        await update.message.reply_text(
            f"Товар: {item['title']} — {item['price']} 💎\nЧто изменить?",
            reply_markup=shop_edit_item_kb(item),
        )
        return
    # state == "shop_edit_menu"
    item_id = context.user_data.get("edit_item_id")
    item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        await back_to_shop(update, context)
        return
    if text == "⬅️ Назад":
        await shop_edit_list(update, context)
        return
    if text == "📝 Название":
        context.user_data["state"] = "shop_edit_name"
        await update.message.reply_text("Новое название:", reply_markup=cancel_reply_kb())
        return
    if text == "💰 Цена":
        context.user_data["state"] = "shop_edit_price"
        await update.message.reply_text("Новая цена в коинах:", reply_markup=cancel_reply_kb())
        return
    if text == "💎 Сумма коинов":
        context.user_data["state"] = "shop_edit_amount"
        await update.message.reply_text("Новая сумма коинов:", reply_markup=cancel_reply_kb())
        return
    if text == "⏳ Срок VIP":
        context.user_data["state"] = "shop_edit_days"
        await update.message.reply_text("Новый срок VIP (дней):", reply_markup=cancel_reply_kb())
        return
    if text == "⏳ Срок доступа":
        context.user_data["state"] = "shop_edit_18plus_days"
        await update.message.reply_text("Новый срок доступа к 18+ (дней, 0 — навсегда):", reply_markup=cancel_reply_kb())
        return
    if text == "🗑 Удалить товар":
        conn.execute("UPDATE shop_items SET active=0 WHERE id=?", (item_id,))
        conn.commit()
        await update.message.reply_text("🗑 Товар удалён.", reply_markup=main_menu_kb(uid))
        await back_to_shop(update, context)
        return
    await update.message.reply_text("Выберите действие 👇", reply_markup=shop_edit_item_kb(item))


async def process_shop_edit_value(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    item_id = context.user_data.get("edit_item_id")
    if text == "❌ Отмена":
        context.user_data["state"] = "shop_edit_menu"
        item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
        await update.message.reply_text("Отменено.", reply_markup=shop_edit_item_kb(item))
        return
    if state == "shop_edit_name":
        ru, uz, en = await translate_to_all(text)
        conn.execute("UPDATE shop_items SET title=?, title_uz=?, title_en=? WHERE id=?", (ru, uz, en, item_id))
        conn.commit()
        msg = f"✅ Название изменено:\n🇷🇺 {ru}\n🇺🇿 {uz}\n🇬🇧 {en}"
    elif state == "shop_edit_price":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET price=? WHERE id=?", (int(text), item_id))
        conn.commit()
        msg = "✅ Цена изменена."
    elif state == "shop_edit_amount":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET reward_amount=? WHERE id=?", (int(text), item_id))
        conn.commit()
        msg = "✅ Сумма коинов изменена."
    elif state == "shop_edit_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней:", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET reward_amount=?, duration_days=? WHERE id=?", (int(text), int(text), item_id))
        conn.commit()
        msg = "✅ Срок VIP изменён."
    elif state == "shop_edit_18plus_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней (0 — навсегда):", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET reward_amount=? WHERE id=?", (int(text), item_id))
        conn.commit()
        msg = "✅ Срок доступа к 18+ изменён."
    else:
        msg = "Готово."
    context.user_data["state"] = "shop_edit_menu"
    item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
    await update.message.reply_text(msg, reply_markup=shop_edit_item_kb(item))


async def show_admin_menu(update, context):
    if not is_admin(update.effective_user.id):
        return
    context.user_data["state"] = "admin"
    await nav(update, context, "🛠 <b>Админ-панель</b>", admin_menu_kb(), parse_mode="HTML")


async def show_moder_menu(update, context):
    u = get_user(update.effective_user.id)
    if not is_moder(u):
        return
    context.user_data["state"] = "moder"
    await nav(update, context, "🛡 <b>Панель модератора</b>", moder_menu_kb(), parse_mode="HTML")


def admin_moder_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Выдать модера"), KeyboardButton("➖ Забрать модера")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


async def show_admin_moder(update, context):
    context.user_data["state"] = "admin_moder"
    rows = conn.execute(
        "SELECT * FROM users WHERE is_moder=1 OR (moder_until IS NOT NULL AND moder_until>?) "
        "ORDER BY tg_id",
        (now_iso(),),
    ).fetchall()
    if not rows:
        text = ("🛡 <b>Модераторы</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                "Пока нет ни одного модератора.")
    else:
        lines = [f"🛡 <b>Модераторы</b> — всего: <b>{len(rows)}</b>",
                 "━━━━━━━━━━━━━━━━━━━━"]
        for i, u in enumerate(rows, 1):
            name = u["first_name"] or "—"
            uname = f"@{u['username']}" if u["username"] else "без юзернейма"
            if u["is_moder"]:
                kind = "♾ постоянный"
            else:
                try:
                    kind = "⏳ до " + datetime.fromisoformat(u["moder_until"]).strftime("%d.%m.%Y")
                except (ValueError, TypeError):
                    kind = "⏳ временный"
            key = " · 🔓 админ-доступ" if u["admin_unlocked"] else ""
            lines.append(
                f"{i}. {html.escape(name)} ({uname})\n"
                f"   🆔 <code>{u['tg_id']}</code> · {kind}{key}"
            )
        text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=admin_moder_kb())


async def admin_moder_router(update, context):
    text = canon(update.message.text)
    if text == "⬅️ Назад":
        await show_admin_menu(update, context)
        return
    if text == "➕ Выдать модера":
        context.user_data["state"] = "moder_give_id"
        await update.message.reply_text("Введите ID пользователя для выдачи модерки:", reply_markup=cancel_reply_kb())
        return
    if text == "➖ Забрать модера":
        context.user_data["state"] = "moder_take_id"
        await update.message.reply_text("Введите ID пользователя для снятия модерки:", reply_markup=cancel_reply_kb())
        return
    await update.message.reply_text("Выберите действие 👇", reply_markup=admin_moder_kb())


async def process_moder_give_take(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    if text == "❌ Отмена":
        await show_admin_moder(update, context)
        return
    if not text.isdigit():
        await update.message.reply_text("ID должен быть числом:", reply_markup=cancel_reply_kb())
        return
    target = int(text)
    if not get_user(target):
        await update.message.reply_text("Пользователь не найден (он должен хоть раз запустить бота).", reply_markup=admin_moder_kb())
        context.user_data["state"] = "admin_moder"
        return
    if state == "moder_give_id":
        conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=?", (target,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("moder_granted_user"), reply_markup=main_menu_kb(target))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await update.message.reply_text(f"✅ Модерка выдана пользователю {target}.", reply_markup=admin_moder_kb())
    else:
        conn.execute("UPDATE users SET is_moder=0 WHERE tg_id=?", (target,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("moder_taken_user"), reply_markup=main_menu_kb(target))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await update.message.reply_text(f"✅ Модерка снята у пользователя {target}.", reply_markup=admin_moder_kb())
    context.user_data["state"] = "admin_moder"


async def start_ban(update, context, back_state):
    context.user_data["ban_back"] = back_state
    context.user_data["state"] = "ban_id"
    await update.message.reply_text(
        "Введите ID пользователя для бана/разбана (повторный ввод снимет бан):",
        reply_markup=cancel_reply_kb(),
    )


async def process_ban(update, context):
    text = canon(update.message.text.strip())
    back_state = context.user_data.get("ban_back", "admin")
    back_kb = admin_menu_kb() if back_state == "admin" else moder_menu_kb()
    if text == "❌ Отмена":
        context.user_data["state"] = back_state
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return
    if not text.isdigit():
        await update.message.reply_text("ID должен быть числом:", reply_markup=cancel_reply_kb())
        return
    target = int(text)
    u = get_user(target)
    if not u:
        await update.message.reply_text("Пользователь не найден.", reply_markup=back_kb)
        context.user_data["state"] = back_state
        return
    if is_admin(target):
        await update.message.reply_text("Нельзя забанить администратора.", reply_markup=back_kb)
        context.user_data["state"] = back_state
        return
    new_val = 0 if u["is_banned"] else 1
    conn.execute("UPDATE users SET is_banned=? WHERE tg_id=?", (new_val, target))
    conn.commit()
    if new_val:
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (target,))
        conn.commit()
        try:
            await context.bot.send_message(target, "🚫 Вы заблокированы в боте.")
        except TelegramError:
            pass
        await update.message.reply_text(f"🔨 Пользователь {target} забанен.", reply_markup=back_kb)
    else:
        try:
            await context.bot.send_message(target, "✅ Вы разблокированы.", reply_markup=main_menu_kb(target))
        except TelegramError:
            pass
        await update.message.reply_text(f"♻️ Пользователь {target} разбанен.", reply_markup=back_kb)
    context.user_data["state"] = back_state


async def moder_panel_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if text == "🚩 Жалобы":
        await show_pending_reports(update, context)
        return
    if text == "🔨 Бан / Разбан":
        await start_ban(update, context, "moder")
        return
    if text == "📊 Статистика":
        await adm_stats_msg(update, context)
        return
    if text == "📤 Выгрузить пользователей":
        await adm_export_msg(update, context)
        return
    if text == "📢 Обязательные каналы":
        await adm_channels_msg(update, context)
        return
    if text == "ℹ️ Помощь":
        await update.message.reply_text(t("moder_help"), parse_mode="HTML", reply_markup=moder_menu_kb())
        return
    await update.message.reply_text("Выберите действие 👇", reply_markup=moder_menu_kb())


async def show_pending_reports(update, context):
    reports = conn.execute("SELECT * FROM reports WHERE status='pending' ORDER BY id DESC LIMIT 20").fetchall()
    back_kb = admin_menu_kb() if is_admin(update.effective_user.id) else moder_menu_kb()
    if not reports:
        await update.message.reply_text("Нет необработанных жалоб ✅", reply_markup=back_kb)
        return
    await update.message.reply_text(f"🚩 Необработанных жалоб: {len(reports)}", reply_markup=back_kb)
    for r in reports:
        if r["context"] == "anon":
            msg = conn.execute("SELECT * FROM anon_messages WHERE id=?", (r["ref_id"],)).fetchone()
            preview = (msg["text"] if msg and msg["content_type"] == "text" else "[голосовое]") if msg else "—"
            body = f"🚩 Жалоба #{r['id']} (анон)\nПричина: {r['reason']}\nСодержание: {preview}"
        else:
            body = f"🚩 Жалоба #{r['id']} (рулетка)\nПричина: {r['reason']}"
        ban_label = "🔨 Бан навсегда" if r["context"] == "anon" else "🔨 Бан 30 дн."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(ban_label, callback_data=f"repadm:ok:{r['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"repadm:no:{r['id']}"),
        ]])
        await context.bot.send_message(update.effective_chat.id, body, reply_markup=kb)


async def notify_staff(context, text, reply_markup=None, parse_mode=None):
    """Уведомление всем админам и модерам (включая временных)."""
    targets = set(ADMIN_IDS)
    for r in conn.execute(
        "SELECT tg_id FROM users WHERE is_moder=1 OR (moder_until IS NOT NULL AND moder_until>?)",
        (now_iso(),),
    ).fetchall():
        targets.add(r["tg_id"])
    for tid in targets:
        try:
            await context.bot.send_message(tid, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramError:
            pass


# ── Админ-действия через reply-клавиатуру ──

async def adm_stats_msg(update, context):
    users_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    msgs_count = conn.execute("SELECT COUNT(*) c FROM anon_messages").fetchone()["c"]
    sessions_count = conn.execute("SELECT COUNT(*) c FROM roulette_sessions").fetchone()["c"]
    sessions_18 = conn.execute("SELECT COUNT(*) c FROM roulette_sessions WHERE mode='18plus'").fetchone()["c"]
    vip_count = conn.execute("SELECT COUNT(*) c FROM users WHERE vip_until>?", (now_iso(),)).fetchone()["c"]
    moders_count = conn.execute("SELECT COUNT(*) c FROM users WHERE is_moder=1").fetchone()["c"]
    # Ссылки: анонимные (созданные пользователями) и реферальные (по факту переходов)
    anon_links = conn.execute("SELECT COUNT(*) c FROM users WHERE custom_link IS NOT NULL AND custom_link<>''").fetchone()["c"]
    ref_links = conn.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    # Совершеннолетние — считаем в Python (age хранится текстом; портативно для sqlite/Postgres)
    adults = 0
    for r in conn.execute("SELECT age FROM users WHERE age IS NOT NULL").fetchall():
        a = str(r["age"]).strip()
        if a.isdigit() and int(a) >= 18:
            adults += 1
    kb = admin_menu_kb() if is_admin(update.effective_user.id) else moder_menu_kb()
    await update.message.reply_text(
        "📊 <b>Статистика бота</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"🔞 Совершеннолетних (18+): <b>{adults}</b>\n"
        f"👑 VIP сейчас: <b>{vip_count}</b>\n"
        f"🛡 Модераторов: <b>{moders_count}</b>\n"
        "─────────────\n"
        f"🔗 Анон-ссылок создано: <b>{anon_links}</b>\n"
        f"👥 Реф-ссылок (приглашений): <b>{ref_links}</b>\n"
        "─────────────\n"
        f"✉️ Анон-сообщений: <b>{msgs_count}</b>\n"
        f"🎲 Сессий рулетки: <b>{sessions_count}</b>\n"
        f"🔞 Из них 18+: <b>{sessions_18}</b>"
        "</blockquote>",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def admin_vip_router(update, context):
    """Админ: выдать/забрать VIP по ID пользователя."""
    text = canon(update.message.text.strip())
    state = context.user_data.get("state")
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if text in ("⬅️ Назад", "🏠 Меню"):
        context.user_data["state"] = None
        if text == "🏠 Меню":
            await go_home(update, context)
        else:
            await show_admin_menu(update, context)
        return
    if state == "admin_vip":
        if text == "➕ Выдать VIP":
            context.user_data["state"] = "vip_give_id"
            await update.message.reply_text(t("vip_ask_id"), parse_mode="HTML", reply_markup=cancel_reply_kb())
            return
        if text == "➖ Забрать VIP":
            context.user_data["state"] = "vip_take_id"
            await update.message.reply_text(t("vip_ask_id"), parse_mode="HTML", reply_markup=cancel_reply_kb())
            return
        await update.message.reply_text(t("choose_on_kb"), reply_markup=admin_vip_kb())
        return
    if text == "❌ Отмена":
        context.user_data["state"] = "admin_vip"
        await update.message.reply_text(t("done"), reply_markup=admin_vip_kb())
        return
    if state in ("vip_give_id", "vip_take_id"):
        target = resolve_user_ref(text)
        if target is None:
            await update.message.reply_text(t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        if state == "vip_take_id":
            conn.execute("UPDATE users SET vip_until=NULL WHERE tg_id=?", (target,))
            conn.commit()
            try:
                _sl = cur_lang(); set_cur_lang(get_lang(target))
                await context.bot.send_message(target, t("vip_taken_user"), parse_mode="HTML")
                set_cur_lang(_sl)
            except TelegramError:
                pass
            context.user_data["state"] = "admin_vip"
            await update.message.reply_text(t("vip_taken_admin", id=target), parse_mode="HTML", reply_markup=admin_vip_kb())
            return
        # выдать — спрашиваем дни
        context.user_data["vip_target"] = target
        context.user_data["state"] = "vip_give_days"
        await update.message.reply_text(t("vip_ask_days"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    if state == "vip_give_days":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text(t("vip_days_number"), reply_markup=cancel_reply_kb())
            return
        days = int(text)
        target = context.user_data.get("vip_target")
        tu = get_user(target)
        base = now_dt()
        try:
            if tu and tu["vip_until"] and datetime.fromisoformat(tu["vip_until"]) > now_dt():
                base = datetime.fromisoformat(tu["vip_until"])
        except (ValueError, TypeError):
            base = now_dt()
        new_until = (base + timedelta(days=days)).isoformat()
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (new_until, target))
        conn.commit()
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("vip_granted_user", days=days), parse_mode="HTML")
            set_cur_lang(_sl)
        except TelegramError:
            pass
        context.user_data["state"] = "admin_vip"
        context.user_data.pop("vip_target", None)
        await update.message.reply_text(t("vip_granted_admin", id=target, days=days), parse_mode="HTML", reply_markup=admin_vip_kb())
        return


async def janitor_unreachable_sweep():
    """Фоновая автоочистка: находит тех, кто заблокировал бота или не запускал его,
    и удаляет «пустые» аккаунты (без VIP/коинов/покупок). Проверяет через chat_action — без спама."""
    rows = conn.execute("SELECT tg_id FROM users").fetchall()
    checked = removed = 0
    for r in rows:
        tid = r["tg_id"]
        if is_admin(tid):
            continue
        u = get_user(tid)
        if not u or is_moder(u):
            continue
        checked += 1
        try:
            # «typing» не виден пользователю, но падает с Forbidden, если бот недоступен
            await bot.send_chat_action(tid, "typing")
        except TelegramForbiddenError:
            # Заблокировал/не запускал бота — удаляем, только если аккаунт «пустой» (ничего не вкладывал)
            if user_is_disposable(tid) and purge_user(tid):
                removed += 1
        except TelegramError:
            pass  # флуд/сеть — пропускаем
        await asyncio.sleep(0.05)  # мягкий троттлинг, чтобы не словить лимиты Telegram
    if removed:
        log.info("janitor: автоочистка недоступных — проверено=%d, удалено=%d", checked, removed)
    return checked, removed


async def adm_export_msg(update, context):
    rows = conn.execute("SELECT tg_id, username, gender FROM users").fetchall()
    path = os.path.join(os.path.dirname(__file__), "users_export.txt")
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"id={r['tg_id']} | username=@{r['username']} | gender={r['gender']}\n")
    with open(path, "rb") as f:
        await context.bot.send_document(update.effective_user.id, document=f)


async def adm_channels_msg(update, context):
    channels = await get_mandatory_channels()
    if channels:
        lst = "\n".join(f"{i+1}. {channel_title(c)} → {c['chat_username']}" for i, c in enumerate(channels))
    else:
        lst = "(пусто)"
    context.user_data["state"] = "adm_channels_menu"
    await update.message.reply_text(
        f"📢 <b>Обязательные каналы</b> ({len(channels)}/10)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>{lst}</blockquote>\n"
        "Это каналы/чаты/боты, на которые нужно подписаться, чтобы <b>удалить сообщение</b>.\n"
        "Выбери действие 👇",
        parse_mode="HTML",
        reply_markup=adm_channels_kb(update.effective_user.id),
    )


def adm_channels_kb(uid=None):
    rows = [
        [KeyboardButton("➕ Добавить канал")],
        [KeyboardButton("🗑 Удалить канал")],
    ]
    # Переключатель «Подписка для входа» — только у админа
    if uid is not None and is_admin(uid):
        enabled = get_setting("subgate_enabled", "0") == "1"
        toggle = "🔒 Подписка для входа: ВКЛ" if enabled else "🔓 Подписка для входа: ВЫКЛ"
        rows.append([KeyboardButton(toggle)])
    rows.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def adm_channels_router(update, context):
    """Управление обязательными каналами: меню → название → ссылка → предпросмотр → сохранить."""
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    ctext = canon(text)
    uid = update.effective_user.id
    if not is_staff(uid):
        context.user_data["state"] = None
        return
    # Общие выходы
    if ctext in ("⬅️ Назад", "🏠 Меню") and state in ("adm_channels_menu",):
        context.user_data["state"] = None
        if ctext == "🏠 Меню":
            await go_home(update, context)
        elif is_admin(uid):
            await show_admin_menu(update, context)
        else:
            await show_moder_menu(update, context)
        return
    if ctext == "❌ Отмена":
        context.user_data.pop("new_channel", None)
        await adm_channels_msg(update, context)
        return

    if state == "adm_channels_menu":
        if (ctext.startswith("🔒 Подписка для входа") or ctext.startswith("🔓 Подписка для входа") or "Подписка для входа" in ctext):
            if not is_admin(uid):
                await update.message.reply_text("Эта настройка доступна только администратору.", reply_markup=adm_channels_kb(uid))
                return
            cur = get_setting("subgate_enabled", "0") == "1"
            set_setting("subgate_enabled", "0" if cur else "1")
            await update.message.reply_text(
                "🔓 Подписка для входа ВЫКЛЮЧЕНА. Подписка нужна только для удаления сообщений."
                if cur else
                "🔒 Подписка для входа ВКЛЮЧЕНА. Теперь, чтобы пользоваться ботом, нужно подписаться на каналы.",
                reply_markup=adm_channels_kb(uid))
            return
        if ctext == "➕ Добавить канал":
            cnt = conn.execute("SELECT COUNT(*) c FROM mandatory_channels").fetchone()["c"]
            if cnt >= 10:
                await update.message.reply_text("Достигнут максимум — 10 каналов. Удали лишний, чтобы добавить новый.", reply_markup=adm_channels_kb(uid))
                return
            context.user_data["new_channel"] = {}
            context.user_data["state"] = "adm_ch_name"
            await update.message.reply_text(
                "📝 Введите <b>название кнопки</b> (как она будет видна пользователю, например: «Наш канал 📢»):",
                parse_mode="HTML", reply_markup=cancel_reply_kb())
            return
        if ctext == "🗑 Удалить канал":
            channels = await get_mandatory_channels()
            if not channels:
                await update.message.reply_text("Каналов нет.", reply_markup=adm_channels_kb(uid))
                return
            rows = [[KeyboardButton(f"{i+1}. {channel_title(c)}")] for i, c in enumerate(channels)]
            rows.append([KeyboardButton("⬅️ Назад")])
            context.user_data["del_map"] = {f"{i+1}. {channel_title(c)}": c["id"] for i, c in enumerate(channels)}
            context.user_data["state"] = "adm_ch_delete"
            await update.message.reply_text("Выбери канал для удаления 👇", reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)))
            return
        await update.message.reply_text("Выбери действие 👇", reply_markup=adm_channels_kb(uid))
        return

    if state == "adm_ch_name":
        context.user_data["new_channel"]["title"] = text
        context.user_data["state"] = "adm_ch_link"
        await update.message.reply_text(
            "🔗 Теперь вставь <b>@канал</b>, чат, бота или ссылку (https://t.me/...):",
            parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    if state == "adm_ch_link":
        context.user_data["new_channel"]["link"] = text
        title = context.user_data["new_channel"]["title"]
        # Предпросмотр — как будет выглядеть кнопка
        preview_kb = InlineKeyboardMarkup([[InlineKeyboardButton(title, url=channel_url(text))]])
        context.user_data["state"] = "adm_ch_confirm"
        await update.message.reply_text(
            "👀 <b>Предпросмотр кнопки:</b>\n"
            f"Название: <b>{html.escape(title)}</b>\n"
            f"Ссылка: {html.escape(channel_url(text))}\n\n"
            "Так будет выглядеть кнопка 👇\nВсё верно?",
            parse_mode="HTML", reply_markup=preview_kb)
        await update.message.reply_text(
            "Сохранить?",
            reply_markup=tr_kb(ReplyKeyboardMarkup([[KeyboardButton("✅ Сохранить")], [KeyboardButton("❌ Отмена")]], resize_keyboard=True)))
        return

    if state == "adm_ch_confirm":
        if ctext == "✅ Сохранить" or canon(text) == "✅ Да":
            nc = context.user_data.get("new_channel", {})
            conn.execute("INSERT INTO mandatory_channels (chat_username, title) VALUES (?, ?)",
                         (nc.get("link", ""), nc.get("title")))
            conn.commit()
            context.user_data.pop("new_channel", None)
            await update.message.reply_text("✅ Канал добавлен!", reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb())
            await adm_channels_msg(update, context)
            return
        await update.message.reply_text("Нажми «✅ Сохранить» или «❌ Отмена».")
        return

    if state == "adm_ch_delete":
        if ctext == "⬅️ Назад":
            await adm_channels_msg(update, context)
            return
        cid = context.user_data.get("del_map", {}).get(text)
        if cid is None:
            await update.message.reply_text("Выбери канал на клавиатуре 👇")
            return
        conn.execute("DELETE FROM mandatory_channels WHERE id=?", (cid,))
        conn.commit()
        context.user_data.pop("del_map", None)
        await update.message.reply_text("🗑 Канал удалён.", reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb())
        await adm_channels_msg(update, context)
        return


async def process_bcast_audience_text(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "❌ Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb())
        return
    mp = {"👥 Всем": "all", "👨 Мужчинам": "m", "👩 Женщинам": "f"}
    aud = mp.get(text)
    if not aud:
        await update.message.reply_text("Выбери вариант:", reply_markup=bcast_audience_kb())
        return
    context.user_data["bcast_aud"] = aud
    context.user_data["state"] = "adm_bcast_content"
    await update.message.reply_text(
        "Отправь сообщение для рассылки (текст/фото/голосовое):",
        reply_markup=cancel_reply_kb(),
    )



async def process_adm_coins_wizard(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=admin_menu_kb())
        return
    if state == "adm_coins_id":
        target = resolve_user_ref(update.message.text.strip())
        if target is None:
            await update.message.reply_text("Пользователь не найден. Введите ID или @username:", reply_markup=cancel_reply_kb())
            return
        context.user_data["coins_target"] = target
        context.user_data["state"] = "adm_coins_amount"
        await update.message.reply_text("На сколько изменить баланс (можно отрицательное число)?", reply_markup=cancel_reply_kb())
    elif state == "adm_coins_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("Введи целое число:")
            return
        target = context.user_data["coins_target"]
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amount, target))
        conn.commit()
        context.user_data["state"] = None
        await update.message.reply_text(f"Баланс пользователя {target} изменён на {amount} 💎", reply_markup=admin_menu_kb())
        try:
            await context.bot.send_message(target, f"Твой баланс коинов изменён на {amount} 💎")
        except TelegramError:
            pass



async def process_adm_ad_wizard(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    ad = context.user_data["ad"]
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=admin_menu_kb())
        return
    if state == "adm_ad_text":
        ad["text"] = text
        context.user_data["state"] = "adm_ad_button_text"
        await update.message.reply_text("Текст кнопки (или «-» если без кнопки):", reply_markup=cancel_reply_kb())

    elif state == "adm_ad_button_text":
        ad["button_text"] = None if text == "-" else text
        if ad["button_text"]:
            context.user_data["state"] = "adm_ad_button_url"
            await update.message.reply_text("Ссылка для кнопки:", reply_markup=cancel_reply_kb())
        else:
            await ad_preview_and_offer(update, context)
    elif state == "adm_ad_button_url":
        ad["button_url"] = text
        await ad_preview_and_offer(update, context)


def ad_markup(ad):
    if ad.get("button_text") and ad.get("button_url"):
        return InlineKeyboardMarkup([[InlineKeyboardButton(ad["button_text"], url=ad["button_url"])]])
    return None


async def ad_preview_and_offer(update, context):
    ad = context.user_data["ad"]
    save_ad(ad)
    context.user_data["state"] = "adm_ad_send"
    await update.message.reply_text("👀 Так реклама будет выглядеть у пользователей:")
    await update.message.reply_text(ad["text"], reply_markup=ad_markup(ad))
    await update.message.reply_text(
        "Разослать рекламу всем пользователям?",
        reply_markup=tr_kb(ReplyKeyboardMarkup(
            [[KeyboardButton("📤 Отправить всем")], [KeyboardButton("❌ Отмена")]],
            resize_keyboard=True,
        )),
    )


async def process_ad_send(update, context):
    text = canon(update.message.text)
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Реклама сохранена, рассылка отменена.", reply_markup=admin_menu_kb())
        return
    if text != "📤 Отправить всем":
        await update.message.reply_text("Выберите действие на клавиатуре 👇")
        return
    ad = conn.execute("SELECT * FROM ad_config WHERE id=1").fetchone()
    markup = None
    if ad and ad["button_text"] and ad["button_url"]:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(ad["button_text"], url=ad["button_url"])]])
    rows = conn.execute("SELECT tg_id FROM users").fetchall()
    sent, failed = 0, 0
    for r in rows:
        try:
            await context.bot.send_message(r["tg_id"], ad["text"], reply_markup=markup)
            sent += 1
        except TelegramError:
            failed += 1
    context.user_data["state"] = None
    await update.message.reply_text(
        f"📣 Реклама разослана. Доставлено: {sent}, не удалось: {failed}",
        reply_markup=admin_menu_kb(),
    )


def save_ad(ad):
    conn.execute(
        "INSERT INTO ad_config (id, text, button_text, button_url) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET text=excluded.text, button_text=excluded.button_text, button_url=excluded.button_url",
        (ad.get("text"), ad.get("button_text"), ad.get("button_url")),
    )
    conn.commit()


def user_is_disposable(uid):
    """True, если аккаунт «пустой» и его можно безопасно удалить:
    не админ/модер, без VIP, без коинов и без покупок за Stars."""
    if is_admin(uid):
        return False
    u = get_user(uid)
    if not u or is_moder(u):
        return False
    if is_vip(u):
        return False
    try:
        if (u["coins"] or 0) > 0:
            return False
    except (KeyError, IndexError, TypeError):
        pass
    has_stars = conn.execute("SELECT 1 FROM star_purchases WHERE user_id=? LIMIT 1", (uid,)).fetchone()
    if has_stars:
        return False
    return True


def purge_user(uid):
    try:
        if is_admin(uid):
            return False
        u = get_user(uid)
        if u and is_moder(u):
            return False
        conn.execute("DELETE FROM users WHERE tg_id=?", (uid,))
        conn.execute("DELETE FROM referrals WHERE referred_id=? OR referrer_id=?", (uid, uid))
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.commit()
        return True
    except Exception as e:  # noqa
        log.warning("purge_user %s: %s", uid, e)
        return False


async def process_bcast_content(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    if canon(update.message.text) == "❌ Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return
    aud = context.user_data["bcast_aud"]
    if aud == "all":
        rows = conn.execute("SELECT tg_id FROM users").fetchall()
    else:
        rows = conn.execute("SELECT tg_id FROM users WHERE gender=?", (aud,)).fetchall()
    sent, failed = 0, 0
    blocked_ids = []
    prefix_text = "Админ:\n\n"
    for r in rows:
        try:
            if update.message.text:
                await context.bot.send_message(r["tg_id"], prefix_text + update.message.text)
            elif update.message.photo:
                caption = (prefix_text + update.message.caption) if update.message.caption else prefix_text
                await context.bot.send_photo(r["tg_id"], update.message.photo[-1].file_id, caption=caption)
            elif update.message.voice:
                await context.bot.send_message(r["tg_id"], prefix_text)
                await context.bot.send_voice(r["tg_id"], update.message.voice.file_id)
            sent += 1
        except TelegramForbiddenError:
            # Пользователь заблокировал бота или не запускал его — кандидат на удаление
            failed += 1
            blocked_ids.append(r["tg_id"])
        except TelegramError:
            failed += 1
    # Чистим тех, кто заблокировал/удалил бота (мёртвые аккаунты из старой БД)
    removed = 0
    for bid in blocked_ids:
        if purge_user(bid):
            removed += 1
    context.user_data["state"] = "admin" if is_admin(uid) else "moder"
    await update.message.reply_text(
        f"📢 Рассылка завершена.\n"
        f"✅ Доставлено: {sent}\n"
        f"❌ Не удалось: {failed}\n"
        f"🧹 Удалено недоступных (заблокировали/не запускали бота): {removed}",
        reply_markup=back_kb,
    )



async def show_star_shop(update, context):
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    uid = update.effective_user.id
    if not pkgs:
        await nav(update, context, t("stars_unavailable"), main_menu_kb(uid))
        return
    smap, rows = {}, []
    for p in pkgs:
        label = f"{item_title(p)} — ⭐{p['price_stars']}"
        smap[label] = p["id"]
        rows.append([KeyboardButton(label)])
    rows.append([KeyboardButton("⬅️ Назад")])
    context.user_data["star_map"] = smap
    context.user_data["state"] = "star_shop"
    await nav(update, context, t("stars_title"),
              tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)), parse_mode="HTML")


async def star_shop_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    pid = context.user_data.get("star_map", {}).get(text)
    if pid is None:
        await update.message.reply_text(t("stars_pick_pkg"))
        return
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=? AND active=1", (pid,)).fetchone()
    if not pkg:
        await nav(update, context, t("pkg_unavailable"), main_menu_kb(uid))
        return
    context.user_data["star_pending"] = pid
    context.user_data["state"] = "star_confirm"
    await nav(
        update, context,
        t("stars_buy_confirm", title=html.escape(item_title(pkg)), coins=pkg['coins'], stars=pkg['price_stars']),
        yes_no_kb(), parse_mode="HTML",
    )


async def star_confirm_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "❌ Отмена":
        await show_star_shop(update, context)
        return
    if text != "✅ Да":
        await update.message.reply_text(t("choose_on_kb"), reply_markup=yes_no_kb())
        return
    pid = context.user_data.get("star_pending")
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=? AND active=1", (pid,)).fetchone()
    if not pkg:
        await nav(update, context, t("pkg_unavailable"), main_menu_kb(uid))
        return
    context.user_data["state"] = None
    await context.bot.send_message(
        uid, t("stars_invoice_sent"),
        reply_markup=main_menu_kb(uid),
    )
    await context.bot.send_invoice(
        chat_id=uid,
        title=item_title(pkg),
        description=t("stars_pkg_desc", coins=pkg['coins']),
        payload=f"coins:{pkg['id']}",
        provider_token="",       # пусто = Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(item_title(pkg), pkg["price_stars"])],
    )


async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


# Кнопка «Узнать кто» — спрашивает подтверждение перед оплатой
def reveal_sender_text(row):
    """Формирует текст с данными отправителя анонимного сообщения."""
    sender = get_user(row["from_id"])
    if not sender:
        return None
    name = sender["first_name"] or "—"
    uname = f"@{sender['username']}" if sender["username"] else f"<a href='tg://user?id={sender['tg_id']}'>{t('reveal_profile_link')}</a>"
    return t("reveal_result", name=html.escape(name), uname=uname, tid=sender["tg_id"])


async def on_reveal_button(update, context):
    query = update.callback_query
    await query.answer()
    mid = int(query.data.split(":")[1])
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (mid,)).fetchone()
    if not row:
        await query.answer(t("anon_not_found"), show_alert=True)
        return
    if query.from_user.id != row["to_id"]:
        await query.answer(t("reveal_only_recipient"), show_alert=True)
        return
    # Админ/модер раскрывают бесплатно и сразу, без оплаты
    if is_unlimited(get_user(query.from_user.id)):
        await context.bot.send_message(
            query.from_user.id,
            reveal_sender_text(row) or t("anon_not_found"),
            parse_mode="HTML",
        )
        return
    # Подтверждение покупки
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_reveal_yes"), callback_data=f"reveal_pay:{mid}")],
        [InlineKeyboardButton(t("btn_cancel_accent"), callback_data="reveal_cancel")],
    ])
    await context.bot.send_message(
        query.from_user.id,
        t("reveal_confirm"),
        parse_mode="HTML",
        reply_markup=kb,
    )


# Подтверждение — отправляем инвойс
async def on_reveal_pay(update, context):
    query = update.callback_query
    await query.answer()
    mid = int(query.data.split(":")[1])
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (mid,)).fetchone()
    if not row:
        await query.edit_message_text(t("anon_not_found"))
        return
    # Убираем кнопки подтверждения
    await query.edit_message_text(t("reveal_paying"))
    # Отправляем инвойс на 1 Star
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=t("reveal_title"),
        description=t("reveal_desc"),
        payload=f"reveal:{mid}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="⭐", amount=1)],
    )


# Отмена раскрытия
async def on_reveal_cancel(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("cancelled"))


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    uid = update.effective_user.id
    payload = sp.invoice_payload or ""

    # Оплата раскрытия отправителя
    if payload.startswith("reveal:"):
        mid = int(payload.split(":")[1])
        row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (mid,)).fetchone()
        if not row:
            await update.message.reply_text(t("msg_not_found"))
            return
        txt = reveal_sender_text(row)
        await update.message.reply_text(txt or t("anon_not_found"), parse_mode="HTML")
        return

    # Оплата покупки коинов за Stars
    if not payload.startswith("coins:"):
        return
    pid = int(payload.split(":")[1])
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=?", (pid,)).fetchone()
    coins = pkg["coins"] if pkg else 0
    conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (coins, uid))
    conn.execute(
        "INSERT INTO star_purchases (user_id, package_id, coins, stars, charge_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, pid, coins, sp.total_amount, sp.telegram_payment_charge_id, now_iso()),
    )
    conn.commit()
    await update.message.reply_text(
        t("stars_paid", coins=coins),
        parse_mode="HTML", reply_markup=main_menu_kb(uid),
    )
    user = get_user(uid)
    await notify_staff(
        context,
        f"⭐ Покупка коинов!\n{user_mention(user)}\n"
        f"Пакет: {html.escape(pkg['title']) if pkg else '-'}\nКоинов: {coins} / Звёзд: {sp.total_amount}",
        parse_mode="HTML",
    )


# ── Админ: управление пакетами коинов за Stars ──

async def show_star_admin(update, context):
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    lst = "\n".join(f"• {p['title']} — {p['coins']} 💎 за ⭐{p['price_stars']}" for p in pkgs) or "(пакетов нет)"
    context.user_data["state"] = "star_admin"
    await update.message.reply_text(f"⭐ Пакеты коинов за Stars:\n{lst}", reply_markup=star_admin_kb())


async def star_admin_router(update, context):
    text = canon(update.message.text)
    if text == "⬅️ Назад":
        await show_admin_menu(update, context)
        return
    if text == "➕ Добавить пакет коинов":
        context.user_data["state"] = "star_add_title"
        context.user_data["new_star"] = {}
        await update.message.reply_text("Название пакета (напр. «100 коинов»):", reply_markup=cancel_reply_kb())
        return
    if text == "🗑 Удалить пакет коинов":
        pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
        if not pkgs:
            await update.message.reply_text("Пакетов нет.", reply_markup=star_admin_kb())
            return
        smap, rows = {}, []
        for p in pkgs:
            label = f"{p['title']} — ⭐{p['price_stars']}"
            smap[label] = p["id"]
            rows.append([KeyboardButton(label)])
        rows.append([KeyboardButton("❌ Отмена")])
        context.user_data["star_del_map"] = smap
        context.user_data["state"] = "star_del"
        await update.message.reply_text("Какой пакет удалить?", reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)))
        return
    await update.message.reply_text("Выбери действие 👇", reply_markup=star_admin_kb())


async def process_star_wizard(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text.strip())
    if text == "❌ Отмена":
        context.user_data["state"] = "star_admin"
        await update.message.reply_text("Отменено.", reply_markup=star_admin_kb())
        return
    if state == "star_del":
        pid = context.user_data.get("star_del_map", {}).get(text)
        if pid is None:
            await update.message.reply_text("Выбери пакет на клавиатуре.")
            return
        conn.execute("UPDATE star_packages SET active=0 WHERE id=?", (pid,))
        conn.commit()
        context.user_data["state"] = "star_admin"
        await update.message.reply_text("🗑 Пакет удалён.", reply_markup=star_admin_kb())
        return
    item = context.user_data.setdefault("new_star", {})
    if state == "star_add_title":
        item["title"] = text
        context.user_data["state"] = "star_add_coins"
        await update.message.reply_text("Сколько коинов даёт пакет? (число):", reply_markup=cancel_reply_kb())
    elif state == "star_add_coins":
        if not text.isdigit():
            await update.message.reply_text("Введи число:")
            return
        item["coins"] = int(text)
        context.user_data["state"] = "star_add_price"
        await update.message.reply_text("Цена в звёздах ⭐ (число):", reply_markup=cancel_reply_kb())
    elif state == "star_add_price":
        if not text.isdigit():
            await update.message.reply_text("Введи число:")
            return
        await update.message.reply_text("⏳ Перевожу название на 3 языка…")
        ru, uz, en = await translate_to_all(item["title"])
        conn.execute(
            "INSERT INTO star_packages (title, title_uz, title_en, coins, price_stars) VALUES (?, ?, ?, ?, ?)",
            (ru, uz, en, item["coins"], int(text)),
        )
        conn.commit()
        context.user_data["state"] = "star_admin"
        await update.message.reply_text(
            f"✅ Пакет добавлен!\n🇷🇺 {ru}\n🇺🇿 {uz}\n🇬🇧 {en}\n"
            "Теперь у пользователей появилась кнопка «💎 Купить коины».",
            reply_markup=star_admin_kb(),
        )


async def handle_referral(update, context, code, existed):
    """Начисляет коины пригласившему за нового пользователя."""
    if existed:
        return  # пользователь уже был — не считается за приглашение
    try:
        inviter_id = int(code[4:])
    except ValueError:
        return
    uid = update.effective_user.id
    if inviter_id == uid:
        return
    inviter = get_user(inviter_id)
    if not inviter:
        return
    if conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (uid,)).fetchone():
        return
    reward = REF_REWARD_VIP if is_vip(inviter) else REF_REWARD_NORMAL
    conn.execute(
        "INSERT INTO referrals (referrer_id, referred_id, coins_awarded, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (inviter_id, uid, reward, now_iso()),
    )
    conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (reward, inviter_id))
    conn.commit()
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(inviter_id))
        await context.bot.send_message(
            inviter_id,
            t("ref_friend_joined", reward=reward),
            parse_mode="HTML",
        )
        set_cur_lang(_sl)
    except TelegramError:
        pass


def qualified_referrals(uid):
    """Кол-во приглашённых, которые СОЗДАЛИ свою ссылку (нажали /start и создали ссылку)."""
    return conn.execute(
        "SELECT COUNT(*) c FROM referrals r JOIN users u ON u.tg_id=r.referred_id "
        "WHERE r.referrer_id=? AND r.active=1 AND u.custom_link IS NOT NULL",
        (uid,),
    ).fetchone()["c"]


async def reward_link_activity(context, uid, kind):
    """Бонус за активность по ссылке: +LINK_REWARD_COINS за каждые LINK_REWARD_EVERY действий.
    kind: 'sent' (отправил по ссылке) или 'answered' (ответил). VIP и персонал — без бонуса."""
    u = get_user(uid)
    if not u or is_vip(u):   # is_vip True и для админа/модера → бонус им не идёт
        return
    if kind == "sent":
        col_total, col_paid = "link_sent_total", "link_sent_rewarded"
    else:
        col_total, col_paid = "link_answered_total", "link_answered_rewarded"
    total = (u[col_total] or 0) + 1
    paid = u[col_paid] or 0
    milestones = total // LINK_REWARD_EVERY
    if milestones > paid:
        reward = (milestones - paid) * LINK_REWARD_COINS
        conn.execute(
            f"UPDATE users SET {col_total}=?, {col_paid}=?, coins = coins + ? WHERE tg_id=?",
            (total, milestones, reward, uid),
        )
        conn.commit()
        try:
            _sl = cur_lang(); set_cur_lang(get_lang(uid))
            await context.bot.send_message(uid, t("link_reward", coins=reward, n=total), parse_mode="HTML")
            set_cur_lang(_sl)
        except TelegramError:
            pass
    else:
        conn.execute(f"UPDATE users SET {col_total}=? WHERE tg_id=?", (total, uid))
        conn.commit()


def ref_rewards_kb(uid, link=None):
    """Инлайн-кнопки наград за рефералов с прогрессом (+ «Поделиться» если передана ссылка)."""
    qual = qualified_referrals(uid)
    rows = []
    if link:
        full = link if link.startswith("http") else ("https://" + link)
        share_url = ("https://t.me/share/url?url=" + urllib.parse.quote(full, safe="")
                     + "&text=" + urllib.parse.quote(t("ref_share_text"), safe=""))
        rows.append([InlineKeyboardButton(t("btn_share_ref"), url=share_url)])
    rows += [
        [InlineKeyboardButton(t("ref_claim_coins_btn", n=REF_REWARD_NORMAL, v=REF_REWARD_VIP), callback_data="ref_info")],
        [InlineKeyboardButton(t("ref_claim_vip_btn", have=qual, need=cfg_vip_threshold()), callback_data="claim_vip")],
        [InlineKeyboardButton(t("ref_claim_moder_btn", have=qual, need=cfg_moder_threshold()), callback_data="claim_moder")],
    ]
    return InlineKeyboardMarkup(rows)


async def refresh_ref_rewards(update, context):
    """Перерисовывает инлайн-кнопки наград (после клейма прогресс меняется)."""
    query = update.callback_query
    try:
        link = await build_start_link(context, f"ref_{query.from_user.id}")
        await query.edit_message_reply_markup(reply_markup=ref_rewards_kb(query.from_user.id, link))
    except TelegramError:
        pass


async def on_claim_vip(update, context):
    """Забрать бесплатный VIP за приглашённых друзей (1 раз на каждые cfg_vip_threshold)."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    u = get_user(uid)
    qual = qualified_referrals(uid)
    threshold = cfg_vip_threshold()
    allowed = qual // threshold
    claimed = u["ref_vip_claims"] or 0
    if allowed <= claimed:
        need = (claimed + 1) * threshold - qual
        await query.answer(t("ref_need_more", n=need, have=qual, need=threshold), show_alert=True)
        return
    days = cfg_vip_days()
    base = max(now_dt(), datetime.fromisoformat(u["vip_until"])) if u["vip_until"] else now_dt()
    new_until = base + timedelta(days=days)
    conn.execute(
        "UPDATE users SET vip_until=?, ref_vip_claims=? WHERE tg_id=?",
        (new_until.isoformat(), claimed + 1, uid),
    )
    conn.commit()
    await context.bot.send_message(uid, t("ref_vip_granted", days=days), parse_mode="HTML")
    await refresh_ref_rewards(update, context)


async def on_claim_moder(update, context):
    """Забрать бесплатную модерку на неделю за REF_MODER_THRESHOLD приглашённых друзей."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    u = get_user(uid)
    qual = qualified_referrals(uid)
    threshold = cfg_moder_threshold()
    allowed = qual // threshold
    claimed = u["ref_moder_claims"] or 0
    if allowed <= claimed:
        need = (claimed + 1) * threshold - qual
        await query.answer(t("ref_need_more", n=need, have=qual, need=threshold), show_alert=True)
        return
    days = cfg_moder_days()
    base = now_dt()
    try:
        if u["moder_until"] and datetime.fromisoformat(u["moder_until"]) > base:
            base = datetime.fromisoformat(u["moder_until"])
    except (ValueError, TypeError):
        pass
    new_until = base + timedelta(days=days)
    conn.execute(
        "UPDATE users SET moder_until=?, ref_moder_claims=? WHERE tg_id=?",
        (new_until.isoformat(), claimed + 1, uid),
    )
    conn.commit()
    await context.bot.send_message(
        uid, t("ref_moder_granted", days=days, need=threshold),
        parse_mode="HTML", reply_markup=main_menu_kb(uid),
    )
    await refresh_ref_rewards(update, context)


async def on_ref_info(update, context):
    query = update.callback_query
    await query.answer(t("ref_info_alert", n=REF_REWARD_NORMAL, v=REF_REWARD_VIP), show_alert=True)


async def show_referral(update, context):
    uid = update.effective_user.id
    await clean_screen(update, context)
    link = await build_start_link(context, f"ref_{uid}")
    total = conn.execute("SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)).fetchone()["c"]
    earned = conn.execute("SELECT COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE referrer_id=? AND active=1", (uid,)).fetchone()["s"]
    vip = is_vip(get_user(uid))
    reward = REF_REWARD_VIP if vip else REF_REWARD_NORMAL
    bonus = t("referral_bonus_vip") if vip else t("referral_bonus_normal")
    caption = (
        t("referral_screen", reward=reward, bonus=bonus, total=total, earned=earned, link=html.escape(link))
        + "\n\n"
        + t("ref_rewards_title", vip_n=cfg_vip_threshold(), mod_n=cfg_moder_threshold(),
            vip_d=cfg_vip_days(), mod_d=cfg_moder_days())
    )
    context.user_data["state"] = "referral"
    photo = get_setting("ref_photo")
    kb = ref_rewards_kb(uid, link)
    if photo:
        try:
            msg = await context.bot.send_photo(
                update.effective_chat.id, photo, caption=caption,
                parse_mode="HTML", reply_markup=kb,
            )
        except TelegramError:
            msg = await context.bot.send_message(
                update.effective_chat.id, caption, parse_mode="HTML", reply_markup=kb)
    else:
        msg = await context.bot.send_message(
            update.effective_chat.id, caption, parse_mode="HTML", reply_markup=kb)
    track_extra(context, msg)
    # Нижняя reply-клавиатура (Топ / Изменить для админа / Назад)
    await send_menu(update, context, t("ref_menu_hint"), referral_kb(uid))


def referral_kb(uid=None):
    rows = [[KeyboardButton("🏆 Топ пригласивших")]]
    if uid is not None and is_admin(uid):
        rows.append([KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


# ── Админ: настройки реферальных наград ──
def ref_settings_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("⏳ VIP: дней"), KeyboardButton("👥 VIP: друзей")],
        [KeyboardButton("🛡 Модер: дней"), KeyboardButton("👥 Модер: друзей")],
        [KeyboardButton("📷 Фото"), KeyboardButton("🗑 Убрать фото")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True)


async def show_ref_settings(update, context):
    context.user_data["state"] = "ref_settings"
    photo_state = "есть ✅" if get_setting("ref_photo") else "нет"
    text = (
        "⚙️ <b>Настройки реферальных наград</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 VIP: <b>{cfg_vip_days()}</b> дн. за <b>{cfg_vip_threshold()}</b> друзей\n"
        f"🛡 Модер: <b>{cfg_moder_days()}</b> дн. за <b>{cfg_moder_threshold()}</b> друзей\n"
        f"📷 Фото на экране «Пригласить»: {photo_state}\n\n"
        "Выбери что изменить 👇"
    )
    await nav(update, context, text, ref_settings_kb(), parse_mode="HTML")


async def ref_settings_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if not is_admin(uid):
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    mp = {
        "⏳ VIP: дней": ("ref_set_vip_days", "Введите, на сколько ДНЕЙ давать VIP:"),
        "👥 VIP: друзей": ("ref_set_vip_threshold", "Введите, сколько ДРУЗЕЙ нужно для VIP:"),
        "🛡 Модер: дней": ("ref_set_moder_days", "Введите, на сколько ДНЕЙ давать модерку:"),
        "👥 Модер: друзей": ("ref_set_moder_threshold", "Введите, сколько ДРУЗЕЙ нужно для модерки:"),
    }
    if text == "⬅️ Назад":
        await show_referral(update, context)
        return
    if text == "📷 Фото":
        context.user_data["state"] = "ref_set_photo"
        await nav(update, context, "Отправьте фото для экрана «Пригласить» (или «❌ Отмена»):", cancel_reply_kb())
        return
    if text == "🗑 Убрать фото":
        set_setting("ref_photo", "")
        await update.message.reply_text("🗑 Фото убрано.")
        await show_ref_settings(update, context)
        return
    if text in mp:
        st, prompt = mp[text]
        context.user_data["state"] = st
        await nav(update, context, prompt, cancel_reply_kb())
        return
    await update.message.reply_text("Выбери пункт на клавиатуре 👇", reply_markup=ref_settings_kb())


async def process_ref_setting_value(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text.strip())
    if text == "❌ Отмена":
        await show_ref_settings(update, context)
        return
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("Введите положительное число:", reply_markup=cancel_reply_kb())
        return
    val = int(text)
    keymap = {
        "ref_set_vip_days": ("ref_vip_days", "VIP дней"),
        "ref_set_vip_threshold": ("ref_vip_threshold", "VIP друзей"),
        "ref_set_moder_days": ("ref_moder_days", "Модер дней"),
        "ref_set_moder_threshold": ("ref_moder_threshold", "Модер друзей"),
    }
    skey, label = keymap[state]
    set_setting(skey, val)
    await update.message.reply_text(f"✅ {label}: {val}")
    await show_ref_settings(update, context)


async def referral_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    if text == "🏆 Топ пригласивших":
        await show_top(update, context)
        return
    if text == "✏️ Изменить" and is_admin(uid):
        await show_ref_settings(update, context)
        return
    await update.message.reply_text(t("choose_action"), reply_markup=referral_kb(uid))


async def show_top(update, context):
    rows = conn.execute(
        "SELECT referrer_id, COUNT(*) c, COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE active=1 "
        "GROUP BY referrer_id ORDER BY c DESC, s DESC LIMIT 10"
    ).fetchall()
    if not rows:
        await nav(update, context, t("top_empty"), referral_kb(update.effective_user.id))
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [t("top_title"), "━━━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows):
        u = conn.execute("SELECT * FROM users WHERE tg_id=?", (r["referrer_id"],)).fetchone()
        name = u["first_name"] if (u and u["first_name"]) else f"ID {r['referrer_id']}"
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {html.escape(name)} — {r['c']} 👥 ({r['s']} 💎)")
    await nav(update, context, "\n".join(lines), referral_kb(), parse_mode="HTML")


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловим блокировку/разблокировку бота для списания/возврата реф-коинов."""
    cm = update.my_chat_member
    if not cm or cm.chat.type != "private":
        return
    new_status = cm.new_chat_member.status
    uid = cm.from_user.id
    if new_status in ("kicked", "banned"):
        ref = conn.execute("SELECT * FROM referrals WHERE referred_id=? AND active=1", (uid,)).fetchone()
        if ref:
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (ref["coins_awarded"], ref["referrer_id"]))
            conn.execute("UPDATE referrals SET active=0 WHERE id=?", (ref["id"],))
            conn.commit()
            try:
                _sl = cur_lang()
                set_cur_lang(get_lang(ref["referrer_id"]))
                await context.bot.send_message(
                    ref["referrer_id"],
                    t("ref_coins_refunded", n=ref['coins_awarded']),
                    parse_mode="HTML",
                )
                set_cur_lang(_sl)
            except TelegramError:
                pass
        # Авто-очистка: если заблокировавший — «пустой» аккаунт, сразу удаляем из базы
        if user_is_disposable(uid):
            if purge_user(uid):
                log.info("auto-purge: пользователь %s заблокировал бота и удалён (пустой аккаунт)", uid)
    elif new_status == "member":
        ref = conn.execute("SELECT * FROM referrals WHERE referred_id=? AND active=0", (uid,)).fetchone()
        if ref:
            conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (ref["coins_awarded"], ref["referrer_id"]))
            conn.execute("UPDATE referrals SET active=1 WHERE id=?", (ref["id"],))
            conn.commit()


async def show_help(update, context):
    uid = update.effective_user.id
    await nav(update, context, t("help"), main_menu_kb(uid), parse_mode="HTML")


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = canon(update.message.text) if update.message else None
    _u = get_user(update.effective_user.id)
    if _u and is_banned(_u) and not is_admin(update.effective_user.id):
        await update.message.reply_text(t("banned"))
        return
    # Восстановление незавершённого анона по ссылке после рестарта бота
    # (состояние в памяти UD теряется — поднимаем его из БД).
    if not state:
        _fl = load_link_flow(update.effective_user.id)
        if _fl:
            context.user_data["state"] = _fl["state"]
            context.user_data["anon_target"] = _fl["target_id"]
            if _fl["msg_type"]:
                context.user_data["anon_type"] = _fl["msg_type"]
            state = _fl["state"]
    # Навигация по главному меню доступна из ЛЮБОГО раздела и чистит прошлый экран.
    # Не перехватываем там, где пользователь вводит свободный текст/контент или сидит в чате.
    _NO_NAV = {
        "awaiting_anon_content", "awaiting_reply", "modmsg_text", "rchat", "tg_watch",
        "18plus_rchat",
        "shop_add_title", "shop_edit_name", "adm_ad_text", "adm_ad_button_text",
        "adm_ad_button_url", "adm_bcast_content",
        "adm_ch_name", "adm_ch_link",
    }
    _NAV = {
        "🔗 Моя ссылка": show_link_menu, "🎲 Чат-рулетка": show_roulette_entry,
        "👤 Профиль": show_profile, "🛒 Магазин": show_shop,
        "👥 Пригласить": show_referral, "ℹ️ Помощь": show_help,
        "🌐 Язык": show_language_menu, "💎 Купить коины": show_star_shop,
        "🔞 18+": eighteen_plus_menu,
        "🏠 Меню": go_home,
    }
    if (text in _NAV and state not in _NO_NAV
            and not (state and state.startswith("moder_q_"))
            and not (state == "moder" and text == "ℹ️ Помощь")):
        if text == "🛒 Магазин":
            context.user_data["state"] = None
        await _NAV[text](update, context)
        return
    if state == "rchat":
        if text == "➡️ Далее":
            await rchat_next(update, context)
            return
        if text == "⏹️ Стоп":
            await rchat_stop(update, context)
            return
        if await relay_roulette_message(update, context):
            return
        # сессия пропала — сброс в меню
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if state == "18plus_rchat":
        if text == "➡️ Далее":
            await rchat_next(update, context)
            return
        if text == "⏹️ Стоп":
            await rchat_stop(update, context)
            return
        if text == "⬅️ Назад" or text == "🏠 Меню":
            context.user_data["state"] = None
            await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
            return
        if await relay_roulette_message(update, context):
            return
        # сессия пропала — сброс в меню
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if state == "rleft":
        if text == "🔍 Новый поиск":
            await rleft_research(update, context)
            return
        if text == "🚩 Пожаловаться":
            await rleft_report(update, context)
            return
        if text == "⬅️ Назад":
            context.user_data["state"] = None
            await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
            return
        await update.message.reply_text(t("roulette_left"), reply_markup=left_chat_kb())
        return
    if state in ("set_gender_first", "set_gender_profile"):
        await set_gender_from_text(update, context)
        return
    if state in ("set_age_first", "set_age_profile"):
        await set_age_from_text(update, context)
        return
    if state == "awaiting_link_code":
        await process_link_code(update, context, text)
        return
    if state == "awaiting_anon_type":
        await on_anon_type_text(update, context)
        return
    if state == "awaiting_anon_content":
        await process_anon_content(update, context)
        return
    if state == "awaiting_reply":
        await process_reply_content(update, context)
        return
    if state == "awaiting_report_reason":
        await process_report_reason(update, context)
        return
    if state == "adm_ad_send":
        await process_ad_send(update, context)
        return
    if state in ("shop_add_title", "shop_add_price", "shop_add_reward", "shop_add_amount", "shop_add_days", "shop_add_18plus_days"):
        await process_shop_add(update, context)
        return
    if state in ("shop_edit_name", "shop_edit_price", "shop_edit_amount", "shop_edit_days", "shop_edit_18plus_days"):
        await process_shop_edit_value(update, context)
        return
    if state in ("shop_edit_pick", "shop_edit_menu"):
        await shop_edit_router(update, context)
        return
    if state in ("star_add_title", "star_add_coins", "star_add_price", "star_del"):
        await process_star_wizard(update, context)
        return
    if state and state.startswith("moder_q_"):
        await moder_q_router(update, context)
        return
    if state in ("moder_give_id", "moder_take_id"):
        await process_moder_give_take(update, context)
        return
    if state == "ban_id":
        await process_ban(update, context)
        return
    if state == "tg_pick":
        await process_tg_pick(update, context)
        return
    if state == "tg_watch":
        if canon(update.message.text) == "🚪 Выйти":
            detach_spectator(update.effective_user.id)
            context.user_data["state"] = None
            await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(update.effective_user.id))
        return
    if state == "modmsg_id":
        await process_modmsg_id(update, context)
        return
    if state == "modmsg_text":
        await process_modmsg_text(update, context)
        return
    if state == "admin_moder":
        await admin_moder_router(update, context)
        return
    if state in ("admin_vip", "vip_give_id", "vip_give_days", "vip_take_id"):
        await admin_vip_router(update, context)
        return
    if state and state.startswith("adm_coins_"):
        await process_adm_coins_wizard(update, context)
        return
    if state in ("adm_channels_menu", "adm_ch_name", "adm_ch_link", "adm_ch_confirm", "adm_ch_delete"):
        await adm_channels_router(update, context)
        return
    if state and state.startswith("adm_ad_"):
        await process_adm_ad_wizard(update, context)
        return
    if state == "adm_bcast_audience":
        await process_bcast_audience_text(update, context)
        return
    if state == "adm_bcast_content":
        await process_bcast_content(update, context)
        return
    if await relay_roulette_message(update, context):
        return
    if text == "⛔ Отменить поиск":
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (update.effective_user.id,))
        conn.commit()
        await nav(update, context, t("search_cancelled"), main_menu_kb(update.effective_user.id))
        return
    # Кнопки админ-клавиатуры
    if is_admin(update.effective_user.id):
        if text == "📊 Статистика":
            await adm_stats_msg(update, context)
            return
        if text == "📤 Выгрузить пользователей":
            await adm_export_msg(update, context)
            return
        if text == "💰 Начислить коины":
            context.user_data["state"] = "adm_coins_id"
            await update.message.reply_text("Введи tg_id или @username пользователя:", reply_markup=cancel_reply_kb())
            return
        if text == "📢 Обязательные каналы":
            await adm_channels_msg(update, context)
            return
        if text == "📣 Реклама":
            context.user_data["state"] = "adm_ad_text"
            context.user_data["ad"] = {}
            await update.message.reply_text("Текст рекламы:", reply_markup=cancel_reply_kb())
            return
        if text == "✉️ Рассылка":
            context.user_data["state"] = "adm_bcast_audience"
            await update.message.reply_text("Кому отправить рассылку?", reply_markup=bcast_audience_kb())
            return
        if text == "🛡 Модеры":
            await show_admin_moder(update, context)
            return
        if text == "🔨 Бан / Разбан":
            await start_ban(update, context, "admin")
            return
        if text == "⭐ Коины за Stars":
            await show_star_admin(update, context)
            return
        if text == "👑 VIP по ID":
            context.user_data["state"] = "admin_vip"
            await update.message.reply_text(t("admin_vip_menu"), parse_mode="HTML", reply_markup=admin_vip_kb())
            return
        if text in ("🔞 18+ доступ: ВКЛ", "🔞 18+ доступ: ВЫКЛ"):
            cur = get_setting("18plus_enabled", "1") == "1"
            set_setting("18plus_enabled", "0" if cur else "1")
            await update.message.reply_text(
                t("adm_18plus_off") if cur else t("adm_18plus_on"),
                parse_mode="HTML", reply_markup=admin_menu_kb(),
            )
            return
    # Главное меню — навигация доступна из любого раздела
    if text == "🔗 Моя ссылка":
        await show_link_menu(update, context)
        return
    if text == "🎲 Чат-рулетка":
        await show_roulette_entry(update, context)
        return
    if text == "18+ рулетка":
        await show_eighteen_plus_roulette(update, context)
        return
    if text == "👤 Профиль":
        await show_profile(update, context)
        return
    if text == "🛒 Магазин":
        context.user_data["state"] = None
        await show_shop(update, context)
        return
    if text == "🔞 18+ магазин":
        context.user_data["state"] = None
        await show_eighteen_plus_shop(update, context)
        return
    if text == "💎 Купить коины":
        await show_star_shop(update, context)
        return
    if text == "👥 Пригласить":
        await show_referral(update, context)
        return
    if text == "ℹ️ Помощь" and state != "moder":
        await show_help(update, context)
        return
    if text == "🌐 Язык":
        await show_language_menu(update, context)
        return
    if text == "🛠 Админка":
        context.user_data["state"] = None
        await show_admin_menu(update, context)
        return
    if text == "🛡 Модерка":
        await show_moder_menu(update, context)
        return
    # Под-меню разделов (reply-клавиатуры)
    if state == "moder":
        await moder_panel_router(update, context)
        return
    if state == "language":
        await language_router(update, context)
        return
    if state == "referral":
        await referral_router(update, context)
        return
    if state == "ref_settings":
        await ref_settings_router(update, context)
        return
    if state in ("ref_set_vip_days", "ref_set_vip_threshold", "ref_set_moder_days", "ref_set_moder_threshold"):
        await process_ref_setting_value(update, context)
        return
    if state == "ref_set_photo":
        if canon(update.message.text) == "❌ Отмена":
            await show_ref_settings(update, context)
        else:
            await update.message.reply_text("Отправьте именно фото (или «❌ Отмена»).", reply_markup=cancel_reply_kb())
        return
    if state == "link_menu":
        await link_menu_router(update, context)
        return
    if state == "profile":
        await profile_router(update, context)
        return
    if state == "roulette_pref":
        await roulette_pref_router(update, context)
        return
    if state == "shop":
        await shop_router(update, context)
        return
    if state == "shop_confirm":
        await shop_confirm_router(update, context)
        return
    if state == "star_shop":
        await star_shop_router(update, context)
        return
    if state == "star_confirm":
        await star_confirm_router(update, context)
        return
    if state == "star_admin":
        await star_admin_router(update, context)
        return
    # 18+ меню
    if text == "🔞 18+":
        await eighteen_plus_menu(update, context)
        return
    if text == "18+ магазин":
        await show_eighteen_plus_shop(update, context)
        return
    if state == "18plus_age_select":
        await eighteen_plus_age_router(update, context)
        return
    if state == "18plus_consent":
        await eighteen_plus_consent_router(update, context)
        return
    if state == "18plus_verify_offer":
        await eighteen_plus_verify_offer_router(update, context)
        return
    if state == "18plus_verify_upload":
        if canon(update.message.text) in ("❌ Отмена", "⬅️ Назад"):
            context.user_data["state"] = None
            await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
            return
        await update.message.reply_text(t("age_verify_ask_photo"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    if state == "18plus_menu":
        await eighteen_plus_menu_router(update, context)
        return
    if state == "18plus_pref":
        await eighteen_plus_pref_router(update, context)
        return
    if state in ("gift18_id", "gift18_confirm"):
        await gift_18plus_router(update, context)
        return
    if state in ("giftcoins_id", "giftcoins_amount"):
        await gift_coins_router(update, context)
        return
    if state == "18plus_age_search":
        await eighteen_plus_age_search_router(update, context)
        return
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    await nav(update, context, t("not_understood"), main_menu_kb(update.effective_user.id))


async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый роутер для голоса/фото/стикеров/гиф/видео/кружков/документов."""
    _u = get_user(update.effective_user.id)
    if _u and is_banned(_u) and not is_admin(update.effective_user.id):
        return
    state = context.user_data.get("state")
    if not state:
        _fl = load_link_flow(update.effective_user.id)
        if _fl:
            context.user_data["state"] = _fl["state"]
            context.user_data["anon_target"] = _fl["target_id"]
            if _fl["msg_type"]:
                context.user_data["anon_type"] = _fl["msg_type"]
            state = _fl["state"]
    # Админ выставляет фото для экрана «Пригласить»
    if state == "ref_set_photo" and is_admin(update.effective_user.id):
        if update.message and update.message.photo:
            set_setting("ref_photo", update.message.photo[-1].file_id)
            await update.message.reply_text("✅ Фото сохранено.")
            await show_ref_settings(update, context)
        else:
            await update.message.reply_text("Отправьте именно фото (или «❌ Отмена»).", reply_markup=cancel_reply_kb())
        return
    # Верификация возраста: пользователь прислал фото документа
    if state == "18plus_verify_upload":
        if update.message and update.message.photo:
            photo = update.message.photo[-1]
            uid = update.effective_user.id
            conn.execute(
                "INSERT INTO age_verification_requests (user_id, photo_file_id, created_at) VALUES (?, ?, ?)",
                (uid, photo.file_id, now_iso()),
            )
            conn.commit()
            context.user_data["state"] = None
            await update.message.reply_text(
                t("age_verification_sent"), parse_mode="HTML",
                reply_markup=main_menu_kb(uid),
            )
            # Уведомить только админов (не модеров) — с кружком фото и кнопками
            requester = get_user(uid)
            cap = (f"🔞 <b>Заявка на подтверждение 18+</b>\n"
                   f"Пользователь: {user_mention(requester)}\n"
                   f"ID: <code>{uid}</code>")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Одобрить", callback_data=f"agever:ok:{uid}"),
                 InlineKeyboardButton("❌ Отменить", callback_data=f"agever:no:{uid}")],
                [InlineKeyboardButton("✉️ В ЛС пользователю", url=f"tg://user?id={uid}")],
            ])
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_photo(admin_id, photo.file_id, caption=cap,
                                                 parse_mode="HTML", reply_markup=markup)
                except TelegramError:
                    pass
        else:
            await update.message.reply_text(t("age_verify_ask_photo"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return
    if state == "awaiting_anon_content":
        await process_anon_content(update, context)
        return
    if state == "awaiting_reply":
        await process_reply_content(update, context)
        return
    if state == "adm_bcast_content":
        await process_bcast_content(update, context)
        return
    if await relay_roulette_message(update, context):
        return



def _keep_alive_server():
    """Мини HTTP-сервер для хостингов типа Render (нужен открытый порт + пинг от UptimeRobot)."""
    port = int(os.getenv("PORT", "8080"))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:  # noqa
        log.warning("keep-alive server: %s", e)


async def on_error(event: ErrorEvent):
    """Глобальный обработчик ошибок — чтобы не падать и не спамить трейсбеками."""
    err = event.exception
    if isinstance(err, TelegramConflictError):
        log.warning("Conflict: бот запущен в нескольких местах. Оставь один инстанс!")
        return True
    log.error("Ошибка при обработке апдейта: %s", err)
    return True


# ============================ РЕГИСТРАЦИЯ ХЕНДЛЕРОВ aiogram ============================
def _mu(message):
    """aiogram Message -> UpdateShim для текстовых/медиа-хендлеров."""
    return UpdateShim(message=message, effective_user=message.from_user,
                      effective_chat=message.chat)


def _cu(cq):
    """aiogram CallbackQuery -> UpdateShim для callback-хендлеров."""
    return UpdateShim(callback_query=_CB(cq), effective_user=cq.from_user,
                      effective_chat=(cq.message.chat if cq.message else None))


async def _lang_middleware(handler, event, data):
    """Перед каждым апдейтом кладём язык пользователя в ContextVar (task-safe)."""
    user = data.get("event_from_user")
    if user:
        set_cur_lang(get_lang(user.id))
        touch_user(user.id)
    else:
        set_cur_lang("ru")
    return await handler(event, data)


# --- обёртки апдейтов под существующие (update, context)-хендлеры ---
async def _h_start(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    await cmd_start(_mu(message), Ctx(message.from_user.id, args=args))


async def _h_payment(message: Message):
    await on_successful_payment(_mu(message), Ctx(message.from_user.id))


async def _h_precheckout(pcq: PreCheckoutQuery):
    upd = UpdateShim(pre_checkout_query=pcq, effective_user=pcq.from_user)
    await on_precheckout(upd, Ctx(pcq.from_user.id))


async def _h_my_chat_member(event: ChatMemberUpdated):
    upd = UpdateShim(my_chat_member=event, effective_user=event.from_user,
                     effective_chat=event.chat)
    await on_my_chat_member(upd, Ctx(event.from_user.id))


async def _h_media(message: Message):
    await media_router(_mu(message), Ctx(message.from_user.id))


async def _h_text(message: Message):
    await text_router(_mu(message), Ctx(message.from_user.id))


# ── Скрытые команды модерации (в меню не показываются, только для персонала) ──
async def _h_cmd_tg(message: Message):
    if not is_staff(message.from_user.id):
        return
    await tg_start(_mu(message), Ctx(message.from_user.id))


async def _h_cmd_next(message: Message):
    if not is_staff(message.from_user.id):
        return
    await modmsg_start(_mu(message), Ctx(message.from_user.id))


# Карта callback-хендлеров: (ключ, функция, точное_совпадение)
_CALLBACKS = [
    ("back_main", on_back_main, True),
    ("reply:", on_reply_button, False),
    ("del:", on_delete_button, False),
    ("subcheck:", on_subcheck_button, False),
    ("subgate", on_subgate_check, True),
    ("report_anon:", on_report_anon, False),
    ("reveal:", on_reveal_button, False),
    ("reveal_pay:", on_reveal_pay, False),
    ("reveal_cancel", on_reveal_cancel, True),
    ("repadm:", on_report_admin_decision, False),
    ("roulette_cancel", on_roulette_cancel, True),
    ("modapp:", on_moder_app_decision, False),
    ("claim_vip", on_claim_vip, True),
    ("claim_moder", on_claim_moder, True),
    ("ref_info", on_ref_info, True),
    ("tgban:", on_tg_ban, False),
    ("agever:", on_age_verify_decision, False),
]


def _make_cb_handler(fn):
    async def _handler(cq: CallbackQuery):
        await fn(_cu(cq), Ctx(cq.from_user.id))
    return _handler


def register_handlers():
    dp.update.outer_middleware(_lang_middleware)
    dp.errors.register(on_error)

    dp.message.register(_h_start, CommandStart())
    # Скрытые команды модерации (в меню не показываются — set_my_commands содержит только /start)
    dp.message.register(_h_cmd_tg, Command("tg"))
    dp.message.register(_h_cmd_next, Command("next"))
    dp.pre_checkout_query.register(_h_precheckout)
    dp.message.register(_h_payment, F.successful_payment)
    dp.my_chat_member.register(_h_my_chat_member)

    for key, fn, exact in _CALLBACKS:
        flt = (F.data == key) if exact else F.data.startswith(key)
        dp.callback_query.register(_make_cb_handler(fn), flt)

    media_filter = (
        F.voice | F.photo | F.sticker | F.animation
        | F.video | F.video_note | F.document
    )
    dp.message.register(_h_media, media_filter)
    dp.message.register(_h_text, F.text & ~F.text.startswith("/"))


def run_safe_cleanup():
    """Безопасная очистка мусора. Пользователей и их данные НЕ трогает."""
    try:
        six_h = (now_dt() - timedelta(hours=6)).isoformat()
        ten_min = (now_dt() - timedelta(minutes=10)).isoformat()
        old_sessions = (now_dt() - timedelta(days=90)).isoformat()
        conn.execute("DELETE FROM link_flow WHERE updated_at < ?", (six_h,))
        conn.execute("DELETE FROM roulette_queue WHERE joined_at < ?", (ten_min,))
        # истёкшие баны (вечные баны хранятся как 9999-... и сюда не попадают)
        conn.execute("DELETE FROM bans WHERE until < ?", (now_iso(),))
        conn.execute(
            "DELETE FROM roulette_sessions WHERE active=0 AND ended_at IS NOT NULL AND ended_at < ?",
            (old_sessions,),
        )
        conn.commit()
        log.info("janitor: безопасная очистка выполнена")
    except Exception as e:  # noqa
        log.warning("safe_cleanup: %s", e)


async def _nudge_user(u):
    """Намёк неактивному ценному пользователю. Данные НЕ удаляются — только напоминание."""
    uid = u["tg_id"]
    try:
        na = u["nudged_at"]
        if na:
            try:
                if now_dt() - datetime.fromisoformat(na) < timedelta(days=JANITOR_PERIOD_DAYS - 1):
                    return False
            except (ValueError, TypeError):
                pass
        _sl = cur_lang(); set_cur_lang(get_lang(uid))
        await BOTP.send_message(uid, t("inactive_nudge"), parse_mode="HTML")
        set_cur_lang(_sl)
        conn.execute("UPDATE users SET nudged_at=? WHERE tg_id=?", (now_iso(), uid))
        conn.commit()
        await asyncio.sleep(0.05)  # мягкий троттлинг рассылки
        return True
    except TelegramError:
        return False
    except Exception as e:  # noqa
        log.warning("nudge %s: %s", uid, e)
        return False


async def janitor_heavy():
    """Раз в 2 недели: удаляет ПУСТЫЕ неактивные аккаунты, ценным шлёт намёк (без удаления)."""
    cutoff = (now_dt() - timedelta(days=INACTIVE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT * FROM users WHERE "
        "(last_active IS NOT NULL AND last_active < ?) OR "
        "(last_active IS NULL AND created_at < ?)",
        (cutoff, cutoff),
    ).fetchall()
    deleted = nudged = 0
    for u in rows:
        uid = u["tg_id"]
        if is_admin(uid) or is_staff(uid):       # персонал не трогаем
            continue
        has_stars = conn.execute("SELECT 1 FROM star_purchases WHERE user_id=? LIMIT 1", (uid,)).fetchone()
        has_ref = conn.execute("SELECT 1 FROM referrals WHERE referrer_id=? AND active=1 LIMIT 1", (uid,)).fetchone()
        invested = (u["coins"] or 0) > 0 or is_vip(u) or bool(has_stars)
        # Ценный (вложился) или часть графа (рефералы/ссылка) — НЕ удаляем
        if invested:
            if await _nudge_user(u):
                nudged += 1
        elif has_ref or u["custom_link"]:
            continue  # сохраняем для целостности ссылок/рефералов
        else:
            # Полностью пустой неактивный аккаунт — удаляем
            try:
                conn.execute("DELETE FROM users WHERE tg_id=?", (uid,))
                conn.execute("DELETE FROM referrals WHERE referred_id=?", (uid,))
                conn.execute("DELETE FROM link_flow WHERE user_id=?", (uid,))
                conn.commit()
                deleted += 1
            except Exception as e:  # noqa
                log.warning("janitor delete %s: %s", uid, e)
    log.info("janitor (раз в 2 недели): удалено пустых=%d, уведомлено=%d", deleted, nudged)
    if ADMIN_IDS and (deleted or nudged):
        for aid in ADMIN_IDS:
            try:
                await BOTP.send_message(
                    aid,
                    f"🧹 Авто-обслуживание:\n🗑 Удалено пустых аккаунтов: {deleted}\n"
                    f"📨 Напоминаний неактивным: {nudged}",
                )
            except TelegramError:
                pass


async def _janitor_loop():
    """Фоновый джанитор: безопасная очистка часто, тяжёлая часть — раз в 2 недели."""
    await asyncio.sleep(120)   # дать боту подняться
    while True:
        try:
            run_safe_cleanup()
            last = get_setting("janitor_last")
            do_heavy = True
            if last:
                try:
                    do_heavy = (now_dt() - datetime.fromisoformat(last)) >= timedelta(days=JANITOR_PERIOD_DAYS)
                except ValueError:
                    pass
            if do_heavy:
                await janitor_heavy()
                await janitor_unreachable_sweep()
                set_setting("janitor_last", now_iso())
        except Exception as e:  # noqa
            log.error("janitor_loop: %s", e)
        await asyncio.sleep(JANITOR_WAKE_HOURS * 3600)


async def _matchmaker_loop():
    """Аналог job_queue.run_repeating: периодически сводит пары в рулетке."""
    ctx = Ctx(0)
    while True:
        await asyncio.sleep(ROULETTE_TICK_SECONDS)
        try:
            await roulette_matchmaker(ctx)
        except Exception as e:  # noqa
            log.error("matchmaker: %s", e)


async def _run():
    init_db()
    register_handlers()
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Запустить бота")])
    except Exception as e:  # noqa
        log.warning("set_my_commands: %s", e)
    # На случай, если ранее был установлен вебхук — иначе поллинг конфликтует.
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:  # noqa
        log.warning("delete_webhook: %s", e)
    asyncio.create_task(_matchmaker_loop())
    asyncio.create_task(_janitor_loop())
    log.info("Бот запущен, поллинг...")
    await dp.start_polling(bot)


def main():
    # фоновый веб-сервер СНАЧАЛА (Render ждёт открытый PORT чтобы считать сервис живым)
    threading.Thread(target=_keep_alive_server, daemon=True).start()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
