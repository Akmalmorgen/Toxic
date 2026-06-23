"""
Анонимный бот: Анон.Вопрос / Валентинка + Чат-рулетка по полу + Магазин (коины, VIP) + Админка.
Стек: aiogram v3, sqlite3 (stdlib) / PostgreSQL (Neon).
"""

import os
import sqlite3
import logging
import random
import string
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
from aiogram.exceptions import TelegramAPIError, TelegramConflictError
from aiogram.filters import CommandStart, CommandObject
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
ROULETTE_TICK_SECONDS = 3
LINK_CHANGE_COOLDOWN_DAYS = 7
VIP_DISCOUNT_PERCENT = 20   # скидка VIP в магазине, %
VIP_DAILY_BONUS = 5         # ежедневный бонус VIP, коинов

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
        joined_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS roulette_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        ended_by INTEGER,
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
        chat_username TEXT NOT NULL
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



def get_user(tg_id):
    return conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


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
    return bool(user_row) and bool(user_row["is_moder"])


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
    "📤 Выгрузить пользователей": ("📤 Foydalanuvchilarni yuklash", "📤 Export users"),
    "💰 Начислить коины": ("💰 Coin qo'shish", "💰 Add coins"),
    "📢 Обязательные каналы": ("📢 Majburiy kanallar", "📢 Required channels"),
    "📣 Реклама": ("📣 Reklama", "📣 Ad"),
    "✉️ Рассылка": ("✉️ Xabar tarqatish", "✉️ Broadcast"),
    "📢 Рассылка": ("📢 Xabar tarqatish", "📢 Broadcast"),
    "🛡 Модеры": ("🛡 Moderatorlar", "🛡 Moderators"),
    "🔨 Бан / Разбан": ("🔨 Ban / Unban", "🔨 Ban / Unban"),
    "⭐ Коины за Stars": ("⭐ Stars uchun coin", "⭐ Coins for Stars"),
    "⬅️ Назад": ("⬅️ Orqaga", "⬅️ Back"),
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
    "📤 Отправить всем": ("📤 Hammaga yuborish", "📤 Send to all"),
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
        "ru": "🔗 <b>Ваша персональная ссылка:</b>\n<blockquote>{link}</blockquote><i>Делитесь ей — вам будут писать анонимно</i> 💌",
        "uz": "🔗 <b>Shaxsiy havolangiz:</b>\n<blockquote>{link}</blockquote><i>Uni ulashing — sizga anonim yozishadi</i> 💌",
        "en": "🔗 <b>Your personal link:</b>\n<blockquote>{link}</blockquote><i>Share it — people will message you anonymously</i> 💌",
    },
    "link_done": {
        "ru": "✅ <b>Готово! Ваша ссылка:</b>\n<blockquote>{link}</blockquote>",
        "uz": "✅ <b>Tayyor! Havolangiz:</b>\n<blockquote>{link}</blockquote>",
        "en": "✅ <b>Done! Your link:</b>\n<blockquote>{link}</blockquote>",
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
    # === Профиль (доп.) ===
    "profile_full": {
        "ru": (
            "👤 <b>Ваш профиль</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "Пол: <b>{gender}</b>\n"
            "Поиск в рулетке: <b>{pref}</b>\n"
            "Коины: <b>{coins}</b> 💎\n"
            "VIP: <b>{vip}</b>"
            "</blockquote>"
        ),
        "uz": (
            "👤 <b>Profilingiz</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "Jins: <b>{gender}</b>\n"
            "Ruletkada qidiruv: <b>{pref}</b>\n"
            "Coinlar: <b>{coins}</b> 💎\n"
            "VIP: <b>{vip}</b>"
            "</blockquote>"
        ),
        "en": (
            "👤 <b>Your profile</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "Gender: <b>{gender}</b>\n"
            "Roulette search: <b>{pref}</b>\n"
            "Coins: <b>{coins}</b> 💎\n"
            "VIP: <b>{vip}</b>"
            "</blockquote>"
        ),
    },
    "vip_none": {"ru": "—", "uz": "—", "en": "—"},
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
        "ru": "🚫 На вас поступила жалоба — вы заблокированы на {days} дн.",
        "uz": "🚫 Sizga shikoyat tushdi — siz {days} kunga bloklandingiz.",
        "en": "🚫 You were reported and have been blocked for {days} days.",
    },
    "anon_deleted_notice": {
        "ru": "🗑 Собеседник удалил своё анонимное сообщение.",
        "uz": "🗑 Suhbatdosh o'zining anonim xabarini o'chirdi.",
        "en": "🗑 The sender deleted their anonymous message.",
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
    # === Жалоба (доп., для пользователя) ===
    "report_confirmed_user": {
        "ru": "Жалоба подтверждена. Отправитель заблокирован на {days} дней ✅",
        "uz": "Shikoyat tasdiqlandi. Yuboruvchi {days} kunga bloklandi ✅",
        "en": "Report confirmed. The sender is blocked for {days} days ✅",
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
            "<blockquote>{link}</blockquote>"
            "⚠️ Если друг заблокирует бота — коины за него спишутся обратно."
        ),
        "uz": (
            "👥 <b>Do'stlarni taklif qiling — coin ishlang!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Har bir do'st uchun: <b>{reward}</b> 💎{bonus}\n"
            "Taklif qilindi: <b>{total}</b>\n"
            "Ishlab topildi: <b>{earned}</b> 💎\n\n"
            "🔗 Havolangiz:\n"
            "<blockquote>{link}</blockquote>"
            "⚠️ Agar do'st botni bloklasa — uning coinlari qaytarib olinadi."
        ),
        "en": (
            "👥 <b>Invite friends — earn coins!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "For each friend: <b>{reward}</b> 💎{bonus}\n"
            "Invited: <b>{total}</b>\n"
            "Earned: <b>{earned}</b> 💎\n\n"
            "🔗 Your link:\n"
            "<blockquote>{link}</blockquote>"
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
        "ru": "👁️ Да, раскрыть · 1 ⭐",
        "uz": "👁️ Ha, aniqlash · 1 ⭐",
        "en": "👁️ Yes, reveal · 1 ⭐",
    },
    "btn_cancel_accent": {
        "ru": "✖️ Отмена",
        "uz": "✖️ Bekor qilish",
        "en": "✖️ Cancel",
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
        "ru": "💬 Ответить",
        "uz": "💬 Javob berish",
        "en": "💬 Reply",
    },
    "btn_report": {
        "ru": "🚩 Пожаловаться",
        "uz": "🚩 Shikoyat",
        "en": "🚩 Report",
    },
    "btn_reveal": {
        "ru": "👁️ Узнать кто · 1 ⭐",
        "uz": "👁️ Kim ekan? · 1 ⭐",
        "en": "👁️ Reveal who · 1 ⭐",
    },
    "btn_delete": {
        "ru": "🗑️ Удалить",
        "uz": "🗑️ O'chirish",
        "en": "🗑️ Delete",
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
            "Добро пожаловать в <b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b> 💙\n"
            "<i>Место, где тебе пишут анонимно — а ты пишешь кому угодно.</i>\n\n"
            "<blockquote>🔗 Анонимные вопросы и валентинки по твоей ссылке\n"
            "🎲 Чат-рулетка — собеседник по выбранному полу\n"
            "🕵️ Полная анонимность и контроль над перепиской</blockquote>\n"
            "✨ Чтобы начать, выбери свой пол 👇"
        ),
        "uz": (
            "👋 <b>Salom, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b>ga xush kelibsiz 💙\n"
            "<i>Bu yerda sizga anonim yozishadi — siz esa istalgan kishiga.</i>\n\n"
            "<blockquote>🔗 Havolangiz orqali anonim savol va valentinkalar\n"
            "🎲 Chat-ruletka — tanlangan jins bo'yicha suhbatdosh\n"
            "🕵️ To'liq anonimlik va yozishmalar ustidan nazorat</blockquote>\n"
            "✨ Boshlash uchun jinsingizni tanlang 👇"
        ),
        "en": (
            "👋 <b>Hi, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome to <b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b> 💙\n"
            "<i>A place where people message you anonymously — and you message anyone.</i>\n\n"
            "<blockquote>🔗 Anonymous questions and valentines via your link\n"
            "🎲 Chat roulette — a partner by the chosen gender\n"
            "🕵️ Full anonymity and control over your chats</blockquote>\n"
            "✨ To get started, choose your gender 👇"
        ),
    },
    "help": {
        "ru": (
            "ℹ️ <b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Анонимные сообщения, тайные признания и живое общение — в одном месте.</i>\n\n"
            "✨ <b>Основные разделы:</b>\n"
            "<blockquote>"
            "🔗 <b>Моя ссылка</b> — личная ссылка для анонимных вопросов и валентинок. Делись ей где угодно.\n"
            "🎲 <b>Чат-рулетка</b> — случайный собеседник по выбранному полу.\n"
            "👤 <b>Профиль</b> — твой пол, баланс коинов и VIP-статус.\n"
            "🛒 <b>Магазин</b> — трать коины на VIP и другие товары.\n"
            "👥 <b>Пригласить</b> — зови друзей и получай <b>+20</b> 💎 (VIP — <b>+50</b> 💎).\n"
            "💎 <b>Купить коины</b> — пополнение за Telegram Stars ⭐.\n"
            "🌐 <b>Язык</b> — русский, узбекский или английский."
            "</blockquote>\n"
            "👑 <b>Что даёт VIP:</b>\n"
            "<blockquote>"
            "• без лимита анонимных сообщений\n"
            "• скидка <b>20%</b> в магазине\n"
            "• <b>+5</b> 💎 каждый день\n"
            "• приоритет в чат-рулетке\n"
            "• корона и медиа (фото/видео/гиф) в анонимках\n"
            "• безлимитная смена ссылки"
            "</blockquote>\n"
            "💬 <i>Выбери раздел в меню ниже 👇</i>"
        ),
        "uz": (
            "ℹ️ <b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Anonim xabarlar, sirli e'tiroflar va jonli muloqot — bir joyda.</i>\n\n"
            "✨ <b>Asosiy bo'limlar:</b>\n"
            "<blockquote>"
            "🔗 <b>Havolam</b> — anonim savol va valentinkalar uchun shaxsiy havola. Uni istalgan joyda ulashing.\n"
            "🎲 <b>Chat-ruletka</b> — tanlangan jins bo'yicha tasodifiy suhbatdosh.\n"
            "👤 <b>Profil</b> — jinsingiz, coin balansi va VIP holati.\n"
            "🛒 <b>Do'kon</b> — coinlarni VIP va boshqa mahsulotlarga sarflang.\n"
            "👥 <b>Taklif qilish</b> — do'stlarni chaqiring va <b>+20</b> 💎 oling (VIP — <b>+50</b> 💎).\n"
            "💎 <b>Coin sotib olish</b> — Telegram Stars ⭐ orqali to'ldirish.\n"
            "🌐 <b>Til</b> — rus, o'zbek yoki ingliz."
            "</blockquote>\n"
            "👑 <b>VIP nima beradi:</b>\n"
            "<blockquote>"
            "• anonim xabarlar limitisiz\n"
            "• do'konda <b>20%</b> chegirma\n"
            "• har kuni <b>+5</b> 💎\n"
            "• chat-ruletkada ustunlik\n"
            "• anonimlarda toj va media (foto/video/gif)\n"
            "• havolani cheksiz o'zgartirish"
            "</blockquote>\n"
            "💬 <i>Quyidagi menyudan bo'limni tanlang 👇</i>"
        ),
        "en": (
            "ℹ️ <b>👾 𐌽EXT | Ан᧐нᥙⲙныᥔ Կᥲᴛ</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Anonymous messages, secret confessions and live chatting — all in one place.</i>\n\n"
            "✨ <b>Main sections:</b>\n"
            "<blockquote>"
            "🔗 <b>My link</b> — your personal link for anonymous questions and valentines. Share it anywhere.\n"
            "🎲 <b>Chat roulette</b> — a random partner by the gender you choose.\n"
            "👤 <b>Profile</b> — your gender, coin balance and VIP status.\n"
            "🛒 <b>Shop</b> — spend coins on VIP and other items.\n"
            "👥 <b>Invite</b> — invite friends and get <b>+20</b> 💎 (VIP — <b>+50</b> 💎).\n"
            "💎 <b>Buy coins</b> — top up with Telegram Stars ⭐.\n"
            "🌐 <b>Language</b> — Russian, Uzbek or English."
            "</blockquote>\n"
            "👑 <b>What VIP gives:</b>\n"
            "<blockquote>"
            "• no limit on anonymous messages\n"
            "• <b>20%</b> discount in the shop\n"
            "• <b>+5</b> 💎 every day\n"
            "• priority in chat roulette\n"
            "• crown and media (photo/video/gif) in anon messages\n"
            "• unlimited link change"
            "</blockquote>\n"
            "💬 <i>Pick a section in the menu below 👇</i>"
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
        "ru": "Собеседник найден! 🎉 Пиши смело.",
        "uz": "Suhbatdosh topildi! 🎉 Bemalol yozing.",
        "en": "Partner found! 🎉 Write away.",
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
    ], resize_keyboard=True, one_time_keyboard=True)


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
    ], resize_keyboard=True, one_time_keyboard=True))


def reward_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("💎 Коины"), KeyboardButton("⏳ VIP")],
        [KeyboardButton("🛡 Модер"), KeyboardButton("📦 Вручную")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True, one_time_keyboard=True))


def admin_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("💰 Начислить коины"), KeyboardButton("📢 Обязательные каналы")],
        [KeyboardButton("📣 Реклама"), KeyboardButton("✉️ Рассылка")],
        [KeyboardButton("🛡 Модеры"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("⭐ Коины за Stars")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def star_admin_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить пакет коинов")],
        [KeyboardButton("🗑 Удалить пакет коинов")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def moder_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🚩 Жалобы"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("📤 Выгрузить пользователей"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📢 Рассылка")],
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
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True))


def link_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔗 Показать ссылку"), KeyboardButton("✏️ Сменить ссылку")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def roulette_pref_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку"), KeyboardButton("🤷 Любого")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True, one_time_keyboard=True))


def anon_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("❓ Вопрос"), KeyboardButton("💌 Валентинка")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True))


def report_reason_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🤬 Мат"), KeyboardButton("💰 Мошенничество")],
        [KeyboardButton("😡 Оскорбление"), KeyboardButton("🔞 18+ стикеры")],
        [KeyboardButton("👎 Не нравится")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True))


async def clean_screen(update, context):
    """Удаляет нажатую пользователем кнопку и предыдущее меню бота, чтобы не мусорить в чате."""
    try:
        await update.message.delete()
    except TelegramError:
        pass
    mid = context.user_data.pop("last_menu_msg_id", None)
    if mid:
        await try_delete_message(context, update.effective_chat.id, mid)


async def send_menu(update, context, text, reply_markup, parse_mode=None):
    """Отправляет новое меню и запоминает его id для последующей очистки."""
    msg = await context.bot.send_message(update.effective_chat.id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    context.user_data["last_menu_msg_id"] = msg.message_id
    return msg


async def nav(update, context, text, reply_markup=None, parse_mode=None):
    """Единый «экран»: удаляет нажатие пользователя и прошлое меню, показывает одно новое сообщение."""
    await clean_screen(update, context)
    return await send_menu(update, context, text, reply_markup, parse_mode)


def profile_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("✏️ Сменить пол")],
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

    if not user["gender"]:
        context.user_data["state"] = "set_gender_first"
        name = tg_user.first_name or "друг"
        await update.message.reply_text(
            t("welcome", name=html.escape(name)),
            parse_mode="HTML",
            reply_markup=gender_kb(),
        )
        return

    await update.message.reply_text(
        t("main_menu"), reply_markup=main_menu_kb(tg_user.id)
    )


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
    context.user_data["state"] = None
    g = {"m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
         "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"}}[gender][cur_lang()]
    await update.message.reply_text(
        t("gender_saved", g=g),
        parse_mode="HTML",
        reply_markup=main_menu_kb(update.effective_user.id),
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
        await update.message.reply_text(
            t("link_no_link"),
            reply_markup=cancel_reply_kb(),
        )
        return
    bot_username = (await context.bot.get_me()).username
    link = f"t.me/{bot_username}?start={user['custom_link']}"
    await update.message.reply_text(
        t("link_show", link=html.escape(link)),
        parse_mode="HTML",
        reply_markup=link_menu_kb(),
    )


async def start_change_link(update, context):
    user = get_user(update.effective_user.id)
    can_change, error_msg = can_change_link(user)
    if not can_change:
        await update.message.reply_text(error_msg, reply_markup=link_menu_kb())
        return
    context.user_data["state"] = "awaiting_link_code"
    await update.message.reply_text(
        t("link_change"),
        reply_markup=cancel_reply_kb(),
    )


async def process_link_code(update, context, code):
    code = (code or "").strip()
    if canon(code) == "❌ Отмена":
        context.user_data["state"] = "link_menu"
        await update.message.reply_text(t("cancelled"), reply_markup=link_menu_kb())
        return
    if not valid_link_code(code):
        await update.message.reply_text(
            t("link_invalid"),
            reply_markup=cancel_reply_kb(),
        )
        return
    exists = conn.execute("SELECT tg_id FROM users WHERE custom_link=?", (code,)).fetchone()
    if exists and exists["tg_id"] != update.effective_user.id:
        await update.message.reply_text(t("link_taken"), reply_markup=cancel_reply_kb())
        return
    conn.execute(
        "UPDATE users SET custom_link=?, link_changed_at=? WHERE tg_id=?",
        (code, now_iso(), update.effective_user.id),
    )
    conn.commit()
    context.user_data["state"] = "link_menu"
    bot_username = (await context.bot.get_me()).username
    link = f"t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        t("link_done", link=html.escape(link)),
        parse_mode="HTML",
        reply_markup=link_menu_kb(),
    )


async def handle_incoming_link(update, context, code):
    sender_id = update.effective_user.id
    sender_row = ensure_user(sender_id, update.effective_user.username, update.effective_user.first_name)
    if is_banned(sender_row):
        await update.message.reply_text(t("banned"))
        return
    owner = conn.execute("SELECT * FROM users WHERE custom_link=?", (code,)).fetchone()
    if not owner:
        await update.message.reply_text(t("anon_invalid_link"))
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
        return
    context.user_data["state"] = "awaiting_anon_type"
    context.user_data["anon_target"] = owner["tg_id"]
    await update.message.reply_text(t("anon_what_send"), reply_markup=anon_type_kb())



async def on_anon_type_text(update, context):
    text = canon(update.message.text)
    if text == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("anon_target", None)
        await update.message.reply_text(
            t("anon_cancelled_menu"),
            reply_markup=main_menu_kb(update.effective_user.id)
        )
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
            return
    extracted = await extract_anon_content(update, is_v)
    if extracted is None:
        return
    content_type, text, voice_file_id = extracted
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
    if mid is None:
        await context.bot.send_message(
            sender.id, t("anon_failed"), reply_markup=main_menu_kb(sender.id)
        )
        return
    await context.bot.send_message(sender.id, t("main_menu"), reply_markup=main_menu_kb(sender.id))


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
    await update.message.reply_text(t("anon_reply_sent"), reply_markup=main_menu_kb(replier.id))



async def get_mandatory_channels():
    return conn.execute("SELECT * FROM mandatory_channels").fetchall()


async def user_subscribed_all(context, user_id, channels):
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["chat_username"], user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except TelegramError:
            return False
    return True


async def on_delete_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    channels = await get_mandatory_channels()
    if channels:
        ok = await user_subscribed_all(context, query.from_user.id, channels)
        if not ok:
            text = t("sub_to_delete")
            text += "\n".join(f"https://t.me/{c['chat_username'].lstrip('@')}" for c in channels)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_subscribed"), callback_data=f"subcheck:{msg_id}")]])
            await query.message.reply_text(text, reply_markup=kb)
            return
    await do_delete_message(query, context, msg_id)


async def on_subcheck_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    channels = await get_mandatory_channels()
    ok = await user_subscribed_all(context, query.from_user.id, channels)
    if not ok:
        await query.message.reply_text(t("sub_not_found"))
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
            InlineKeyboardButton("🔨 Бан 7 дн.", callback_data=f"repadm:ok:{report_id}"),
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
            InlineKeyboardButton("🔨 Бан 7 дн.", callback_data=f"repadm:ok:{report_id}"),
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
        conn.execute(
            "INSERT INTO bans (owner_id, banned_id, until, created_at) VALUES (?, ?, ?, ?)",
            (report["reporter_id"], report["reported_id"], until, now_iso()),
        )
        conn.execute("UPDATE reports SET status='confirmed' WHERE id=?", (report_id,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(report["reporter_id"]))
            await context.bot.send_message(
                report["reporter_id"], t("report_confirmed_user", days=BAN_DAYS)
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        # Уведомляем самого заблокированного пользователя (на его языке)
        try:
            _sl2 = cur_lang()
            set_cur_lang(get_lang(report["reported_id"]))
            await context.bot.send_message(report["reported_id"], t("you_were_banned", days=BAN_DAYS))
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



async def show_profile(update, context):
    user = get_user(update.effective_user.id)
    if is_unlimited(user):
        vip_status = t("vip_forever")
        coins_display = "∞"
    elif is_vip(user):
        vip_status = t("vip_until", date=user['vip_until'][:10])
        coins_display = user['coins']
    else:
        vip_status = t("vip_none")
        coins_display = user['coins']
    text = t(
        "profile_full",
        gender=gender_label(user['gender']),
        pref=pref_label(user['search_pref']) if user['search_pref'] else t("vip_none"),
        coins=coins_display,
        vip=vip_status,
    )
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
    await context.bot.send_message(update.effective_chat.id, t("choose_action"), reply_markup=profile_kb())


def searching_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⛔ Отменить поиск")]], resize_keyboard=True))


def cancel_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True, one_time_keyboard=True))


def bcast_audience_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👥 Всем")],
        [KeyboardButton("👨 Мужчинам"), KeyboardButton("👩 Женщинам")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True, one_time_keyboard=True))


def in_chat_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_next"), callback_data="roulette_next"),
        InlineKeyboardButton(t("btn_stop"), callback_data="roulette_stop"),
    ]])


def left_chat_kb(session_id):
    """Панель после того, как собеседник покинул чат: новый поиск + жалоба."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_new_search"), callback_data="roulette_research"),
        InlineKeyboardButton(t("btn_complain"), callback_data=f"rrep:{session_id}"),
    ]])


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
        sent = await context.bot.send_message(update.effective_chat.id, t("roulette_already_chat"), reply_markup=in_chat_kb())
        UD[user["tg_id"]]["roulette_msg_id"] = sent.message_id
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
    for i, a in enumerate(rows):
        if a["user_id"] in matched_ids:
            continue
        for b in rows[i + 1:]:
            if b["user_id"] in matched_ids:
                continue
            if compatible(a, b) and not is_banned_pair(a["user_id"], b["user_id"]):
                conn.execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", (a["user_id"], b["user_id"]))
                conn.execute(
                    "INSERT INTO roulette_sessions (user1_id, user2_id, active, started_at) VALUES (?, ?, 1, ?)",
                    (a["user_id"], b["user_id"], now_iso()),
                )
                conn.commit()
                matched_ids.add(a["user_id"])
                matched_ids.add(b["user_id"])
                for uid in (a["user_id"], b["user_id"]):
                    try:
                        sent = await context.bot.send_message(uid, t("roulette_found"), reply_markup=in_chat_kb())
                        # Запоминаем id «панели чата», чтобы потом отредактировать её
                        UD[uid]["roulette_msg_id"] = sent.message_id
                    except TelegramError:
                        pass
                break


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
    # Второму участнику: меняем его «панель чата» на сообщение «собеседник ушёл»
    # с кнопками «Новый поиск» и «Пожаловаться» — без спама новыми сообщениями.
    # Рендерим на ЕГО языке.
    _sl = cur_lang()
    set_cur_lang(get_lang(other_id))
    kb = left_chat_kb(session["id"])
    other_msg_id = UD[other_id].get("roulette_msg_id")
    edited = False
    if other_msg_id:
        try:
            await context.bot.edit_message_text(
                text=t("roulette_left"),
                chat_id=other_id,
                message_id=other_msg_id,
                reply_markup=kb,
            )
            edited = True
        except TelegramError:
            pass
    if not edited:
        try:
            sent = await context.bot.send_message(other_id, t("roulette_left"), reply_markup=kb)
            UD[other_id]["roulette_msg_id"] = sent.message_id
        except TelegramError:
            pass
    set_cur_lang(_sl)
    if requeue_ender:
        user = get_user(ender_id)
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, joined_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, joined_at=excluded.joined_at",
            (ender_id, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, now_iso()),
        )
        conn.commit()
    return session


async def _requeue_and_search(context, uid):
    """Ставит пользователя в очередь с его прежними настройками и показывает экран поиска."""
    user = get_user(uid)
    conn.execute(
        "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, joined_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, joined_at=excluded.joined_at",
        (uid, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, now_iso()),
    )
    conn.commit()
    await context.bot.send_message(uid, t("roulette_finding_partner"), reply_markup=searching_kb())


async def on_roulette_next(update, context):
    query = update.callback_query
    await query.answer(t("roulette_searching_new"))
    # Убираем кнопки с нажатой панели, чтобы по ней нельзя было кликать повторно
    try:
        await query.edit_message_text(t("roulette_chat_ended"))
    except TelegramError:
        pass
    await end_roulette_session(context, query.from_user.id, requeue_ender=True)
    # Новая панель чата появится при следующем матче; пока показываем reply-клаву отмены
    await _requeue_and_search(context, query.from_user.id)


async def on_roulette_stop(update, context):
    query = update.callback_query
    await query.answer(t("roulette_chat_stopped"))
    # Убираем кнопки с панели завершённого чата
    try:
        await query.edit_message_text(t("roulette_chat_stopped"))
    except TelegramError:
        pass
    await end_roulette_session(context, query.from_user.id, requeue_ender=False)
    # Сам нажал «Стоп» → возвращаем к выбору, кого искать
    context.user_data["state"] = "roulette_pref"
    await context.bot.send_message(
        query.from_user.id,
        t("roulette_who"),
        reply_markup=roulette_pref_reply_kb(),
    )


async def on_roulette_research(update, context):
    """Кнопка «Новый поиск» у того, кого покинули: ищем заново с прежними настройками."""
    query = update.callback_query
    uid = query.from_user.id
    if get_active_session(uid):
        await query.answer(t("roulette_already_short"))
        return
    await query.answer(t("roulette_searching_new"))
    # уже в очереди?
    if conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (uid,)).fetchone():
        return
    try:
        await query.edit_message_text(t("roulette_finding_new"))
    except TelegramError:
        pass
    await _requeue_and_search(context, uid)



async def relay_roulette_message(update, context):
    session = get_active_session(update.effective_user.id)
    if not session:
        return False
    other_id = session["user2_id"] if session["user1_id"] == update.effective_user.id else session["user1_id"]
    try:
        await context.bot.copy_message(other_id, update.effective_chat.id, update.message.message_id)
    except TelegramError:
        pass
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


async def show_shop(update, context):
    items = conn.execute("SELECT * FROM shop_items WHERE active=1").fetchall()
    context.user_data["state"] = "shop"
    shop_map = {}
    rows = []
    for it in items:
        label = f"{it['title']} — {it['price']} 💎"
        shop_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    context.user_data["shop_map"] = shop_map
    if is_admin(update.effective_user.id):
        rows.append([KeyboardButton("➕ Добавить товар"), KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])
    text = t("shop_title") if items else t("shop_empty")
    await nav(update, context, text, tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)), parse_mode="HTML")


async def shop_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "⬅️ Назад":
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
        t("shop_buy_confirm", title=html.escape(item['title']), price=price_txt),
        yes_no_kb(), parse_mode="HTML",
    )


async def shop_confirm_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id
    if text == "❌ Отмена":
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
                resize_keyboard=True, one_time_keyboard=True,
            )),
            parse_mode="HTML",
        )
    else:  # manual
        context.user_data["state"] = None
        await nav(
            update, context,
            t("purchase_manual"),
            main_menu_kb(uid), parse_mode="HTML",
        )


# ── Анкета модератора ──

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


async def process_shop_add(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    item = context.user_data.setdefault("new_item", {})
    if text == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(update.effective_user.id))
        await show_shop(update, context)
        return
    if state == "shop_add_title":
        item["title"] = text
        context.user_data["state"] = "shop_add_price"
        await update.message.reply_text("💰 Цена в коинах:", reply_markup=cancel_reply_kb())
    elif state == "shop_add_price":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        item["price"] = int(text)
        context.user_data["state"] = "shop_add_reward"
        await update.message.reply_text("🎁 Что получит покупатель при покупке?", reply_markup=reward_type_kb())
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
            save_new_item(item)
            context.user_data["state"] = None
            await update.message.reply_text("✅ Товар добавлен!", reply_markup=main_menu_kb(update.effective_user.id))
            await show_shop(update, context)
    elif state == "shop_add_amount":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        item["reward_amount"] = int(text)
        save_new_item(item)
        context.user_data["state"] = None
        await update.message.reply_text("✅ Товар добавлен!", reply_markup=main_menu_kb(update.effective_user.id))
        await show_shop(update, context)
    elif state == "shop_add_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней:", reply_markup=cancel_reply_kb())
            return
        item["reward_amount"] = int(text)
        save_new_item(item)
        context.user_data["state"] = None
        await update.message.reply_text("✅ VIP-товар добавлен!", reply_markup=main_menu_kb(update.effective_user.id))
        await show_shop(update, context)


def save_new_item(item):
    rt = item.get("reward_type", "manual")
    conn.execute(
        "INSERT INTO shop_items (title, price, is_vip, duration_days, reward_type, reward_amount, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (
            item["title"], item["price"],
            1 if rt == "vip" else 0,
            item.get("reward_amount") if rt == "vip" else None,
            rt,
            item.get("reward_amount"),
        ),
    )
    conn.commit()


async def shop_edit_list(update, context):
    items = conn.execute("SELECT * FROM shop_items WHERE active=1").fetchall()
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
    rows.append([KeyboardButton("🗑 Удалить товар")])
    rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def shop_edit_router(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text)
    uid = update.effective_user.id
    if state == "shop_edit_pick":
        if text == "⬅️ Назад":
            await show_shop(update, context)
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
        await show_shop(update, context)
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
    if text == "🗑 Удалить товар":
        conn.execute("UPDATE shop_items SET active=0 WHERE id=?", (item_id,))
        conn.commit()
        await update.message.reply_text("🗑 Товар удалён.", reply_markup=main_menu_kb(uid))
        await show_shop(update, context)
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
        conn.execute("UPDATE shop_items SET title=? WHERE id=?", (text, item_id))
        conn.commit()
        msg = "✅ Название изменено."
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
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


async def show_admin_moder(update, context):
    context.user_data["state"] = "admin_moder"
    await update.message.reply_text("🛡 Управление модерами:", reply_markup=admin_moder_kb())


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
    if text == "📤 Выгрузить пользователей":
        await adm_export_msg(update, context)
        return
    if text == "📊 Статистика":
        await adm_stats_msg(update, context)
        return
    if text == "📢 Рассылка":
        context.user_data["state"] = "adm_bcast_audience"
        await update.message.reply_text("Кому отправить рассылку?", reply_markup=bcast_audience_kb())
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
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔨 Бан 7 дн.", callback_data=f"repadm:ok:{r['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"repadm:no:{r['id']}"),
        ]])
        await context.bot.send_message(update.effective_chat.id, body, reply_markup=kb)


async def notify_staff(context, text, reply_markup=None, parse_mode=None):
    """Уведомление всем админам и модерам."""
    targets = set(ADMIN_IDS)
    for r in conn.execute("SELECT tg_id FROM users WHERE is_moder=1").fetchall():
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
    vip_count = conn.execute("SELECT COUNT(*) c FROM users WHERE vip_until>?", (now_iso(),)).fetchone()["c"]
    moders_count = conn.execute("SELECT COUNT(*) c FROM users WHERE is_moder=1").fetchone()["c"]
    kb = admin_menu_kb() if is_admin(update.effective_user.id) else moder_menu_kb()
    await update.message.reply_text(
        f"📊 Статистика:\nПользователей: {users_count}\nАнон-сообщений: {msgs_count}\n"
        f"Сессий рулетки: {sessions_count}\nVIP сейчас: {vip_count}\nМодеров: {moders_count}",
        reply_markup=kb,
    )


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
    text = "Обязательные каналы:\n" + ("\n".join(c["chat_username"] for c in channels) or "(пусто)")
    context.user_data["state"] = "adm_channel_add"
    await update.message.reply_text(
        text + "\n\nОтправь @username канала, чтобы добавить, или «❌ Отмена».",
        reply_markup=cancel_reply_kb(),
    )


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
        if not text.isdigit():
            await update.message.reply_text("id должен быть числом:")
            return
        context.user_data["coins_target"] = int(text)
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



async def process_adm_channel_wizard(update, context):
    username = update.message.text.strip()
    if username == "❌ Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=admin_menu_kb())
        return
    conn.execute("INSERT INTO mandatory_channels (chat_username) VALUES (?)", (username,))
    conn.commit()
    context.user_data["state"] = None
    await update.message.reply_text(f"Канал {username} добавлен ✅", reply_markup=admin_menu_kb())


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
            resize_keyboard=True, one_time_keyboard=True,
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
        except TelegramError:
            failed += 1
    context.user_data["state"] = "admin" if is_admin(uid) else "moder"
    await update.message.reply_text(
        f"Рассылка завершена. Отправлено: {sent}, не удалось: {failed}",
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
        label = f"{p['title']} — ⭐{p['price_stars']}"
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
        t("stars_buy_confirm", title=html.escape(pkg['title']), coins=pkg['coins'], stars=pkg['price_stars']),
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
        title=pkg["title"],
        description=t("stars_pkg_desc", coins=pkg['coins']),
        payload=f"coins:{pkg['id']}",
        provider_token="",       # пусто = Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(pkg["title"], pkg["price_stars"])],
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
        conn.execute("INSERT INTO star_packages (title, coins, price_stars) VALUES (?, ?, ?)",
                     (item["title"], item["coins"], int(text)))
        conn.commit()
        context.user_data["state"] = "star_admin"
        await update.message.reply_text(
            "✅ Пакет добавлен! Теперь у пользователей появилась кнопка «💎 Купить коины».",
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
    reward = 50 if is_vip(inviter) else 20
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


async def show_referral(update, context):
    uid = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"t.me/{bot_username}?start=ref_{uid}"
    total = conn.execute("SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)).fetchone()["c"]
    earned = conn.execute("SELECT COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE referrer_id=? AND active=1", (uid,)).fetchone()["s"]
    vip = is_vip(get_user(uid))
    reward = 50 if vip else 20
    bonus = t("referral_bonus_vip") if vip else t("referral_bonus_normal")
    text = t(
        "referral_screen",
        reward=reward, bonus=bonus, total=total, earned=earned,
        link=html.escape(link),
    )
    context.user_data["state"] = "referral"
    await nav(update, context, text, referral_kb(), parse_mode="HTML")


def referral_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🏆 Топ пригласивших")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


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
    await update.message.reply_text(t("choose_action"), reply_markup=referral_kb())


async def show_top(update, context):
    rows = conn.execute(
        "SELECT referrer_id, COUNT(*) c, COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE active=1 "
        "GROUP BY referrer_id ORDER BY c DESC, s DESC LIMIT 10"
    ).fetchall()
    if not rows:
        await nav(update, context, t("top_empty"), referral_kb())
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
    if state in ("set_gender_first", "set_gender_profile"):
        await set_gender_from_text(update, context)
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
    if state in ("shop_add_title", "shop_add_price", "shop_add_reward", "shop_add_amount", "shop_add_days"):
        await process_shop_add(update, context)
        return
    if state in ("shop_edit_name", "shop_edit_price", "shop_edit_amount", "shop_edit_days"):
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
    if state == "admin_moder":
        await admin_moder_router(update, context)
        return
    if state and state.startswith("adm_coins_"):
        await process_adm_coins_wizard(update, context)
        return
    if state == "adm_channel_add":
        await process_adm_channel_wizard(update, context)
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
            await update.message.reply_text("Введи tg_id пользователя:", reply_markup=cancel_reply_kb())
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
    # Главное меню — навигация доступна из любого раздела
    if text == "🔗 Моя ссылка":
        await show_link_menu(update, context)
        return
    if text == "🎲 Чат-рулетка":
        await show_roulette_entry(update, context)
        return
    if text == "👤 Профиль":
        await show_profile(update, context)
        return
    if text == "🛒 Магазин":
        context.user_data["state"] = None
        await show_shop(update, context)
        return
    if text == "💎 Купить коины":
        await show_star_shop(update, context)
        return
    if text == "👥 Пригласить":
        await show_referral(update, context)
        return
    if text == "ℹ️ Помощь":
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
    set_cur_lang(get_lang(user.id) if user else "ru")
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


# Карта callback-хендлеров: (ключ, функция, точное_совпадение)
_CALLBACKS = [
    ("back_main", on_back_main, True),
    ("reply:", on_reply_button, False),
    ("del:", on_delete_button, False),
    ("subcheck:", on_subcheck_button, False),
    ("report_anon:", on_report_anon, False),
    ("reveal:", on_reveal_button, False),
    ("reveal_pay:", on_reveal_pay, False),
    ("reveal_cancel", on_reveal_cancel, True),
    ("repadm:", on_report_admin_decision, False),
    ("roulette_cancel", on_roulette_cancel, True),
    ("roulette_next", on_roulette_next, True),
    ("roulette_stop", on_roulette_stop, True),
    ("roulette_research", on_roulette_research, True),
    ("rrep:", on_roulette_report, False),
    ("modapp:", on_moder_app_decision, False),
]


def _make_cb_handler(fn):
    async def _handler(cq: CallbackQuery):
        await fn(_cu(cq), Ctx(cq.from_user.id))
    return _handler


def register_handlers():
    dp.update.outer_middleware(_lang_middleware)
    dp.errors.register(on_error)

    dp.message.register(_h_start, CommandStart())
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
    log.info("Бот запущен, поллинг...")
    await dp.start_polling(bot)


def main():
    # фоновый веб-сервер СНАЧАЛА (Render ждёт открытый PORT чтобы считать сервис живым)
    threading.Thread(target=_keep_alive_server, daemon=True).start()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
