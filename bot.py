# ===================== БЛОК 1 / 14 — ИМПОРТЫ, ENV, БД =====================
"""
𐌽ꤕ𐌗ተ — анонимный Telegram-бот.
Anon + Chat-Roulette + Nearby + Shop + Stars + Admin.
Стек: aiogram v3, SQLite / PostgreSQL (Neon).
"""
from __future__ import annotations

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
import time as _time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramConflictError,
    TelegramForbiddenError,
)
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ChatMemberUpdated,
    PreCheckoutQuery,
    ErrorEvent,
    ReplyKeyboardRemove,
    ReplyParameters,
    BufferedInputFile,
    BotCommand,
    InputMediaPhoto,
    KeyboardButton as _AiKeyboardButton,
    ReplyKeyboardMarkup as _AiReplyKeyboardMarkup,
    InlineKeyboardButton as _AiInlineKeyboardButton,
    InlineKeyboardMarkup as _AiInlineKeyboardMarkup,
    LabeledPrice as _AiLabeledPrice,
)

TelegramError = TelegramAPIError


# ============================ ЛОГИРОВАНИЕ ============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("anon_bot")
boot = logging.getLogger("anon_bot.boot")


# ============================ ENV ============================
load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN", "") or "").strip()
ADMIN_IDS = {
    int(x) for x in (os.getenv("ADMIN_IDS", "") or "").split(",") if x.strip().isdigit()
}

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    boot.critical("=" * 60)
    boot.critical("❌ BOT_TOKEN не задан или имеет неверный формат.")
    boot.critical("   Локально: cp .env.example .env → впиши токен")
    boot.critical("   Render: Dashboard → Environment → Add BOT_TOKEN")
    boot.critical("=" * 60)
    raise SystemExit(1)

if not ADMIN_IDS:
    boot.warning("⚠️ ADMIN_IDS пустой — админ-панель недоступна.")
    boot.warning("   Узнать свой ID: @userinfobot")

boot.info("✅ BOT_TOKEN получен (bot_id=%s)", BOT_TOKEN.split(":", 1)[0])
boot.info("✅ Админов: %d", len(ADMIN_IDS))

# Первый админ (главный) — используется для возврата Stars
SUPER_ADMIN_ID = min(ADMIN_IDS) if ADMIN_IDS else 0


# ============================ ЯЗЫК ============================
_lang_var = contextvars.ContextVar("cur_lang", default="ru")


def cur_lang() -> str:
    return _lang_var.get()


def set_cur_lang(value: str) -> None:
    _lang_var.set(value)


# ===================== PTB-СОВМЕСТИМЫЕ ОБЁРТКИ =====================
def KeyboardButton(text, **kw):
    return _AiKeyboardButton(text=text, **kw)


class ReplyKeyboardMarkup(_AiReplyKeyboardMarkup):
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


# ============================ ДВИЖОК ============================
bot = Bot(BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()

_HTML_TAG_RE = re.compile(
    r'<(b|i|u|s|code|pre|a|blockquote|tg-emoji|span|strong|em)[\s>/]',
    re.IGNORECASE,
)


def _needs_html(text):
    return isinstance(text, str) and bool(_HTML_TAG_RE.search(text))


class _BotProxy:
    def __init__(self, real_bot):
        self._bot = real_bot

    def __getattr__(self, name):
        return getattr(self._bot, name)

    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        if reply_to_message_id is not None:
            kw["reply_parameters"] = ReplyParameters(message_id=reply_to_message_id)
        if kw.get("parse_mode") is None and _needs_html(text):
            kw["parse_mode"] = "HTML"
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
UD = defaultdict(dict)


def ud(uid):
    return UD[uid]


class _Msg:
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
        if parse_mode is None and _needs_html(text):
            parse_mode = "HTML"
        return await self._m.answer(
            text, reply_markup=reply_markup, parse_mode=parse_mode, **kw
        )

    async def delete(self):
        return await self._m.delete()


class _CB:
    def __init__(self, cq):
        self._cq = cq
        self.data = cq.data
        self.from_user = cq.from_user
        self.message = _Msg(cq.message) if cq.message else None

    async def answer(self, text=None, show_alert=False, **kw):
        return await self._cq.answer(text=text, show_alert=show_alert, **kw)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        if parse_mode is None and _needs_html(text):
            parse_mode = "HTML"
        return await self._cq.message.edit_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode, **kw
        )

    async def edit_message_caption(self, caption=None, reply_markup=None,
                                   parse_mode=None, **kw):
        if parse_mode is None and _needs_html(caption):
            parse_mode = "HTML"
        return await self._cq.message.edit_caption(
            caption=caption, reply_markup=reply_markup, parse_mode=parse_mode, **kw
        )


class UpdateShim:
    def __init__(self, message=None, callback_query=None, pre_checkout_query=None,
                 my_chat_member=None, effective_user=None, effective_chat=None):
        self.message = _Msg(message) if message is not None else None
        self.callback_query = callback_query
        self.pre_checkout_query = pre_checkout_query
        self.my_chat_member = my_chat_member
        self.effective_user = effective_user
        self.effective_chat = effective_chat


Update = UpdateShim


class ContextTypes:
    DEFAULT_TYPE = object


class Ctx:
    def __init__(self, uid, args=None, error=None):
        self.bot = BOTP
        self._uid = uid
        self.user_data = UD[uid]
        self.args = args or []
        self.error = error


# ============================ КОНСТАНТЫ ============================
DB_PATH = (
    os.getenv("DB_PATH", "").strip()
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
)

DAILY_LIMIT = 20
BAN_DAYS = 7
ROULETTE_BAN_DAYS = 30
ANON_BAN_FOREVER = "9999-12-31T23:59:59"
ROULETTE_TICK_SECONDS = 3
SEARCH_TIMEOUT_MIN = 30
SEARCH_REMIND_MIN = 5
LINK_CHANGE_COOLDOWN_DAYS = 3
LINK_OLD_TTL_HOURS = 24
VIP_DISCOUNT_PERCENT = 20
VIP_DAILY_BONUS = 5
WELCOME_COOLDOWN_MIN = 10

# Рефералы
REF_REWARD_NORMAL = 50
REF_REWARD_VIP = 100
REF_INVITED_BONUS = 100
REF_INVITED_BONUS_VIP = 200
REF_VIP_THRESHOLD = 5
REF_VIP_DAYS = 7
REF_MODER_THRESHOLD = 10
REF_MODER_DAYS = 7
LINK_REWARD_EVERY = 10
LINK_REWARD_COINS = 20

# Возврат Stars
STARS_REFUND_PERCENT = 50

CREATOR_USERNAME = "@ToxIc_0707"

# Джанитор
INACTIVE_DAYS = 14
JANITOR_WAKE_HOURS = 6
JANITOR_PERIOD_DAYS = 14


def _safe(func, *args, default=None):
    try:
        return func(*args)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        return default


# ============================ БД ============================
DATABASE_URL = (
    os.getenv("DATABASE_URL", "").strip()
    or os.getenv("POSTGRES_URL", "").strip()
    or os.getenv("NEON_DATABASE_URL", "").strip()
)
USE_PG = bool(DATABASE_URL)


if USE_PG:
    import psycopg2

    _pg_lock = threading.RLock()

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
            try:
                self._rows = raw.fetchall() if raw.description else []
            except Exception:
                self._rows = []
            self._pos = 0
            self._lastrowid = None
            if self._rows and "id" in self._cols:
                self._lastrowid = self._rows[0][self._cols.index("id")]

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

    def _translate_schema(script):
        s = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        s = re.sub(r"\bINTEGER\b", "BIGINT", s)
        return s

    class _PgConnection:
        def __init__(self, url):
            self.url = url
            self._conn = None
            self._connect()

        def _connect(self):
            last_err = None
            for attempt in range(1, 6):
                try:
                    self._conn = psycopg2.connect(
                        self.url,
                        connect_timeout=15,
                        keepalives=1,
                        keepalives_idle=30,
                        keepalives_interval=10,
                        keepalives_count=5,
                    )
                    self._conn.autocommit = True
                    if attempt > 1:
                        boot.info("PG подключился с попытки %d", attempt)
                    return
                except psycopg2.OperationalError as e:
                    last_err = e
                    if attempt < 5:
                        boot.warning("PG connect %d/5: %s", attempt, e)
                        _time.sleep(2 ** attempt)
            boot.critical("❌ Не удалось подключиться к PostgreSQL: %s", last_err)
            boot.critical("   Проверь DATABASE_URL (нужен ?sslmode=require)")
            raise SystemExit(1)

        def execute(self, sql, params=()):
            q = sql.replace("?", "%s")
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
                        self._connect()

        def executescript(self, script):
            with _pg_lock:
                cur = self._conn.cursor()
                cur.execute(_translate_schema(script))
                return _PgCursor(cur)

        def commit(self):
            pass

        def rollback(self):
            try:
                self._conn.rollback()
            except Exception:
                pass

        def cursor(self):
            return self

    conn = _PgConnection(DATABASE_URL)
    boot.info("🗄 База данных: PostgreSQL")

else:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-16000")
    except Exception as _e:
        boot.warning("SQLite pragma: %s", _e)
    boot.info("🗄 База данных: SQLite (%s)", DB_PATH)


def db():
    return conn
# ===================== БЛОК 2 / 14 — СХЕМА БД =====================

def init_db():
    """Создаёт все таблицы. Безопасно для повторного вызова."""
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        gender TEXT,
        search_pref TEXT,
        custom_link TEXT UNIQUE,
        old_link TEXT,
        old_link_until TEXT,
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
        ref_code TEXT,
        last_greet TEXT,
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
        title_uz TEXT,
        title_en TEXT,
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
        title TEXT,
        added_by INTEGER
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
        refunded INTEGER NOT NULL DEFAULT 0,
        refunded_at TEXT,
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
    CREATE TABLE IF NOT EXISTS link_flow (
        user_id INTEGER PRIMARY KEY,
        target_id INTEGER NOT NULL,
        msg_type TEXT,
        state TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    -- ============ ПОБЛИЗОСТИ ============
    CREATE TABLE IF NOT EXISTS nearby_profiles (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        age INTEGER,
        gender TEXT,
        looking_for TEXT,
        bio TEXT,
        photo_id TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS nearby_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS nearby_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user1_id, user2_id)
    );

    -- ============ /sex — комнаты для девушек ============
    CREATE TABLE IF NOT EXISTS sex_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        owner_id INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sex_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        number INTEGER NOT NULL,
        joined_at TEXT NOT NULL,
        UNIQUE(room_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS sex_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        sender_number INTEGER NOT NULL,
        content_type TEXT NOT NULL,
        text TEXT,
        voice_file_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sex_exit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        UNIQUE(room_id, user_id)
    );

    -- ============ /anon — наблюдение ============
    CREATE TABLE IF NOT EXISTS anon_watchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mod_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        UNIQUE(mod_id, target_id)
    );
    """)
    conn.commit()
    migrate()
    ensure_indexes()


def migrate():
    """Безопасно добавляет недостающие колонки."""
    alters = [
        "ALTER TABLE users ADD COLUMN first_name TEXT",
        "ALTER TABLE users ADD COLUMN is_moder INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_bonus TEXT",
        "ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT 'ru'",
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
        "ALTER TABLE users ADD COLUMN ref_code TEXT",
        "ALTER TABLE users ADD COLUMN old_link TEXT",
        "ALTER TABLE users ADD COLUMN old_link_until TEXT",
        "ALTER TABLE users ADD COLUMN last_greet TEXT",
        "ALTER TABLE anon_messages ADD COLUMN parent_id INTEGER",
        "ALTER TABLE shop_items ADD COLUMN reward_type TEXT NOT NULL DEFAULT 'manual'",
        "ALTER TABLE shop_items ADD COLUMN reward_amount INTEGER",
        "ALTER TABLE shop_items ADD COLUMN title_uz TEXT",
        "ALTER TABLE shop_items ADD COLUMN title_en TEXT",
        "ALTER TABLE mandatory_channels ADD COLUMN title TEXT",
        "ALTER TABLE mandatory_channels ADD COLUMN added_by INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE roulette_sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE star_packages ADD COLUMN title_uz TEXT",
        "ALTER TABLE star_packages ADD COLUMN title_en TEXT",
        "ALTER TABLE star_purchases ADD COLUMN refunded INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE star_purchases ADD COLUMN refunded_at TEXT",
    ]
    for sql in alters:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    conn.commit()


def ensure_indexes():
    """Индексы для горячих запросов."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u1 ON roulette_sessions(active, user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u2 ON roulette_sessions(active, user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_to ON anon_messages(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_from ON anon_messages(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_parent ON anon_messages(parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
        "CREATE INDEX IF NOT EXISTS idx_bans_pair ON bans(owner_id, banned_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_banned ON bans(banned_id)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
        "CREATE INDEX IF NOT EXISTS idx_starpur_user ON star_purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_refcode ON users(ref_code)",
        "CREATE INDEX IF NOT EXISTS idx_users_lastactive ON users(last_active)",
        "CREATE INDEX IF NOT EXISTS idx_users_oldlink ON users(old_link)",
        "CREATE INDEX IF NOT EXISTS idx_moderapps_status ON moder_apps(status)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_likes_from ON nearby_likes(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_likes_to ON nearby_likes(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_match_u1 ON nearby_matches(user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_match_u2 ON nearby_matches(user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_sex_members_room ON sex_members(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_sex_messages_room ON sex_messages(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_watchers_target ON anon_watchers(target_id)",
    ]
    for q in indexes:
        try:
            conn.execute(q)
        except Exception as e:
            log.warning("index skip: %s (%s)", q.split(" ON ")[0], e)
    conn.commit()
    log.info("🗄 Индексы готовы")


# ============================ ВРЕМЯ ============================
def now_iso() -> str:
    return datetime.utcnow().isoformat()


def now_dt() -> datetime:
    return datetime.utcnow()


# ============================ НАСТРОЙКИ ============================
def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    except Exception:
        return default
    return row["value"] if row and row["value"] is not None else default


def get_setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value) -> None:
    conn.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()


def cfg_vip_days():        return get_setting_int("ref_vip_days", REF_VIP_DAYS)
def cfg_vip_threshold():   return max(1, get_setting_int("ref_vip_threshold", REF_VIP_THRESHOLD))
def cfg_moder_days():      return get_setting_int("ref_moder_days", REF_MODER_DAYS)
def cfg_moder_threshold(): return max(1, get_setting_int("ref_moder_threshold", REF_MODER_THRESHOLD))


# ============================ ПОЛЬЗОВАТЕЛИ ============================
UserRow = sqlite3.Row | dict | None


def get_user(tg_id: int) -> UserRow:
    return conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def ensure_user(tg_id: int, username: str | None, first_name: str | None = None) -> UserRow:
    u = get_user(tg_id)
    if u is None:
        conn.execute(
            "INSERT INTO users (tg_id, username, first_name, coins, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (tg_id, username, first_name, now_iso()),
        )
        conn.commit()
        return get_user(tg_id)

    changed = False
    if u["username"] != username:
        conn.execute("UPDATE users SET username=? WHERE tg_id=?", (username, tg_id))
        changed = True
    if first_name and u["first_name"] != first_name:
        conn.execute("UPDATE users SET first_name=? WHERE tg_id=?", (first_name, tg_id))
        changed = True
    if changed:
        conn.commit()
        u = get_user(tg_id)
    return u


def touch_user(uid: int) -> None:
    """Отмечает активность. Пишем не чаще раза в час."""
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
    except Exception as e:
        log.debug("touch_user(%s): %s", uid, e)


def resolve_user_ref(text: str | None) -> int | None:
    """Ищет пользователя по tg_id или @username."""
    if not text:
        return None
    s = text.strip()
    if s.isdigit():
        u = get_user(int(s))
        return u["tg_id"] if u else None
    uname = s.lstrip("@").strip().lower()
    if not uname:
        return None
    row = conn.execute("SELECT tg_id FROM users WHERE LOWER(username)=?", (uname,)).fetchone()
    return row["tg_id"] if row else None


# ============================ РОЛИ ============================
def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


def is_super_admin(tg_id: int) -> bool:
    return tg_id == SUPER_ADMIN_ID


def is_moder(user_row: UserRow) -> bool:
    if not user_row:
        return False
    if user_row["is_moder"]:
        return True
    try:
        mu = user_row["moder_until"]
        if mu and datetime.fromisoformat(mu) > now_dt():
            return True
    except (KeyError, IndexError, ValueError, TypeError):
        pass
    return False


def is_staff(tg_id: int) -> bool:
    if is_admin(tg_id):
        return True
    return is_moder(get_user(tg_id))


def is_banned(user_row: UserRow) -> bool:
    return bool(user_row) and bool(user_row["is_banned"])


def is_vip(user_row: UserRow) -> bool:
    if not user_row:
        return False
    try:
        if is_admin(user_row["tg_id"]) or is_moder(user_row):
            return True
    except (KeyError, TypeError):
        pass
    if not user_row["vip_until"]:
        return False
    try:
        return datetime.fromisoformat(user_row["vip_until"]) > now_dt()
    except (ValueError, TypeError):
        return False


def is_unlimited(user_row: UserRow) -> bool:
    if not user_row:
        return False
    try:
        return is_admin(user_row["tg_id"]) or is_moder(user_row)
    except (KeyError, TypeError):
        return False


def user_age_int(user_row: UserRow) -> int | None:
    try:
        a = user_row["age"]
    except (KeyError, IndexError, TypeError):
        return None
    if a is None:
        return None
    s = str(a).strip()
    return int(s) if s.isdigit() else None


# ============================ ЦЕНА ============================
def effective_price(price: int, user_row: UserRow) -> int:
    if is_unlimited(user_row):
        return 0
    if is_vip(user_row):
        return max(0, round(price * (100 - VIP_DISCOUNT_PERCENT) / 100))
    return price


# ============================ УТИЛИТЫ ============================
def gender_label(code: str | None) -> str:
    return {
        "m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
        "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"},
    }.get(code, {}).get(cur_lang(), "—")


def pref_label(code: str | None) -> str:
    return {
        "m": {"ru": "Парня", "uz": "Yigit", "en": "A guy"},
        "f": {"ru": "Девушку", "uz": "Qiz", "en": "A girl"},
        "any": {"ru": "Любого", "uz": "Farqi yo'q", "en": "Anyone"},
    }.get(code, {}).get(cur_lang(), "—")


def user_mention(user_row: UserRow) -> str:
    if not user_row:
        return "—"
    name = user_row["first_name"] or "пользователь"
    if user_row["username"]:
        return f"{name} (@{user_row['username']})"
    return f'<a href="tg://user?id={user_row["tg_id"]}">{html.escape(name)}</a> (ID: {user_row["tg_id"]})'


def fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    lang = cur_lang()
    hu = {"ru": "ч", "uz": "soat", "en": "h"}.get(lang, "h")
    mu = {"ru": "мин", "uz": "daq", "en": "min"}.get(lang, "min")
    if h > 0:
        return f"{h} {hu} {m} {mu}"
    return f"{m} {mu}"


async def try_delete_message(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
    except TelegramError as e:
        log.debug("try_delete_message(%s, %s): %s", chat_id, message_id, e)


def has_forbidden_contacts(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    if re.search(r'@[a-z][a-z0-9_]{2,}', low):
        return True
    if re.search(r'https?://|www\.|t\.me|telegram\.me|telegram\.dog|joinchat|tg://', low):
        return True
    if re.search(
        r'\b[a-z0-9][a-z0-9-]*\.(com|ru|uz|net|org|io|me|info|biz|tv|app|link|site|online|club|store|xyz|kz)\b',
        low,
    ):
        return True
    if re.search(
        r'\b(instagram|insta|tiktok|youtube|youtu|whatsapp|watsap|vatsap|'
        r'facebook|snapchat|discord|onlyfans|vkontakte|тикток|инстаграм|ютуб|ватсап|вотсап)\b',
        low,
    ):
        return True
    for m in re.finditer(r'[\d\s\-()+]{7,}', text):
        if sum(c.isdigit() for c in m.group()) >= 7:
            return True
    return False
    # ===================== БЛОК 3 / 14 — ЯЗЫКИ (BTN + tr) =====================
LANGS = ("ru", "uz", "en")
LANG_BUTTONS = {"Русский": "ru", "O'zbekcha": "uz", "English": "en"}

BTN = {
    "🔗 Моя ссылка": ("🔗 Havolam", "🔗 My link"),
    "🎲 Чат-рулетка": ("🎲 Chat-ruletka", "🎲 Chat roulette"),
    "📍 Поблизости": ("📍 Yaqin-atrofda", "📍 Nearby"),
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
    "👑 VIP всем": ("👑 Hammaga VIP", "👑 VIP to all"),
    "👑 VIP девушкам": ("👑 Qizlarga VIP", "👑 VIP to girls"),
    "👑 VIP парням": ("👑 Yigitlarga VIP", "👑 VIP to guys"),
    "➕ Выдать VIP всем": ("➕ Hammaga VIP berish", "➕ Grant VIP to all"),
    "➖ Забрать у всех": ("➖ Hammadan olish", "➖ Revoke from all"),
    "➕ Выдать VIP девушкам": ("➕ Qizlarga VIP berish", "➕ Grant VIP to girls"),
    "➖ Забрать у девушек": ("➖ Qizlardan olish", "➖ Revoke from girls"),
    "➕ Выдать VIP парням": ("➕ Yigitlarga VIP berish", "➕ Grant VIP to guys"),
    "➖ Забрать у парней": ("➖ Yigitlardan olish", "➖ Revoke from guys"),
    "📤 Выгрузить пользователей": ("📤 Foydalanuvchilarni yuklash", "📤 Export users"),
    "💰 Начислить коины": ("💰 Coin qo'shish", "💰 Add coins"),
    "📢 Обязательные каналы": ("📢 Majburiy kanallar", "📢 Required channels"),
    "➕ Добавить канал": ("➕ Kanal qo'shish", "➕ Add channel"),
    "🗑 Удалить канал": ("🗑 Kanalni o'chirish", "🗑 Delete channel"),
    "💾 Сохранить": ("💾 Saqlash", "💾 Save"),
    "✅ Сохранить": ("✅ Saqlash", "✅ Save"),
    "📣 Реклама": ("📣 Reklama", "📣 Ad"),
    "✉️ Рассылка": ("✉️ Xabar tarqatish", "✉️ Broadcast"),
    "📢 Рассылка": ("📢 Xabar tarqatish", "📢 Broadcast"),
    "🛡 Модеры": ("🛡 Moderatorlar", "🛡 Moderators"),
    "🔒 Отозвать доступ": ("🔒 Kirishni bekor qilish", "🔒 Revoke access"),
    "🔨 Бан / Разбан": ("🔨 Ban / Unban", "🔨 Ban / Unban"),
    "⭐ Коины за Stars": ("⭐ Stars uchun coin", "⭐ Coins for Stars"),
    "⭐ Возврат Stars": ("⭐ Stars qaytarish", "⭐ Refund Stars"),
    "💎 Цена раскрытия": ("💎 Ochish narxi", "💎 Reveal price"),
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
    "🎁 Подарить коины": ("🎁 Coin sovg'a qilish", "🎁 Gift coins"),
    "✅ Согласиться": ("✅ Roziman", "✅ I agree"),
    "✅ Подтвердить": ("✅ Tasdiqlash", "✅ Confirm"),
    "❌ Отклонить": ("❌ Rad etish", "❌ Reject"),
    "✏️ Изменить возраст": ("✏️ Yoshni o'zgartirish", "✏️ Change age"),
    "🚪 Выйти": ("🚪 Chiqish", "🚪 Exit"),
    # Поблизости
    "🔍 Смотреть анкеты": ("🔍 Anketalarni ko'rish", "🔍 Browse profiles"),
    "💕 Мои мэтчи": ("💕 Mening matchlarim", "💕 My matches"),
    "✏️ Редактировать анкету": ("✏️ Anketani tahrirlash", "✏️ Edit profile"),
    "📷 Отправить фото": ("📷 Foto yuborish", "📷 Send photo"),
    # /sex
    "💬 Комната": ("💬 Xona", "💬 Room"),
    "👥 Участники": ("👥 Ishtirokchilar", "👥 Members"),
    "🚪 Запросить выход": ("🚪 Chiqishni so'rash", "🚪 Request exit"),
    "🛡 Одобрить выход": ("🛡 Chiqishni tasdiqlash", "🛡 Approve exit"),
    "🗑 Удалить комнату": ("🗑 Xonani o'chirish", "🗑 Delete room"),
    "✏️ Переименовать": ("✏️ Nomini o'zgartirish", "✏️ Rename"),
}


def _strip_emoji_prefix(s: str) -> str:
    if not isinstance(s, str):
        return s
    return re.sub(
        r'^[\U0001F000-\U0001FFFF'
        r'\u2300-\u2BFF'
        r'\u3030\u303D\u3297\u3299'
        r'\u00A9\u00AE\u203C\u2049\u20E3\u2122\u2139'
        r'\u2190-\u21FF'
        r'\u2702\u2705\u2708-\u270D\u270F\u2712\u2714\u2716'
        r'\u271D\u2721\u2728\u2733\u2734\u2744\u2747'
        r'\u274C\u274E\u2753-\u2755\u2757\u2763\u2764'
        r'\u2795-\u2797\u27A1\u27B0\u27BF\u2934\u2935'
        r'\u2B00-\u2BFF'
        r'\uFE0F\u200D'
        r']+[\uFE0F]?\s*',
        '', s,
    )


_ALIAS = {}
for _ru, (_uz, _en) in BTN.items():
    _canonical = _strip_emoji_prefix(_ru)
    _ALIAS[_ru] = _canonical
    _ALIAS[_uz] = _canonical
    _ALIAS[_en] = _canonical


def canon(text: str | None) -> str | None:
    if text is None:
        return None
    t = text.strip()
    hit = _ALIAS.get(t) or _ALIAS.get(text)
    if hit:
        return hit
    stripped = _strip_emoji_prefix(t)
    return _ALIAS.get(stripped, stripped)


def styled(text, kind="default"):
    return text


def tr_btn(ru_label: str, lang: str | None = None, kind: str = "default") -> str:
    lang = lang or cur_lang()
    if lang == "ru":
        base = ru_label
    else:
        pair = BTN.get(ru_label)
        base = ru_label if not pair else (pair[0] if lang == "uz" else pair[1])
    return styled(base, kind) if kind != "default" else base


def tr_kb(markup, lang=None):
    lang = lang or cur_lang()
    if not isinstance(markup, ReplyKeyboardMarkup):
        return markup
    new_rows = []
    for row in markup.keyboard:
        new_row = []
        for b in row:
            txt = b.text
            if lang == "ru":
                new_row.append(KeyboardButton(txt))
            else:
                pair = BTN.get(txt)
                if pair:
                    new_row.append(KeyboardButton(pair[0] if lang == "uz" else pair[1]))
                else:
                    new_row.append(KeyboardButton(txt))
        new_rows.append(new_row)
    return ReplyKeyboardMarkup(
        new_rows,
        resize_keyboard=markup.resize_keyboard,
        one_time_keyboard=markup.one_time_keyboard,
    )


def get_lang(uid: int) -> str:
    try:
        u = get_user(uid)
        if u and u["lang"] in LANGS:
            return u["lang"]
    except (KeyError, TypeError):
        pass
    return "ru"


def set_lang(uid: int, lang: str) -> None:
    conn.execute("UPDATE users SET lang=? WHERE tg_id=?", (lang, uid))
    conn.commit()


# ===================== АВТОПЕРЕНОС ЭМОДЗИ =====================
_LEADING_EMOJI_RE = re.compile(
    r'^([\U0001F000-\U0001FFFF'
    r'\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF'
    r'\u25A0-\u27BF\u2B00-\u2BFF'
    r'\u3030\u303D\u3297\u3299'
    r'\uFE0F\u200D\u20E3]+)'
)


def _leading_emoji(s):
    if not isinstance(s, str) or not s:
        return ""
    m = _LEADING_EMOJI_RE.match(s)
    return m.group(1) if m else ""
    # ===================== БЛОК 4 / 14 — СЛОВАРЬ T (часть 1) =====================
T = {
    # ============================ ГЛАВНОЕ ============================
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
    "banned": {
        "ru": "🚫 Вы заблокированы и не можете пользоваться ботом.",
        "uz": "🚫 Siz bloklangansiz va botdan foydalana olmaysiz.",
        "en": "🚫 You are blocked and cannot use the bot.",
    },
    "done": {"ru": "✅ Готово!", "uz": "✅ Tayyor!", "en": "✅ Done!"},
    "enter_number": {"ru": "🔢 Введите число:", "uz": "🔢 Raqam kiriting:", "en": "🔢 Enter a number:"},
    "enter_days": {"ru": "📅 Введите число дней:", "uz": "📅 Kunlar sonini kiriting:", "en": "📅 Enter the number of days:"},
    "choose_on_kb": {"ru": "👇 Выберите", "uz": "👇 Tanlang", "en": "👇 Choose"},
    "cancelled": {"ru": "Отменено.", "uz": "Bekor qilindi.", "en": "Cancelled."},

    # ============================ ЯЗЫК ============================
    "lang_choose": {
        "ru": "🌐 Выберите язык интерфейса:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Choose the interface language:",
    },
    "lang_set": {
        "ru": "🌐 Язык изменён на Русский ✅\n\nГлавное меню",
        "uz": "🌐 Til O'zbekchaga o'zgartirildi ✅\n\nAsosiy menyu",
        "en": "🌐 Language changed to English ✅\n\nMain menu",
    },

    # ============================ ПРИВЕТСТВИЕ ============================
    "welcome": {
        "ru": (
            "🔥 <b>Привет, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Добро пожаловать в <b>𐌽ꤕ𐌗ተ</b> — место, где говорят честно и анонимно 🕶\n\n"
            "<blockquote>🔗 Получай анонимки по своей ссылке\n"
            "🎲 Чат-рулетка — новые знакомства каждый раз\n"
            "📍 Поблизости — анкеты и мэтчи\n"
            "🤐 Полная анонимность — никто не знает, кто ты\n"
            "💎 VIP, коины и бонусы за приглашённых друзей</blockquote>\n\n"
            "👇 <b>Первый шаг — выбери свой пол</b>"
        ),
        "uz": (
            "🔥 <b>Salom, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Xush kelibsiz <b>𐌽ꤕ𐌗ተ</b> ga 🕶\n\n"
            "<blockquote>🔗 Havolangiz orqali anonim xabar oling\n"
            "🎲 Chat-ruletka — yangi tanishuvlar\n"
            "📍 Yaqin-atrofda — anketalar va matchlar\n"
            "🤐 To'liq anonimlik\n"
            "💎 VIP, coinlar va bonuslar</blockquote>\n\n"
            "👇 <b>Birinchi qadam — jinsingizni tanlang</b>"
        ),
        "en": (
            "🔥 <b>Hi, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome to <b>𐌽ꤕ𐌗ተ</b> — speak freely and anonymously 🕶\n\n"
            "<blockquote>🔗 Get anonymous messages via your link\n"
            "🎲 Chat roulette — new people every time\n"
            "📍 Nearby — profiles and matches\n"
            "🤐 Full anonymity\n"
            "💎 VIP, coins and bonuses for inviting friends</blockquote>\n\n"
            "👇 <b>First step — choose your gender</b>"
        ),
    },
    "welcome_back": {
        "ru": (
            "🎉 <b>С возвращением, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Снова рады видеть тебя в <b>𐌽ꤕ𐌗ተ</b> 💫\n\n"
            "<blockquote>🔗 Делись ссылкой — получай анонимки\n"
            "🎲 Прыгай в чат-рулетку\n"
            "👥 Зови друзей — получай бонусы\n"
            "🛒 Загляни в магазин</blockquote>\n\n"
            "🏠 Главное меню"
        ),
        "uz": (
            "🎉 <b>Qaytganingiz bilan, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Sizni yana ko'rganimizdan xursandmiz 💫\n\n"
            "<blockquote>🔗 Havolani ulashing\n"
            "🎲 Chat-ruletkaga kiring\n"
            "👥 Do'stlarni chaqiring\n"
            "🛒 Do'konni ko'rib chiqing</blockquote>\n\n"
            "🏠 Asosiy menyu"
        ),
        "en": (
            "🎉 <b>Welcome back, {name}!</b> 👋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Great to see you again 💫\n\n"
            "<blockquote>🔗 Share your link\n"
            "🎲 Jump into chat roulette\n"
            "👥 Invite friends\n"
            "🛒 Check the shop</blockquote>\n\n"
            "🏠 Main menu"
        ),
    },

    # ============================ ПОМОЩЬ ============================
    "help": {
        "ru": (
            "ℹ️ <b>ПОМОЩЬ — ВСЁ О БОТЕ 𐌽ꤕ𐌗ተ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Полное описание всех функций и кнопок</i>\n\n"

            "<b>🔗 МОЯ ССЫЛКА</b>\n"
            "<blockquote>"
            "Твоя личная ссылка для анонимных сообщений.\n"
            "• <b>«Показать ссылку»</b> — показывает ссылку + кнопку «Поделиться»\n"
            "• <b>«Сменить ссылку»</b> — меняет код ссылки. "
            "Обычным раз в <b>3 дня</b>, VIP — <b>без ограничений</b>.\n"
            "• После смены старая ссылка работает <b>ещё 1 день</b>.\n"
            "• Слать можно: ❓ Вопрос, 💌 Валентинку — текст или голос.\n"
            "• VIP может слать фото, стикеры, гиф, видео."
            "</blockquote>\n\n"

            "<b>🎲 ЧАТ-РУЛЕТКА</b>\n"
            "<blockquote>"
            "Случайный собеседник по полу.\n"
            "• Жми <b>«Чат-рулетка»</b> → выбери кого ищешь\n"
            "• Кнопки: <b>«Далее»</b> — следующий, <b>«Стоп»</b> — выйти\n"
            "• VIP находит пару быстрее"
            "</blockquote>\n\n"

            "<b>📍 ПОБЛИЗОСТИ</b>\n"
            "<blockquote>"
            "Анкеты и мэтчи по интересам.\n"
            "• <b>«Смотреть анкеты»</b> — листаешь профили, ставишь ❤️ или 👎\n"
            "• Взаимный ❤️ = <b>мэтч</b> — открывается ЛС собеседника\n"
            "• <b>«Мои мэтчи»</b> — список тех, с кем совпало\n"
            "• <b>«Редактировать анкету»</b> — имя, возраст, пол, о себе, фото"
            "</blockquote>\n\n"

            "<b>👤 ПРОФИЛЬ</b>\n"
            "<blockquote>"
            "Твои данные: ID, имя, пол, возраст, время в рулетке, "
            "анонимки, приглашённые друзья, VIP, коины.\n"
            "• <b>«Сменить пол»</b>\n"
            "• <b>«Изменить возраст»</b>\n"
            "• <b>«Подарить коины»</b> — перевести другу по ID или @username"
            "</blockquote>\n\n"

            "<b>🛒 МАГАЗИН</b>\n"
            "<blockquote>"
            "Тратишь коины:\n"
            "• <b>VIP</b> — премиум на N дней\n"
            "• <b>Коины</b> — пополнение баланса\n"
            "• <b>Модерка</b> — заявка на роль модератора\n\n"
            "VIP видит цены со скидкой <b>−20%</b>."
            "</blockquote>\n\n"

            "<b>👥 ПРИГЛАСИТЬ</b>\n"
            "<blockquote>"
            "• За каждого друга — <b>+50 коинов</b> (VIP — <b>+100</b>)\n"
            "• Друг получает <b>+100</b> за вход\n"
            "• Награды: <b>VIP бесплатно</b> за 5 друзей, <b>Модерка</b> за 10\n"
            "• Внизу — <b>Топ пригласивших</b>\n"
            "• Считаются только друзья, которые <b>создали свою ссылку</b>"
            "</blockquote>\n\n"

            "<b>💎 КУПИТЬ КОИНЫ</b>\n"
            "<blockquote>"
            "Пополнение через <b>Telegram Stars ⭐</b>. Выбираешь пакет → оплата → коины мгновенно."
            "</blockquote>\n\n"

            "<b>🌐 ЯЗЫК</b>\n"
            "<blockquote>🇷🇺 Русский · 🇺🇿 O'zbekcha · 🇬🇧 English</blockquote>\n\n"

            "<b>💎 ЧТО ТАКОЕ КОИНЫ</b>\n"
            "<blockquote>Внутренняя валюта. Зарабатывай за друзей и активность. Трать в магазине.</blockquote>\n\n"

            "<b>👑 ЧТО ДАЁТ VIP</b>\n"
            "<blockquote>"
            "• Анонимки <b>без лимита</b> (обычным — 20/день)\n"
            "• <b>−20%</b> в магазине\n"
            "• <b>+5 коинов</b> ежедневно\n"
            "• Приоритет в рулетке\n"
            "• Фото/видео/стикеры в анонимках\n"
            "• Смена ссылки <b>без ограничений</b>"
            "</blockquote>\n\n"

            "<i>Для безопасности переписки могут проверяться модераторами.</i>"
        ),
        "uz": (
            "ℹ️ <b>YORDAM — 𐌽ꤕ𐌗ተ HAQIDA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🔗 Havolam</b> — anonim xabarlar uchun shaxsiy havola.\n"
            "<b>🎲 Chat-ruletka</b> — tasodifiy suhbatdosh.\n"
            "<b>📍 Yaqin-atrofda</b> — anketalar va matchlar.\n"
            "<b>👤 Profil</b> — ma'lumotlaringiz.\n"
            "<b>🛒 Do'kon</b> — VIP va coinlar.\n"
            "<b>👥 Taklif qilish</b> — do'stlar uchun bonuslar.\n"
            "<b>💎 Coin sotib olish</b> — Stars orqali.\n"
            "<b>🌐 Til</b> — tilni o'zgartirish."
        ),
        "en": (
            "ℹ️ <b>HELP — ALL ABOUT 𐌽ꤕ𐌗ተ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🔗 My link</b> — personal link for anonymous messages.\n"
            "<b>🎲 Chat roulette</b> — random partner.\n"
            "<b>📍 Nearby</b> — profiles and matches.\n"
            "<b>👤 Profile</b> — your data.\n"
            "<b>🛒 Shop</b> — VIP and coins.\n"
            "<b>👥 Invite</b> — referral bonuses.\n"
            "<b>💎 Buy coins</b> — via Telegram Stars.\n"
            "<b>🌐 Language</b> — change language."
        ),
    },

    # ============================ ПРОФИЛЬ ============================
    "profile_full": {
        "ru": (
            "<b>Ваш профиль</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "ID: <code>{id}</code>\n"
            "Имя: <b>{name}</b>\n"
            "Пол: <b>{gender}</b>\n"
            "Возраст: <b>{age}</b>\n"
            "В чат-рулетке: <b>{roulette_time}</b>\n"
            "Отправлено по ссылке: <b>{sent}</b>\n"
            "Получено по ссылке: <b>{received}</b>\n"
            "Приглашено друзей: <b>{invited}</b>\n"
            "Место в топе: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "Коины: <b>{coins}</b>\n"
            "Потрачено звёзд: <b>{stars}</b>\n"
            "Регистрация: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "uz": (
            "<b>Profilingiz</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "ID: <code>{id}</code>\n"
            "Ism: <b>{name}</b>\n"
            "Jins: <b>{gender}</b>\n"
            "Yosh: <b>{age}</b>\n"
            "Chat-ruletkada: <b>{roulette_time}</b>\n"
            "Havola orqali: <b>{sent}</b>\n"
            "Havola orqali kelgan: <b>{received}</b>\n"
            "Do'stlar: <b>{invited}</b>\n"
            "Topda: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "Coinlar: <b>{coins}</b>\n"
            "Yulduzlar: <b>{stars}</b>\n"
            "Ro'yxatdan: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "en": (
            "<b>Your profile</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "ID: <code>{id}</code>\n"
            "Name: <b>{name}</b>\n"
            "Gender: <b>{gender}</b>\n"
            "Age: <b>{age}</b>\n"
            "In roulette: <b>{roulette_time}</b>\n"
            "Sent via link: <b>{sent}</b>\n"
            "Received via link: <b>{received}</b>\n"
            "Friends invited: <b>{invited}</b>\n"
            "Leaderboard: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "Coins: <b>{coins}</b>\n"
            "Stars spent: <b>{stars}</b>\n"
            "Registered: <b>{reg_date}</b>"
            "</blockquote>"
        ),
    },
    "vip_none": {"ru": "—", "uz": "—", "en": "—"},
    "vip_until": {"ru": "до {date}", "uz": "{date} gacha", "en": "until {date}"},
    "vip_forever": {"ru": "навсегда", "uz": "abadiy", "en": "forever"},
    "choose_action": {
        "ru": "Выберите действие на клавиатуре",
        "uz": "Klaviaturadan amalni tanlang",
        "en": "Choose an action on the keyboard",
    },
    "choose_new_gender": {
        "ru": "Выберите новый пол:",
        "uz": "Yangi jinsni tanlang:",
        "en": "Choose new gender:",
    },
    "gender_saved": {
        "ru": "✅ Готово! Ваш пол: <b>{g}</b>\n\nГлавное меню",
        "uz": "✅ Tayyor! Jinsingiz: <b>{g}</b>\n\nAsosiy menyu",
        "en": "✅ Done! Your gender: <b>{g}</b>\n\nMain menu",
    },
    "gender_set_short": {
        "ru": "✅ Пол сохранён: {g}",
        "uz": "✅ Jins saqlandi: {g}",
        "en": "✅ Gender saved: {g}",
    },
    "gender_needed_for_search": {
        "ru": "👤 Для поиска нужно указать пол. Выбери:",
        "uz": "👤 Qidiruv uchun jinsingizni tanlang:",
        "en": "👤 Please select your gender to start searching:",
    },

    # ============================ ВОЗРАСТ ============================
    "age_register_ask": {
        "ru": "<b>Сколько вам лет?</b>\n\nНапишите возраст числом (например: 21).",
        "uz": "<b>Yoshingiz nechada?</b>\n\nYoshingizni raqam bilan yozing (masalan: 21).",
        "en": "<b>How old are you?</b>\n\nType your age as a number (e.g. 21).",
    },
    "age_enter_number": {
        "ru": "Введите ваш возраст числом (например: 21):",
        "uz": "Yoshingizni raqam bilan kiriting (masalan: 21):",
        "en": "Enter your age as a number (e.g. 21):",
    },
    "age_saved": {
        "ru": "Возраст сохранён: <b>{age}</b>\n\nГлавное меню",
        "uz": "Yosh saqlandi: <b>{age}</b>\n\nAsosiy menyu",
        "en": "Age saved: <b>{age}</b>\n\nMain menu",
    },

    # ============================ ПОДАРОК КОИНОВ ============================
    "giftcoins_ask_id": {
        "ru": (
            "<b>Подарить коины другу</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Коины спишутся с твоего баланса и придут другу.\n\n"
            "Введите <b>Telegram ID</b> или <b>@username</b> друга\n"
            "<i>(друг должен быть запущен в боте)</i>"
        ),
        "uz": (
            "<b>Do'stga coin sovg'a qilish</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coinlar balansingizdan yechiladi.\n\n"
            "Do'stning <b>Telegram ID</b> yoki <b>@username</b> ini kiriting"
        ),
        "en": (
            "<b>Gift coins to a friend</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coins are deducted from your balance.\n\n"
            "Enter the friend's <b>Telegram ID</b> or <b>@username</b>"
        ),
    },
    "giftcoins_ask_amount": {
        "ru": "Сколько коинов подарить? (твой баланс: <b>{balance}</b>)",
        "uz": "Qancha coin sovg'a qilasiz? (balansingiz: <b>{balance}</b>)",
        "en": "How many coins to gift? (your balance: <b>{balance}</b>)",
    },
    "giftcoins_amount_number": {
        "ru": "Введите положительное число коинов:",
        "uz": "Musbat coin sonini kiriting:",
        "en": "Enter a positive number of coins:",
    },
    "giftcoins_not_enough": {
        "ru": "Недостаточно коинов. Твой баланс: <b>{balance}</b>. Введите меньшую сумму:",
        "uz": "Coin yetarli emas. Balansingiz: <b>{balance}</b>. Kamroq kiriting:",
        "en": "Not enough coins. Your balance: <b>{balance}</b>. Enter a smaller amount:",
    },
    "giftcoins_sent": {
        "ru": "<b>Готово!</b> Подарено <b>{amount}</b> пользователю <code>{id}</code>",
        "uz": "<b>Tayyor!</b> <code>{id}</code> ga <b>{amount}</b> sovg'a qilindi",
        "en": "<b>Done!</b> Gifted <b>{amount}</b> to user <code>{id}</code>",
    },
    "giftcoins_received": {
        "ru": "<b>Вам подарили {amount}!</b>\nКто-то перевёл тебе коины. Трать в магазине",
        "uz": "<b>Sizga {amount} sovg'a qilindi!</b>\nKimdir coin yubordi. Do'konda sarflang",
        "en": "<b>You received {amount} as a gift!</b>\nSomeone sent you coins. Spend in the shop",
    },
    "gift_user_not_found": {
        "ru": "Пользователь не найден (он должен быть запущен в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi (u botda bo'lishi kerak). ID yoki @username kiriting:",
        "en": "User not found (they must be in the bot). Enter ID or @username:",
    },
    "gift_not_self": {
        "ru": "Нельзя подарить самому себе. Введите ID друга:",
        "uz": "O'zingizga sovg'a qila olmaysiz. Do'stning ID sini kiriting:",
        "en": "You can't gift yourself. Enter a friend's ID:",
    },
}
# ===================== БЛОК 5 / 14 — СЛОВАРЬ T (часть 2) =====================
T.update({

    # ============================ ССЫЛКА ============================
    "link_section": {
        "ru": "🔗 <b>Раздел «Моя ссылка»</b>\n\n👉 Выберите действие",
        "uz": "🔗 <b>«Havolam» bo'limi</b>\n\n👉 Amalni tanlang",
        "en": "🔗 <b>«My link» section</b>\n\n👉 Choose an action",
    },
    "link_menu": {
        "ru": "Выберите действие на клавиатуре",
        "uz": "Klaviaturadan amalni tanlang",
        "en": "Choose an action on the keyboard",
    },
    "link_show": {
        "ru": "🤫 <b>Ваша персональная ссылка</b>\n<blockquote>{link}</blockquote>\nНажми «Поделиться» — выбери, кому отправить, и тебе будут писать анонимно",
        "uz": "🤫 <b>Shaxsiy havolangiz</b>\n<blockquote>{link}</blockquote>\n«Ulashish» tugmasini bosing",
        "en": "🤫 <b>Your personal link</b>\n<blockquote>{link}</blockquote>\nTap «Share» — pick who to send it to",
    },
    "link_done": {
        "ru": "✅ <b>Готово! Ваша ссылка</b>\n<blockquote>{link}</blockquote>\nНажми «Поделиться», чтобы отправить её",
        "uz": "✅ <b>Tayyor! Havolangiz</b>\n<blockquote>{link}</blockquote>",
        "en": "✅ <b>Done! Your link</b>\n<blockquote>{link}</blockquote>",
    },
    "link_no_link": {
        "ru": "У вас ещё нет ссылки.\nПридумайте код (до 10 символов: латиница, цифры, «-», «_»):",
        "uz": "Sizda hali havola yo'q.\nKod kiriting (10 ta belgigacha):",
        "en": "You don't have a link yet.\nCreate a code (up to 10 characters):",
    },
    "link_change": {
        "ru": "Придумайте новый код (до 10 символов).\nСтарая ссылка работает ещё 24 часа, потом удаляется.",
        "uz": "Yangi kod kiriting (10 ta belgigacha).\nEski havola yana 24 soat ishlaydi.",
        "en": "Enter a new code (up to 10 characters).\nThe old link works for 24 more hours.",
    },
    "link_invalid": {
        "ru": "Код должен быть до 10 символов (латиница, цифры, «-», «_»). Попробуйте ещё раз:",
        "uz": "Kod 10 ta belgigacha bo'lishi kerak. Qayta urinib ko'ring:",
        "en": "Code must be up to 10 characters. Try again:",
    },
    "link_taken": {
        "ru": "Этот код уже занят, попробуйте другой:",
        "uz": "Bu kod band, boshqasini kiriting:",
        "en": "This code is already taken, try another one:",
    },
    "link_limit": {
        "ru": "Ссылку можно сменить через {days} дн. Или купи VIP для снятия ограничения",
        "uz": "Havolani {days} kundan keyin o'zgartirish mumkin. Yoki VIP sotib oling",
        "en": "You can change the link in {days} days. Or buy VIP to remove the limit",
    },
    "btn_share": {"ru": "Поделиться", "uz": "Ulashish", "en": "Share"},
    "share_text": {
        "ru": "Напиши мне что-нибудь анонимно",
        "uz": "Menga anonim biror narsa yozing",
        "en": "Send me something anonymously",
    },

    # ============================ АНОНИМКА ============================
    "anon_what_send": {
        "ru": "Что хотите отправить?",
        "uz": "Nima yubormoqchisiz?",
        "en": "What would you like to send?",
    },
    "anon_write_prompt": {
        "ru": "✍️ Напишите ваш {label} текстом или отправьте голосовое:",
        "uz": "✍️ {label}ni matn bilan yozing yoki ovozli xabar yuboring:",
        "en": "✍️ Write your {label} as text or send a voice message:",
    },
    "anon_label_question": {"ru": "вопрос", "uz": "savol", "en": "question"},
    "anon_label_valentine": {"ru": "валентинку", "uz": "valentinka", "en": "valentine"},
    "anon_sent": {"ru": "Отправлено", "uz": "Yuborildi", "en": "Sent"},
    "anon_failed": {
        "ru": "Не удалось доставить сообщение получателю",
        "uz": "Xabarni yetkazib bo'lmadi",
        "en": "Failed to deliver the message",
    },
    "anon_reply_prompt": {
        "ru": "Напиши ответ (текст или голосовое):",
        "uz": "Javob yozing (matn yoki ovozli):",
        "en": "Write your reply (text or voice):",
    },
    "anon_reply_sent": {"ru": "Ответ отправлен", "uz": "Javob yuborildi", "en": "Reply sent"},
    "anon_reply_failed": {
        "ru": "Не удалось доставить ответ",
        "uz": "Javobni yetkazib bo'lmadi",
        "en": "Failed to deliver the reply",
    },
    "anon_not_found": {"ru": "Сообщение не найдено.", "uz": "Xabar topilmadi.", "en": "Message not found."},
    "anon_limit": {
        "ru": "Лимит {n} сообщений в сутки исчерпан. VIP снимает это ограничение.",
        "uz": "Kuniga {n} ta xabar limiti tugadi. VIP bu cheklovni olib tashlaydi.",
        "en": "Daily limit of {n} messages reached. VIP removes this limit.",
    },
    "anon_vip_media": {
        "ru": "Фото/стикеры/гиф/видео могут отправлять только VIP.\nОтправь текст или голосовое.",
        "uz": "Foto/stiker/gif/video faqat VIP yuborishi mumkin.",
        "en": "Photos/stickers/gifs/videos can only be sent by VIP.",
    },
    "anon_formats": {
        "ru": "Поддерживается текст, голосовое{vip}.",
        "uz": "Matn, ovozli{vip} qo'llab-quvvatlanadi.",
        "en": "Supported: text, voice{vip}.",
    },
    "anon_formats_vip": {
        "ru": ", фото, стикеры, гиф, видео",
        "uz": ", foto, stikerlar, gif, video",
        "en": ", photos, stickers, gifs, videos",
    },
    "anon_invalid_link": {
        "ru": "Эта ссылка недействительна",
        "uz": "Bu havola yaroqsiz",
        "en": "This link is invalid",
    },
    "anon_own_link": {
        "ru": "Это ваша собственная ссылка. Самому себе писать нельзя.",
        "uz": "Bu sizning shaxsiy havolangiz. O'zingizga yozib bo'lmaydi.",
        "en": "This is your own link. You can't write to yourself.",
    },
    "anon_banned": {
        "ru": "Вы временно не можете писать этому пользователю",
        "uz": "Siz bu foydalanuvchiga vaqtincha yoza olmaysiz",
        "en": "You are temporarily unable to write to this user",
    },
    "anon_deleted_notice": {
        "ru": "🗑 Собеседник удалил своё анонимное сообщение.",
        "uz": "🗑 Suhbatdosh o'zining anonim xabarini o'chirdi.",
        "en": "🗑 The sender deleted their anonymous message.",
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
    "anon_quote_reply": {"ru": "<i>в ответ на:</i>", "uz": "<i>javoban:</i>", "en": "<i>in reply to:</i>"},
    "preview_voice": {"ru": "голосовое сообщение", "uz": "ovozli xabar", "en": "voice message"},
    "preview_media": {"ru": "медиа", "uz": "media", "en": "media"},
    "btn_reply": {"ru": "💬 Ответить", "uz": "💬 Javob", "en": "💬 Reply"},
    "btn_report": {"ru": "😡 Жалоба", "uz": "😡 Shikoyat", "en": "😡 Report"},
    "btn_reveal": {"ru": "👁 Узнать кто · 1", "uz": "👁 Kim ekan · 1", "en": "👁 Reveal who · 1"},
    "btn_delete": {"ru": "🗑 Удалить", "uz": "🗑 O'chirish", "en": "🗑 Delete"},
    "del_both": {"ru": "Удалено у обоих", "uz": "Ikkalasida ham o'chirildi", "en": "Deleted for both"},
    "del_only_me": {
        "ru": "Удалено у тебя. У собеседника не вышло (старше 48ч?).",
        "uz": "Sizda o'chirildi.",
        "en": "Deleted for you.",
    },
    "del_stale": {
        "ru": "Сообщение устарело — удалено только у тебя.",
        "uz": "Xabar eskirgan — faqat sizda o'chirildi.",
        "en": "Message is stale — deleted only for you.",
    },

    # ============================ ЖАЛОБА ============================
    "report_choose": {"ru": "Выбери причину жалобы:", "uz": "Shikoyat sababini tanlang:", "en": "Choose the report reason:"},
    "report_sent": {
        "ru": "Жалоба отправлена админу на рассмотрение",
        "uz": "Shikoyat adminga yuborildi",
        "en": "Report sent to admin for review",
    },
    "report_cancelled": {"ru": "Жалоба отменена.", "uz": "Shikoyat bekor qilindi.", "en": "Report cancelled."},
    "report_confirmed_user": {
        "ru": "Жалоба подтверждена. Этот пользователь не сможет беспокоить вас {days} дн.",
        "uz": "Shikoyat tasdiqlandi. Bu foydalanuvchi sizni {days} kun bezovta qila olmaydi.",
        "en": "Report confirmed. This user can't bother you for {days} days.",
    },
    "report_confirmed_forever": {
        "ru": "Жалоба подтверждена. Этот пользователь больше <b>никогда</b> не сможет писать вам.",
        "uz": "Shikoyat tasdiqlandi. Bu foydalanuvchi endi sizga <b>hech qachon</b> yoza olmaydi.",
        "en": "Report confirmed. This user can <b>never</b> message you again.",
    },
    "report_rejected_user": {
        "ru": "Жалоба отклонена администратором.",
        "uz": "Shikoyat administrator tomonidan rad etildi.",
        "en": "The report was rejected by the administrator.",
    },
    "report_already_handled": {
        "ru": "ℹ️ Жалоба уже обработана.",
        "uz": "ℹ️ Shikoyat allaqachon ko'rib chiqilgan.",
        "en": "ℹ️ The report has already been handled.",
    },
    "report_confirmed_staff": {
        "ru": "✅ Жалоба подтверждена, бан выдан",
        "uz": "✅ Shikoyat tasdiqlandi, ban berildi",
        "en": "✅ Report confirmed, ban issued",
    },
    "report_rejected_staff": {"ru": "❌ Жалоба отклонена", "uz": "❌ Shikoyat rad etildi", "en": "❌ Report rejected"},
    "you_were_banned": {
        "ru": "⚠️ На вас поступила жалоба — на {days} дн. вы не сможете попасть к этому собеседнику в рулетке.",
        "uz": "⚠️ Sizga shikoyat tushdi — {days} kun davomida bu suhbatdoshga tusha olmaysiz.",
        "en": "⚠️ You were reported — for {days} days you won't be matched with this person.",
    },
    "you_were_banned_forever": {
        "ru": "На вас поступила жалоба. Вы <b>навсегда</b> заблокированы для этого пользователя.",
        "uz": "Sizga shikoyat tushdi. Siz bu foydalanuvchi uchun <b>abadiy</b> bloklandingiz.",
        "en": "You were reported. You are <b>permanently</b> blocked for this user.",
    },
    "no_contacts": {
        "ru": "⛔ Нельзя отправлять ссылки, @юзернеймы, номера, ID и соцсети.",
        "uz": "⛔ Havola, @username, raqam, ID yuborib bo'lmaydi.",
        "en": "⛔ You can't send links, @usernames, numbers, IDs.",
    },
    "cant_ban_staff": {
        "ru": "Нельзя забанить администратора или модератора. Жалоба отклонена.",
        "uz": "Administrator yoki moderatorni bloklab bo'lmaydi.",
        "en": "You can't ban an admin or moderator.",
    },
    "staff_only": {"ru": "🛡 Только для модерации.", "uz": "🛡 Faqat moderatorlar uchun.", "en": "🛡 Moderation only."},
    "admin_only": {"ru": "🔒 Только для админа.", "uz": "🔒 Faqat admin uchun.", "en": "🔒 Admin only."},
    "super_admin_only": {"ru": "🔒 Только для главного админа.", "uz": "🔒 Faqat bosh admin uchun.", "en": "🔒 Super admin only."},

    # ============================ ПОДПИСКА ============================
    "sub_to_delete_short": {
        "ru": "<b>Чтобы удалить сообщение — подпишись</b>\n<i>Нажми на кнопки ниже, подпишись, вернись и нажми «Проверить».</i>",
        "uz": "<b>Xabarni o'chirish uchun — obuna bo'ling</b>",
        "en": "<b>To delete the message — subscribe</b>",
    },
    "btn_check_sub": {"ru": "Проверить", "uz": "Tekshirish", "en": "Check"},
    "subgate_start": {
        "ru": "🔒 <b>Чтобы пользоваться ботом — подпишись</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Нажми на кнопки ниже, подпишись, затем вернись и нажми «Проверить».</i>",
        "uz": "🔒 <b>Botdan foydalanish uchun — obuna bo'ling</b>",
        "en": "🔒 <b>To use the bot — subscribe</b>",
    },
    "sub_not_found": {
        "ru": "❗ Подписка не найдена, проверь ещё раз",
        "uz": "❗ Obuna topilmadi, qayta tekshiring",
        "en": "❗ Subscription not found, check again",
    },

    # ============================ РУЛЕТКА ============================
    "roulette_who": {"ru": "🎲 Кого вы хотите найти?", "uz": "🎲 Kimni topmoqchisiz?", "en": "🎲 Who do you want to find?"},
    "roulette_searching": {"ru": "⏳ Идёт поиск собеседника…", "uz": "⏳ Suhbatdosh qidirilmoqda…", "en": "⏳ Searching for a partner…"},
    "roulette_finding_partner": {"ru": "⏳ Идёт поиск собеседника…", "uz": "⏳ Suhbatdosh qidirilmoqda…", "en": "⏳ Searching for a partner…"},
    "roulette_already_chat": {
        "ru": "Вы уже в чате. Пишите собеседнику или используйте кнопки ниже",
        "uz": "Siz allaqachon chatsiz.",
        "en": "You are already in a chat.",
    },
    "roulette_stop": {"ru": "Поиск отменён.", "uz": "Qidiruv bekor qilindi.", "en": "Search cancelled."},
    "roulette_left": {"ru": "Собеседник покинул чат.", "uz": "Suhbatdosh chatni tark etdi.", "en": "Partner left the chat."},
    "session_not_found": {"ru": "❓ Сессия не найдена.", "uz": "❓ Sessiya topilmadi.", "en": "❓ Session not found."},
    "search_still": {
        "ru": "Всё ещё ищем тебе собеседника…\nТы в поиске уже <b>{min}</b> мин.",
        "uz": "Hali ham suhbatdosh qidirilmoqda…\nSiz <b>{min}</b> daqiqadan beri qidiruvdasiz.",
        "en": "Still looking for a partner…\nYou've been searching for <b>{min}</b> min.",
    },
    "search_timeout": {
        "ru": "<b>Поиск остановлен</b> — за {min} мин подходящий собеседник не нашёлся",
        "uz": "<b>Qidiruv to'xtatildi</b> — {min} daqiqada mos suhbatdosh topilmadi",
        "en": "<b>Search stopped</b> — no match found in {min} min",
    },
    "roulette_found": {
        "ru": "🎲🟢 <b>СОБЕСЕДНИК НАЙДЕН</b> 🟢🎲\n━━━━━━━━━━━━━━━━━━━━\n<i>Пиши первым — не стесняйся!</i>\n<blockquote>🤫 Полная анонимность\nМожно слать фото, голосовые и стикеры</blockquote>\n<i>«Далее» — другой · «Стоп» — выйти</i>",
        "uz": "🎲🟢 <b>SUHBATDOSH TOPILDI</b> 🟢🎲\n<i>Birinchi bo'lib yozing!</i>",
        "en": "🎲🟢 <b>A PARTNER IS FOUND</b> 🟢🎲\n<i>Write first!</i>",
    },

    # ============================ МАГАЗИН ============================
    "shop_title": {"ru": "🛒 <b>Магазин</b>\nВыберите товар", "uz": "🛒 <b>Do'kon</b>\nMahsulotni tanlang", "en": "🛒 <b>Shop</b>\nChoose an item"},
    "shop_empty": {"ru": "<b>Магазин пока пуст.</b>", "uz": "<b>Do'kon hali bo'sh.</b>", "en": "<b>The shop is empty.</b>"},
    "shop_pick_item": {"ru": "🛒 Выберите товар на клавиатуре", "uz": "🛒 Klaviaturadan mahsulotni tanlang", "en": "🛒 Choose an item on the keyboard"},
    "shop_vip_note": {
        "ru": "<i>Цены показаны с твоей VIP-скидкой −20%.</i>",
        "uz": "<i>Narxlar VIP chegirmangiz −20% bilan ko'rsatilgan.</i>",
        "en": "<i>Prices shown with your VIP −20% discount.</i>",
    },
    "item_unavailable": {"ru": "❌ Товар недоступен.", "uz": "❌ Mahsulot mavjud emas.", "en": "❌ Item unavailable."},
    "not_enough_coins": {"ru": "💸 Недостаточно коинов", "uz": "💸 Coinlar yetarli emas", "en": "💸 Not enough coins"},
    "shop_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» за {price}?",
        "uz": "«<b>{title}</b>»ni {price} ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» for {price}?",
    },
    "price_plain": {"ru": "<b>{price}</b>", "uz": "<b>{price}</b>", "en": "<b>{price}</b>"},
    "price_vip": {
        "ru": "<b>{price}</b> (VIP-скидка, обычно {orig})",
        "uz": "<b>{price}</b> (VIP chegirma, odatda {orig})",
        "en": "<b>{price}</b> (VIP discount, usually {orig})",
    },
    "purchase_coins": {
        "ru": "✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b>",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> <b>{amt}</b> qo'shildi",
        "en": "✅ <b>Purchase complete!</b> <b>{amt}</b> added",
    },
    "purchase_vip": {
        "ru": "✅ <b>Покупка совершена!</b> VIP активен на <b>{days}</b> дн.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> VIP <b>{days}</b> kun faol",
        "en": "✅ <b>Purchase complete!</b> VIP active for <b>{days}</b> days",
    },
    "purchase_manual": {
        "ru": "✅ <b>Покупка совершена!</b> Админ свяжется с вами.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> Admin siz bilan bog'lanadi.",
        "en": "✅ <b>Purchase complete!</b> The admin will contact you.",
    },

    # ============================ STARS ============================
    "stars_unavailable": {
        "ru": "Покупка коинов пока недоступна.",
        "uz": "Coin sotib olish hozircha mavjud emas.",
        "en": "Buying coins is not available yet.",
    },
    "stars_pick_pkg": {"ru": "💎 Выбери пакет на клавиатуре", "uz": "💎 Klaviaturadan paketni tanlang", "en": "💎 Choose a package on the keyboard"},
    "pkg_unavailable": {"ru": "Пакет недоступен.", "uz": "Paket mavjud emas.", "en": "Package unavailable."},
    "stars_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» ({coins} коинов) за <b>{stars} ⭐</b>?",
        "uz": "«<b>{title}</b>» ({coins} coin) ni <b>{stars} ⭐</b> ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» ({coins} coins) for <b>{stars} ⭐</b>?",
    },
    "stars_invoice_sent": {
        "ru": "💳 Счёт выставлен ниже. Оплати кнопкой или вернись в меню",
        "uz": "💳 Hisob-faktura quyida. To'lang yoki menyuga qayting",
        "en": "💳 The invoice is below. Pay with the button or return to the menu",
    },
    "stars_pkg_desc": {"ru": "{coins} коинов для бота", "uz": "Bot uchun {coins} coin", "en": "{coins} coins for the bot"},
    "stars_paid": {
        "ru": "🔥 <b>Оплата прошла!</b> Начислено <b>{coins}</b>",
        "uz": "🔥 <b>To'lov amalga oshdi!</b> <b>{coins}</b> qo'shildi",
        "en": "🔥 <b>Payment successful!</b> <b>{coins}</b> added",
    },
    "stars_title": {
        "ru": "<b>Покупка коинов за Telegram Stars</b>\nВыбери пакет",
        "uz": "<b>Telegram Stars uchun coin sotib olish</b>\nPaketni tanlang",
        "en": "<b>Buy coins with Telegram Stars</b>\nChoose a package",
    },

    # ============================ РАСКРЫТИЕ ============================
    "msg_not_found": {"ru": "Сообщение не найдено", "uz": "Xabar topilmadi", "en": "Message not found"},
    "reveal_profile_link": {"ru": "профиль", "uz": "profil", "en": "profile"},
    "btn_reveal_yes": {"ru": "Да, раскрыть · 1", "uz": "Ha, aniqlash · 1", "en": "Yes, reveal · 1"},
    "btn_cancel_accent": {"ru": "Отмена", "uz": "Bekor", "en": "Cancel"},
    "reveal_title": {"ru": "Раскрыть отправителя", "uz": "Yuboruvchini aniqlash", "en": "Reveal sender"},
    "reveal_desc": {
        "ru": "Узнай, кто отправил тебе это анонимное сообщение",
        "uz": "Sizga bu anonim xabarni kim yuborganini biling",
        "en": "Find out who sent you this anonymous message",
    },
    "reveal_result": {
        "ru": "<b>Отправитель раскрыт!</b>\n\nИмя: <b>{name}</b>\nНик: {uname}\nID: <code>{tid}</code>",
        "uz": "<b>Yuboruvchi aniqlandi!</b>\n\nIsm: <b>{name}</b>\nNik: {uname}\nID: <code>{tid}</code>",
        "en": "<b>Sender revealed!</b>\n\nName: <b>{name}</b>\nUsername: {uname}\nID: <code>{tid}</code>",
    },
    "reveal_confirm": {
        "ru": "Раскрыть отправителя этого сообщения за <b>1 ⭐</b>?",
        "uz": "Ushbu xabar yuboruvchini <b>1 ⭐</b> uchun aniqlaysizmi?",
        "en": "Reveal the sender of this message for <b>1 ⭐</b>?",
    },
    "reveal_paying": {"ru": "Оплатите инвойс ниже...", "uz": "Quyidagi hisob-fakturani to'lang...", "en": "Pay the invoice below..."},
    "reveal_only_recipient": {
        "ru": "Только получатель может раскрыть отправителя.",
        "uz": "Faqat qabul qiluvchi yuboruvchini aniqlay oladi.",
        "en": "Only the recipient can reveal the sender.",
    },

    # ============================ РЕФЕРАЛЫ ============================
    "referral_screen": {
        "ru": (
            "<b>Приглашай друзей — зарабатывай коины!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "За каждого друга: <b>{reward}</b>{bonus}\n"
            "Приглашено: <b>{total}</b>\n"
            "Заработано: <b>{earned}</b>\n\n"
            "Твоя ссылка:\n"
            "<blockquote>{link}</blockquote>\n"
            "Если друг заблокирует бота — коины за него спишутся обратно."
        ),
        "uz": (
            "<b>Do'stlarni taklif qiling — coin ishlang!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Har bir do'st uchun: <b>{reward}</b>{bonus}\n"
            "Taklif qilindi: <b>{total}</b>\n"
            "Ishlab topildi: <b>{earned}</b>\n\n"
            "Havolangiz:\n"
            "<blockquote>{link}</blockquote>"
        ),
        "en": (
            "<b>Invite friends — earn coins!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "For each friend: <b>{reward}</b>{bonus}\n"
            "Invited: <b>{total}</b>\n"
            "Earned: <b>{earned}</b>\n\n"
            "Your link:\n"
            "<blockquote>{link}</blockquote>"
        ),
    },
    "referral_bonus_vip": {"ru": " (VIP-бонус)", "uz": " (VIP bonus)", "en": " (VIP bonus)"},
    "referral_bonus_normal": {"ru": " (у VIP — 100)", "uz": " (VIP uchun — 100)", "en": " (VIP gets 100)"},
    "ref_rewards_title": {
        "ru": (
            "<b>Награды за друзей</b>\n"
            "Приведи друзей по ссылке (чтобы они создали свою ссылку) и забери:\n"
            "<b>VIP бесплатно</b> — за {vip_n} друзей ({vip_d} дн.)\n"
            "<b>Модерка на неделю</b> — за {mod_n} друзей ({mod_d} дн.)\n"
            "Жми кнопку, когда наберёшь"
        ),
        "uz": (
            "<b>Do'stlar uchun mukofotlar</b>\n"
            "<b>Bepul VIP</b> — {vip_n} do'st uchun ({vip_d} kun)\n"
            "<b>Bir haftalik moder</b> — {mod_n} do'st uchun ({mod_d} kun)"
        ),
        "en": (
            "<b>Rewards for friends</b>\n"
            "<b>Free VIP</b> — for {vip_n} friends ({vip_d} days)\n"
            "<b>Moderator for a week</b> — for {mod_n} friends ({mod_d} days)"
        ),
    },
    "ref_claim_coins_btn": {"ru": "{n} за друга · VIP {v}", "uz": "do'st uchun {n} · VIP {v}", "en": "{n} per friend · VIP {v}"},
    "btn_share_ref": {"ru": "Поделиться ссылкой", "uz": "Havolani ulashish", "en": "Share the link"},
    "ref_share_text": {
        "ru": "Залетай в анонимный бот! Тебе пишут тайно, чат-рулетка, подарки 🎁 Жми",
        "uz": "Anonim botga kir! Sizga yashirin yozishadi, chat-ruletka, sovg'alar 🎁 Bosing",
        "en": "Join the anonymous bot! Get secret messages, chat roulette, gifts 🎁 Tap",
    },
    "ref_claim_vip_btn": {"ru": "VIP бесплатно", "uz": "Bepul VIP", "en": "Free VIP"},
    "ref_claim_moder_btn": {"ru": "Модерка на неделю", "uz": "Bir haftalik moder", "en": "Moderator for a week"},
    "ref_need_more": {
        "ru": (
            "❌ Недостаточно друзей\n\n"
            "Нужно ещё: {n}\n"
            "У тебя подходящих: {have} из {need}\n\n"
            "Считаются только те друзья, которые сами создали свою ссылку."
        ),
        "uz": "❌ Do'stlar yetarli emas\n\nYana kerak: {n}\nSizda mos: {have} / {need}",
        "en": "❌ Not enough friends\n\nNeed more: {n}\nYou have: {have} / {need}",
    },
    "ref_vip_granted": {
        "ru": "🎉 <b>VIP активирован на {days} дней</b> за приглашённых друзей!",
        "uz": "🎉 <b>VIP {days} kunga faollashtirildi</b>!",
        "en": "🎉 <b>VIP activated for {days} days</b>!",
    },
    "ref_moder_granted": {
        "ru": "<b>Модерка выдана на {days} дней</b> за {need} приглашённых друзей!\nПрочувствуй власть модератора 👑",
        "uz": "<b>Moderlik {days} kunga berildi</b> — {need} ta do'st uchun!",
        "en": "<b>Moderator granted for {days} days</b> for {need} invited friends!",
    },
    "ref_info_alert": {
        "ru": "За каждого приглашённого друга: {n} (а если ты VIP — {v}). Коины приходят автоматически.",
        "uz": "Har bir taklif qilingan do'st uchun: {n} (VIP bo'lsangiz — {v}).",
        "en": "For each invited friend: {n} (VIP gets {v}).",
    },
    "link_reward": {
        "ru": "<b>Бонус за активность по ссылке:</b> +{coins}\nВсего действий: {n}. Так держать! 🔥",
        "uz": "<b>Havola faolligi uchun bonus:</b> +{coins}\nJami: {n}.",
        "en": "<b>Activity bonus for your link:</b> +{coins}\nTotal actions: {n}.",
    },
    "ref_menu_hint": {"ru": "Меню «Пригласить»", "uz": "«Taklif qilish» menyusi", "en": "Invite menu"},
    "ref_friend_joined": {
        "ru": "🎉 По твоей ссылке пришёл друг! Тебе начислено <b>+{reward}</b>",
        "uz": "🎉 Havolangiz orqali do'st keldi! Sizga <b>+{reward}</b> qo'shildi",
        "en": "🎉 A friend joined via your link! You earned <b>+{reward}</b>",
    },
    "ref_welcome_bonus": {
        "ru": "<b>Добро пожаловать!</b> Ты пришёл по ссылке друга — лови подарок <b>+{n}</b>",
        "uz": "<b>Xush kelibsiz!</b> Do'st havolasi orqali keldingiz — sovg'a <b>+{n}</b>",
        "en": "<b>Welcome!</b> You joined via a friend's link — here's a gift <b>+{n}</b>",
    },
    "ref_progress_title": {"ru": "<b>Прогресс до наград:</b>", "uz": "<b>Mukofotlargacha progress:</b>", "en": "<b>Progress to rewards:</b>"},
    "ref_friends_word": {"ru": "друзей", "uz": "do'st", "en": "friends"},
    "top_empty": {
        "ru": "Пока никто никого не пригласил. Будь первым! 🏆",
        "uz": "Hozircha hech kim taklif qilmagan. Birinchi bo'ling! 🏆",
        "en": "No one has invited anyone yet. Be the first! 🏆",
    },
    "top_title": {"ru": "🏆 <b>Топ пригласивших</b>", "uz": "🏆 <b>Eng ko'p taklif qilganlar</b>", "en": "🏆 <b>Top inviters</b>"},
    "ref_coins_refunded": {
        "ru": "⚠️ Приглашённый друг заблокировал бота — <b>{n}</b> списаны обратно.",
        "uz": "⚠️ Taklif qilingan do'st botni blokladi — <b>{n}</b> qaytarib olindi.",
        "en": "⚠️ Your invited friend blocked the bot — <b>{n}</b> deducted back.",
    },

    # ============================ МОДЕРАЦИЯ / АДМИНКА ============================
    "vip_daily_bonus": {
        "ru": "🎁 Ежедневный VIP-бонус: <b>+{n}</b>",
        "uz": "🎁 Kunlik VIP bonus: <b>+{n}</b>",
        "en": "🎁 Daily VIP bonus: <b>+{n}</b>",
    },
    "moder_form_gender": {
        "ru": "<b>Анкета на модератора.</b>\n\nВаш пол?",
        "uz": "<b>Moderatorlik anketasi.</b>\n\nJinsingiz?",
        "en": "<b>Moderator application.</b>\n\nYour gender?",
    },
    "moder_form_age": {"ru": "Сколько вам лет?", "uz": "Yoshingiz nechada?", "en": "How old are you?"},
    "moder_form_tg": {"ru": "Сколько времени проводите в Telegram в день?", "uz": "Kuniga Telegramda qancha vaqt o'tkazasiz?", "en": "How much time do you spend on Telegram per day?"},
    "moder_form_avail": {"ru": "Сколько готовы уделять боту? Когда вы онлайн?", "uz": "Botga qancha vaqt ajrata olasiz?", "en": "How much time can you give the bot?"},
    "moder_form_cancelled": {
        "ru": "↩️ Анкета отменена. Коины ({price}) возвращены.",
        "uz": "↩️ Anketa bekor qilindi. Coinlar ({price}) qaytarildi.",
        "en": "↩️ Application cancelled. Coins ({price}) refunded.",
    },
    "moder_form_sent": {
        "ru": "📨 Анкета отправлена администратору. Ожидайте решения!",
        "uz": "📨 Anketa administratorga yuborildi.",
        "en": "📨 Application sent to the administrator.",
    },
    "moder_granted_user": {
        "ru": "🛡 Вам выдана роль модератора! В меню появилась кнопка «Модерка».",
        "uz": "🛡 Sizga moderator roli berildi!",
        "en": "🛡 You've been granted the moderator role!",
    },
    "moder_granted_shop": {
        "ru": "<b>Вы теперь Модер!</b> Добро пожаловать в команду 👑\nЗа бонусом напишите админу @ToxIc_0707",
        "uz": "<b>Endi siz Modersiz!</b> Jamoaga xush kelibsiz 👑",
        "en": "<b>You're a Moder now!</b> Welcome to the team 👑",
    },
    "moder_rejected_user": {
        "ru": "❌ К сожалению, заявка на модера отклонена. Коины ({coins}) возвращены.",
        "uz": "❌ Afsuski, moderlik arizasi rad etildi. Coinlar ({coins}) qaytarildi.",
        "en": "❌ Unfortunately, your moder application was rejected. Coins ({coins}) refunded.",
    },
    "moder_taken_user": {"ru": "🛡 Роль модератора снята.", "uz": "🛡 Moderator roli olib tashlandi.", "en": "🛡 The moderator role has been removed."},
    "moder_app_already": {"ru": "ℹ️ Заявка уже обработана.", "uz": "ℹ️ Ariza ko'rib chiqilgan.", "en": "ℹ️ Already handled."},
    "moder_granted_staff": {"ru": "✅ Модерка выдана.", "uz": "✅ Moderlik berildi.", "en": "✅ Moderation granted."},
    "moder_rejected_staff": {"ru": "❌ Заявка отклонена, коины возвращены.", "uz": "❌ Ariza rad etildi, coinlar qaytarildi.", "en": "❌ Application rejected, coins refunded."},
    "mod_message": {
        "ru": "<b>Сообщение от модератора {name}</b>:\n{text}",
        "uz": "<b>{name} moderatordan xabar</b>:\n{text}",
        "en": "<b>Message from moderator {name}</b>:\n{text}",
    },
    "admin_vip_menu": {
        "ru": "<b>Управление VIP по ID</b>\n\nВыдать или забрать VIP у пользователя",
        "uz": "<b>ID bo'yicha VIP boshqaruvi</b>",
        "en": "<b>VIP management by ID</b>",
    },
    "vip_ask_id": {
        "ru": "Введите <b>tg_id</b> или <b>@username</b> пользователя:",
        "uz": "Foydalanuvchining <b>tg_id</b> yoki <b>@username</b> ini kiriting:",
        "en": "Enter the user's <b>tg_id</b> or <b>@username</b>:",
    },
    "vip_ask_days": {"ru": "На сколько дней выдать VIP? (число)", "uz": "VIP necha kunga berilsin?", "en": "For how many days to grant VIP?"},
    "vip_id_number": {"ru": "ID должен быть числом. Попробуйте снова:", "uz": "ID raqam bo'lishi kerak:", "en": "ID must be a number:"},
    "vip_days_number": {"ru": "Введите положительное число дней:", "uz": "Musbat kunlar sonini kiriting:", "en": "Enter a positive number of days:"},
    "vip_user_not_found": {
        "ru": "Пользователь не найден (он должен быть в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi. ID yoki @username kiriting:",
        "en": "User not found. Enter ID or @username:",
    },
    "vip_granted_admin": {
        "ru": "VIP выдан пользователю <code>{id}</code> на <b>{days}</b> дн.",
        "uz": "<code>{id}</code> ga VIP <b>{days}</b> kunga berildi.",
        "en": "VIP granted to user <code>{id}</code> for <b>{days}</b> days.",
    },
    "vip_taken_admin": {"ru": "VIP снят у пользователя <code>{id}</code>.", "uz": "<code>{id}</code> dan VIP olib tashlandi.", "en": "VIP revoked from user <code>{id}</code>."},
    "vip_granted_user": {
        "ru": "<b>Вам выдан VIP на {days} дней!</b>\nНаслаждайтесь привилегиями 💎",
        "uz": "<b>Sizga {days} kunga VIP berildi!</b> 💎",
        "en": "<b>You've been granted VIP for {days} days!</b> 💎",
    },
    "vip_taken_user": {"ru": "👑 Ваш VIP-статус был снят администратором.", "uz": "👑 VIP holatingiz olib tashlandi.", "en": "👑 Your VIP status was revoked."},
    "vip_bulk_menu_title": {
        "ru": "🎯 <b>Массовый VIP — {target}</b>\n\nВыберите действие:",
        "uz": "🎯 <b>Ommaviy VIP — {target}</b>\n\nAmalni tanlang:",
        "en": "🎯 <b>Bulk VIP — {target}</b>\n\nChoose an action:",
    },
    "vip_bulk_revoke_done": {
        "ru": "✅ VIP снят у <b>{target}</b> ({count} чел.)",
        "uz": "✅ <b>{target}</b>dan VIP olib tashlandi ({count} kishi)",
        "en": "✅ VIP revoked from <b>{target}</b> ({count} users)",
    },
    "vip_bulk_ask_days": {
        "ru": "На сколько дней выдать VIP <b>{target}</b>? (число)",
        "uz": "VIP <b>{target}</b> necha kunga berilsin?",
        "en": "For how many days to grant VIP to <b>{target}</b>?",
    },
    "vip_bulk_done": {
        "ru": "VIP выдан <b>{target}</b> на <b>{days}</b> дн. ({count} чел.)",
        "uz": "VIP <b>{target}</b> <b>{days}</b> kunga berildi ({count} kishi)",
        "en": "VIP granted to <b>{target}</b> for <b>{days}</b> days ({count} users)",
    },
    "inactive_nudge": {
        "ru": "💤 <b>Давно тебя не было в 𐌽ꤕ𐌗ተ!</b>\nЧтобы не потерять свои данные (коины, VIP, ссылку) — просто нажми /start 👋",
        "uz": "💤 <b>Sizni 𐌽ꤕ𐌗ተ da ko'rmaganimizga ancha bo'ldi!</b>\nMa'lumotlaringizni yo'qotmaslik uchun /start ni bosing 👋",
        "en": "💤 <b>Haven't seen you in 𐌽ꤕ𐌗ተ for a while!</b>\nSo you don't lose your data — just tap /start 👋",
    },
    "moder_help": {
        "ru": (
            "<b>Помощь по модерке</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Кнопки панели:</b>\n"
            "<blockquote>"
            "<b>Жалобы</b> — список жалоб\n"
            "<b>Бан / Разбан</b> — по ID\n"
            "<b>Статистика</b> — цифры\n"
            "<b>Выгрузить пользователей</b> — .txt\n"
            "<b>Обязательные каналы</b> — каналы для удаления"
            "</blockquote>\n"
            "<b>Скрытые команды:</b>\n"
            "<blockquote>"
            "<b>/tg</b> — мониторинг рулетки\n"
            "<b>/next</b> — написать пользователю по ID\n"
            "<b>/anon</b> — наблюдение за анонимной перепиской\n"
            "<b>/sex</b> — комната для девушек (только для модеров)"
            "</blockquote>\n"
            "<i>Сообщения могут проверяться для безопасности.</i>"
        ),
        "uz": (
            "<b>Moderator yordami</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel tugmalari:</b>\n"
            "<blockquote><b>Shikoyatlar</b>\n<b>Ban / Unban</b>\n<b>Statistika</b>\n<b>Fayllar</b></blockquote>\n"
            "<b>Maxfiy buyruqlar</b>: <b>/tg</b>, <b>/next</b>, <b>/anon</b>, <b>/sex</b>"
        ),
        "en": (
            "<b>Moderator help</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel buttons:</b>\n"
            "<blockquote><b>Reports</b>\n<b>Ban / Unban</b>\n<b>Statistics</b>\n<b>Export</b></blockquote>\n"
            "<b>Hidden commands</b>: <b>/tg</b>, <b>/next</b>, <b>/anon</b>, <b>/sex</b>"
        ),
    },

    # ============================ ПОБЛИЗОСТИ ============================
    "nearby_title": {
        "ru": "📍 <b>Поблизости</b>\n━━━━━━━━━━━━━━━━━━━━\nВыбери действие:",
        "uz": "📍 <b>Yaqin-atrofda</b>\n━━━━━━━━━━━━━━━━━━━━\nAmalni tanlang:",
        "en": "📍 <b>Nearby</b>\n━━━━━━━━━━━━━━━━━━━━\nChoose an action:",
    },
    "nearby_create_title": {
        "ru": "📍 <b>Анкета Поблизости</b>\n━━━━━━━━━━━━━━━━━━━━\nСоздай анкету, чтобы тебя видели другие.\n\n",
        "uz": "📍 <b>Yaqin-atrofda anketasi</b>\n━━━━━━━━━━━━━━━━━━━━\n",
        "en": "📍 <b>Nearby profile</b>\n━━━━━━━━━━━━━━━━━━━━\nCreate a profile to be seen.\n\n",
    },
    "nearby_ask_name": {"ru": "✏️ <b>Шаг 1/5</b> — напиши своё <b>имя</b>:", "uz": "✏️ <b>1/5</b> — <b>ismingiz</b>:", "en": "✏️ <b>Step 1/5</b> — your <b>name</b>:"},
    "nearby_ask_age": {"ru": "✏️ <b>Шаг 2/5</b> — сколько тебе <b>лет</b>? (число)", "uz": "✏️ <b>2/5</b> — <b>yoshingiz</b>?", "en": "✏️ <b>Step 2/5</b> — your <b>age</b>?"},
    "nearby_ask_gender": {"ru": "✏️ <b>Шаг 3/5</b> — твой <b>пол</b>:", "uz": "✏️ <b>3/5</b> — <b>jinsingiz</b>:", "en": "✏️ <b>Step 3/5</b> — your <b>gender</b>:"},
    "nearby_ask_looking": {"ru": "✏️ <b>Шаг 4/5</b> — <b>кого ищешь</b>?", "uz": "✏️ <b>4/5</b> — <b>kimni qidirasiz</b>?", "en": "✏️ <b>Step 4/5</b> — <b>who are you looking for</b>?"},
    "nearby_ask_bio": {"ru": "✏️ <b>Шаг 5/5</b> — расскажи <b>о себе</b> (до 200 символов):", "uz": "✏️ <b>5/5</b> — <b>o'zingiz haqida</b> (200 ta belgigacha):", "en": "✏️ <b>Step 5/5</b> — <b>about you</b> (up to 200 chars):"},
    "nearby_ask_photo": {
        "ru": "📷 Последний шаг — отправь своё <b>фото</b>\n(или напиши «-» чтобы пропустить)",
        "uz": "📷 Oxirgi qadam — <b>foto</b> yuboring\n(yoki «-» yozing)",
        "en": "📷 Last step — send your <b>photo</b>\n(or type «-» to skip)",
    },
    "nearby_name_invalid": {"ru": "Имя 2-30 символов:", "uz": "Ism 2-30 belgi:", "en": "Name 2-30 chars:"},
    "nearby_age_invalid": {"ru": "Возраст 12-99:", "uz": "Yosh 12-99:", "en": "Age 12-99:"},
    "nearby_bio_invalid": {"ru": "Опиши 5-200 символов:", "uz": "5-200 belgi yozing:", "en": "Describe 5-200 chars:"},
    "nearby_photo_required": {"ru": "📷 Отправь именно фото или «-» чтобы пропустить:", "uz": "📷 Foto yuboring yoki «-»:", "en": "📷 Send photo or «-»:"},
    "nearby_profile_saved": {
        "ru": "✅ <b>Анкета создана!</b>\n\nТеперь можешь смотреть анкеты других.",
        "uz": "✅ <b>Anketa yaratildi!</b>\n\nBoshqalarni ko'rishingiz mumkin.",
        "en": "✅ <b>Profile created!</b>\n\nNow you can browse others.",
    },
    "nearby_no_more": {
        "ru": "😔 <b>Пока никого нет</b>\n\nВозможно, анкет мало. Зайди позже!",
        "uz": "😔 <b>Hozircha hech kim yo'q</b>\n\nKeyinroq kiring!",
        "en": "😔 <b>No one yet</b>\n\nCome back later!",
    },
    "nearby_match_title": {"ru": "💕 <b>Взаимная симпатия!</b>\n━━━━━━━━━━━━━━━━━━━━", "uz": "💕 <b>O'zaro yoqdi!</b>\n━━━━━━━━━━━━━━━━━━━━", "en": "💕 <b>Mutual like!</b>\n━━━━━━━━━━━━━━━━━━━━"},
    "nearby_match_contact": {"ru": "Собеседник: <b>{name}</b>\n\n{contact}", "uz": "Suhbatdosh: <b>{name}</b>\n\n{contact}", "en": "Partner: <b>{name}</b>\n\n{contact}"},
    "nearby_match_footer": {"ru": "Мы сообщили о мэтче боту @{bot}", "uz": "@{bot} botga xabar berdik", "en": "Reported match to bot @{bot}"},
    "nearby_no_matches": {
        "ru": "💕 <b>Мои мэтчи</b>\n\nПока никого нет 😔\nЛайкай анкеты — будут взаимные!",
        "uz": "💕 <b>Mening matchlarim</b>\n\nHozircha yo'q 😔",
        "en": "💕 <b>My matches</b>\n\nNone yet 😔",
    },
    "nearby_matches_list": {"ru": "💕 <b>Мои мэтчи ({n})</b>\n━━━━━━━━━━━━━━━━━━━━", "uz": "💕 <b>Matchlarim ({n})</b>", "en": "💕 <b>My matches ({n})</b>"},
    "nearby_matches_footer": {
        "ru": "Напиши в ЛС — это единственный способ связаться после мэтча.",
        "uz": "Lichkaga yozing — bog'lanishning yagona yo'li.",
        "en": "DM them — the only way to contact after a match.",
    },

    # ============================ /sex ============================
    "sex_only_moder": {"ru": "🛡 Только для модераторов.", "uz": "🛡 Faqat moderatorlar uchun.", "en": "🛡 Moderators only."},
    "sex_room_exists": {"ru": "💬 Комната уже создана: <b>{title}</b>", "uz": "💬 Xona allaqachon yaratilgan: <b>{title}</b>", "en": "💬 Room already exists: <b>{title}</b>"},
    "sex_create_prompt": {
        "ru": "💬 <b>Создание комнаты</b>\n\nВведи название комнаты:",
        "uz": "💬 <b>Xona yaratish</b>\n\nXona nomini kiriting:",
        "en": "💬 <b>Create room</b>\n\nEnter room name:",
    },
    "sex_room_created": {
        "ru": "✅ Комната «<b>{title}</b>» создана!\n\nВсе девушки бота добавлены автоматически.",
        "uz": "✅ «<b>{title}</b>» xonasi yaratildi!\n\nBarcha qizlar avtomatik qo'shildi.",
        "en": "✅ Room «<b>{title}</b>» created!\n\nAll girls auto-added.",
    },
    "sex_room_joined": {"ru": "💬 Ты в комнате <b>{title}</b>", "uz": "💬 Siz <b>{title}</b> xonasidasiz", "en": "💬 You're in room <b>{title}</b>"},
    "sex_room_deleted": {"ru": "🗑 Комната удалена.", "uz": "🗑 Xona o'chirildi.", "en": "🗑 Room deleted."},
    "sex_room_renamed": {"ru": "✏️ Комната переименована в <b>{title}</b>", "uz": "✏️ Xona <b>{title}</b> ga o'zgartirildi", "en": "✏️ Room renamed to <b>{title}</b>"},
    "sex_exit_requested": {
        "ru": "⏳ Запрос на выход отправлен. Жди одобрения модера.",
        "uz": "⏳ Chiqish so'rovi yuborildi.",
        "en": "⏳ Exit request sent.",
    },
    "sex_exit_approved": {"ru": "✅ Ты вышел из комнаты.", "uz": "✅ Siz xonadan chiqdingiz.", "en": "✅ You left the room."},
    "sex_renamed_prompt": {"ru": "✏️ Введи новое название:", "uz": "✏️ Yangi nomni kiriting:", "en": "✏️ Enter new name:"},
    "sex_only_owner_can_delete": {
        "ru": "Удалить комнату может только её создатель.",
        "uz": "Xonani faqat yaratuvchi o'chira oladi.",
        "en": "Only the owner can delete the room.",
    },
    "sex_only_owner_can_rename": {
        "ru": "Переименовать комнату может только её создатель.",
        "uz": "Xonani faqat yaratuvchi nomini o'zgartira oladi.",
        "en": "Only the owner can rename the room.",
    },
    "sex_no_room": {
        "ru": "💬 Нет активной комнаты.\n\nНабери /sex чтобы создать.",
        "uz": "💬 Faol xona yo'q.\n\n/sex ni bosing.",
        "en": "💬 No active room.\n\nType /sex to create.",
    },
    "sex_member_joined_you": {
        "ru": "👤 <b>{name}</b> присоединился к комнате (номер {num})",
        "uz": "👤 <b>{name}</b> xonaga qo'shildi ({num})",
        "en": "👤 <b>{name}</b> joined the room (#{num})",
    },
    "sex_msg_from": {"ru": "<b>💬 {num}:</b>", "uz": "<b>💬 {num}:</b>", "en": "<b>💬 {num}:</b>"},

    # ============================ /anon НАБЛЮДЕНИЕ ============================
    "anon_watch_prompt": {
        "ru": "👁 <b>Наблюдение за анонимной перепиской</b>\n"
              "━━━━━━━━━━━━━━━━━━━━\n"
              "Введите ID пользователя, чью переписку вы хотите посмотреть.\n"
              "Будет отправлена история файлом и подписка на новые сообщения.\n\n"
              "<i>«Отмена» — вернуться в меню</i>",
        "uz": "👁 <b>Anonim yozishmalarni kuzatish</b>\n\nFoydalanuvchi ID sini kiriting.",
        "en": "👁 <b>Anonymous chat watch</b>\n\nEnter user ID to watch.",
    },
    "anon_watch_empty": {"ru": "❌ У пользователя нет переписки.", "uz": "❌ Foydalanuvchida yozishma yo'q.", "en": "❌ User has no chats."},
    "anon_watch_file_caption": {
        "ru": "👁 <b>Наблюдение за {uid}</b>\nСвежие сообщения будут приходить в ЛС.",
        "uz": "👁 <b>{uid} kuzatilmoqda</b>\nYangi xabarlar LС ga keladi.",
        "en": "👁 <b>Watching {uid}</b>\nNew messages will arrive in DM.",
    },
    "anon_watch_leave": {"ru": "🚪 Вы вышли из наблюдения.", "uz": "🚪 Kuzatishdan chiqdingiz.", "en": "🚪 You left the watch."},
    "anon_watch_new_msg": {
        "ru": "👁 <b>Новая анонимка для {uid}</b>\nОт: <b>{sname}</b> (<code>{sfid}</code>)\n{when}",
        "uz": "👁 <b>{uid} uchun yangi anonimka</b>\nKimdan: <b>{sname}</b>",
        "en": "👁 <b>New anon for {uid}</b>\nFrom: <b>{sname}</b>\n{when}",
    },
})
# ===================== БЛОК 6 / 14 — t(), КЛАВИАТУРЫ, УТИЛИТЫ =====================

# ---- Гармонизация эмодзи (перенос из ru в uz/en) ----
def _harmonize_translations():
    for _key, _block in T.items():
        if not isinstance(_block, dict):
            continue
        _ru = _block.get("ru")
        if not isinstance(_ru, str):
            continue
        _em = _leading_emoji(_ru)
        if not _em:
            continue
        for _lang in ("uz", "en"):
            _val = _block.get(_lang)
            if not isinstance(_val, str) or not _val:
                continue
            if not _leading_emoji(_val):
                _block[_lang] = _em + " " + _val.lstrip()


_harmonize_translations()


def t(key: str, **kw) -> str:
    """Перевод строки на текущий язык."""
    d = T.get(key, {})
    s = d.get(cur_lang()) or d.get("ru") or key
    return s.format(**kw) if kw else s


# ============================ ГЛАВНЫЕ КЛАВИАТУРЫ ============================
def main_menu_kb(tg_id: int):
    rows = [
        [KeyboardButton("🔗 Моя ссылка"), KeyboardButton("📍 Поблизости")],
        [KeyboardButton("🎲 Чат-рулетка"), KeyboardButton("👤 Профиль")],
        [KeyboardButton("🛒 Магазин"), KeyboardButton("👥 Пригласить")],
        [KeyboardButton("ℹ️ Помощь"), KeyboardButton("🌐 Язык")],
    ]
    try:
        if conn.execute("SELECT 1 FROM star_packages WHERE active=1 LIMIT 1").fetchone():
            rows.append([KeyboardButton(tr_btn("💎 Купить коины"))])
    except Exception:
        pass
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


def cancel_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))


def back_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))


def gender_kb(with_back: bool = False):
    rows = [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")]]
    if with_back:
        rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


def language_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇺🇿 O'zbekcha")],
        [KeyboardButton("🇬🇧 English")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


# ============================ ПРОФИЛЬ ============================
def profile_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("✏️ Сменить пол"), KeyboardButton("✏️ Изменить возраст")],
        [KeyboardButton("🎁 Подарить коины")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def age_back_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))


# ============================ ССЫЛКА ============================
def link_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔗 Показать ссылку"), KeyboardButton("✏️ Сменить ссылку")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def link_code_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))


def share_kb(link: str, text: str):
    share_url = (
        "https://t.me/share/url?url=" + urllib.parse.quote(link, safe="")
        + "&text=" + urllib.parse.quote(text, safe="")
    )
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_share"), url=share_url)]])


# ============================ АНОНИМКА ============================
def anon_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("❓ Вопрос"), KeyboardButton("💌 Валентинка")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def report_reason_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🤬 Мат"), KeyboardButton("💰 Мошенничество")],
        [KeyboardButton("😡 Оскорбление"), KeyboardButton("👎 Не нравится")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


# ============================ РУЛЕТКА ============================
def roulette_pref_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку"), KeyboardButton("🤷 Любого")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def searching_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⛔ Отменить поиск")]], resize_keyboard=True))


def in_chat_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➡️ Далее"), KeyboardButton("⏹️ Стоп")],
    ], resize_keyboard=True))


def left_chat_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Новый поиск")],
        [KeyboardButton("🚩 Пожаловаться"), KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


# ============================ ПОБЛИЗОСТИ ============================
def nearby_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Смотреть анкеты"), KeyboardButton("💕 Мои мэтчи")],
        [KeyboardButton("✏️ Редактировать анкету")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def nearby_gender_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def nearby_looking_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку")],
        [KeyboardButton("🤷 Любого")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def nearby_browse_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Смотреть анкеты")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def nearby_matches_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Смотреть анкеты")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


# ============================ РЕФЕРАЛЫ ============================
def referral_kb(uid: int | None = None):
    rows = [[KeyboardButton("🏆 Топ пригласивших")]]
    if uid is not None and is_admin(uid):
        rows.append([KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


def ref_settings_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("👑 VIP: дней"), KeyboardButton("👥 VIP: друзей")],
        [KeyboardButton("🛡 Модер: дней"), KeyboardButton("👥 Модер: друзей")],
        [KeyboardButton("📷 Фото"), KeyboardButton("🚫 Убрать фото")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True)


def ref_rewards_kb(uid: int, link: str | None = None):
    rows = []
    if link:
        full = link if link.startswith("http") else ("https://" + link)
        share_url = (
            "https://t.me/share/url?url=" + urllib.parse.quote(full, safe="")
            + "&text=" + urllib.parse.quote(t("ref_share_text"), safe="")
        )
        rows.append([InlineKeyboardButton(t("btn_share_ref"), url=share_url)])
    u = get_user(uid)
    n_coins = REF_REWARD_VIP if (u and is_vip(u)) else REF_REWARD_NORMAL
    rows += [
        [InlineKeyboardButton(
            t("ref_claim_coins_btn", n=n_coins, v=REF_REWARD_VIP),
            callback_data="ref_info")],
        [InlineKeyboardButton(t("ref_claim_vip_btn"), callback_data="claim_vip")],
        [InlineKeyboardButton(t("ref_claim_moder_btn"), callback_data="claim_moder")],
    ]
    return InlineKeyboardMarkup(rows)


# ============================ МАГАЗИН ============================
def reward_type_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("💎 Коины"), KeyboardButton("⏳ VIP")],
        [KeyboardButton("🛡 Модер"), KeyboardButton("📦 Вручную")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def shop_edit_item_kb(item):
    rows = [[KeyboardButton("📝 Название"), KeyboardButton("💰 Цена")]]
    if item["reward_type"] == "coins":
        rows.append([KeyboardButton("💎 Сумма коинов")])
    elif item["reward_type"] == "vip" or item["is_vip"]:
        rows.append([KeyboardButton("⏳ Срок VIP")])
    rows.append([KeyboardButton("🗑 Удалить товар")])
    rows.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


# ============================ АДМИНКА ============================
def admin_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("💰 Начислить коины"), KeyboardButton("👑 VIP по ID")],
        [KeyboardButton("📢 Обязательные каналы"), KeyboardButton("📢 Рассылка")],
        [KeyboardButton("🛡 Модеры"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("⭐ Коины за Stars")],
        [KeyboardButton("💎 Цена раскрытия")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def admin_moder_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Выдать модера"), KeyboardButton("➖ Забрать модера")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def admin_vip_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👑 VIP всем"), KeyboardButton("👑 VIP девушкам"), KeyboardButton("👑 VIP парням")],
        [KeyboardButton("➕ Выдать VIP"), KeyboardButton("➖ Забрать VIP")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def vip_bulk_menu_kb(bulk_filter: str):
    if bulk_filter == "all":
        give, take = "➕ Выдать VIP всем", "➖ Забрать у всех"
    elif bulk_filter == "female":
        give, take = "➕ Выдать VIP девушкам", "➖ Забрать у девушек"
    else:
        give, take = "➕ Выдать VIP парням", "➖ Забрать у парней"
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton(give), KeyboardButton(take)],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def star_admin_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить пакет коинов")],
        [KeyboardButton("🗑 Удалить пакет коинов")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))


def bcast_audience_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👥 Всем")],
        [KeyboardButton("👨 Мужчинам"), KeyboardButton("👩 Женщинам")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))


def adm_channels_kb(uid: int | None = None):
    rows = [
        [KeyboardButton("➕ Добавить канал")],
        [KeyboardButton("🗑 Удалить канал")],
    ]
    if uid is not None and is_admin(uid):
        enabled = get_setting("subgate_enabled", "0") == "1"
        toggle = "Подписка для входа: ВКЛ" if enabled else "Подписка для входа: ВЫКЛ"
        rows.append([KeyboardButton(toggle)])
    rows.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))


def moder_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🚩 Жалобы"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("📢 Обязательные каналы")],
        [KeyboardButton("ℹ️ Помощь")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))


def moder_decision_kb(app_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Выдать", callback_data=f"modapp:ok:{app_id}"),
        InlineKeyboardButton("Отказ", callback_data=f"modapp:no:{app_id}"),
    ]])


# ============================ ПОДПИСКА ============================
def subscribe_kb(msg_id: int, channels):
    rows = []
    for c in channels:
        url = channel_url(c["chat_username"])
        if is_valid_btn_url(url):
            rows.append([InlineKeyboardButton(channel_title(c), url=url)])
    rows.append([InlineKeyboardButton(t("btn_check_sub"), callback_data=f"subcheck:{msg_id}")])
    return InlineKeyboardMarkup(rows)


def subscribe_gate_kb(channels):
    rows = []
    for c in channels:
        url = channel_url(c["chat_username"])
        if is_valid_btn_url(url):
            rows.append([InlineKeyboardButton(channel_title(c), url=url)])
    rows.append([InlineKeyboardButton(t("btn_check_sub"), callback_data="subgate")])
    return InlineKeyboardMarkup(rows)


# ============================ КАНАЛЫ ============================
def channel_url(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return "https://" + raw
    return "https://t.me/" + raw.lstrip("@")


def is_valid_btn_url(url: str) -> bool:
    if not url or any(ch.isspace() for ch in url):
        return False
    low = url.lower()
    return low.startswith("https://") or low.startswith("http://") or low.startswith("tg://")


def channel_title(ch) -> str:
    try:
        ttl = ch["title"]
    except (KeyError, IndexError, TypeError):
        ttl = None
    if ttl:
        return ttl
    raw = (ch["chat_username"] or "").strip()
    name = raw.lstrip("@").rstrip("/").split("/")[-1]
    return "📢 " + (name or "Канал")


def _chat_ref_for_check(raw: str | None) -> str | None:
    raw = (raw or "").strip()
    if raw.startswith("@"):
        return raw
    low = raw.lower()
    if "t.me/" in low:
        tail = raw.split("t.me/", 1)[1].strip("/")
        if tail.startswith("+") or tail.lower().startswith("joinchat"):
            return None
        tail = tail.split("?")[0].split("/")[0]
        return "@" + tail if tail else None
    if raw and not raw.startswith("http"):
        return "@" + raw.lstrip("@")
    return None


def _ch_added_by(c) -> int | None:
    try:
        v = c["added_by"]
    except (KeyError, IndexError, TypeError):
        return None
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def channels_deletable_by(uid: int):
    chans = conn.execute("SELECT * FROM mandatory_channels").fetchall()
    if is_admin(uid):
        return chans
    uid = int(uid)
    return [c for c in chans if _ch_added_by(c) == uid]


async def get_mandatory_channels():
    return conn.execute("SELECT * FROM mandatory_channels").fetchall()


async def user_subscribed_all(context, user_id: int, channels) -> bool:
    for ch in channels:
        ref = _chat_ref_for_check(ch["chat_username"])
        if ref is None:
            continue
        try:
            member = await context.bot.get_chat_member(ref, user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except TelegramError:
            continue
    return True


# ============================ РЕФ-КОДЫ ============================
REF_CODE_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"


def get_or_create_ref_code(uid: int) -> str:
    u = get_user(uid)
    if u:
        try:
            if u["ref_code"]:
                return u["ref_code"]
        except (KeyError, IndexError, TypeError):
            pass
    for _ in range(50):
        code = "".join(random.choice(REF_CODE_CHARS) for _ in range(5))
        if not conn.execute("SELECT 1 FROM users WHERE ref_code=?", (code,)).fetchone():
            conn.execute("UPDATE users SET ref_code=? WHERE tg_id=?", (code, uid))
            conn.commit()
            return code
    return str(uid)


def resolve_ref_code(code: str) -> int | None:
    row = conn.execute("SELECT tg_id FROM users WHERE ref_code=?", (code,)).fetchone()
    if row:
        return row["tg_id"]
    if code.isdigit():
        old = conn.execute("SELECT tg_id FROM users WHERE tg_id=?", (int(code),)).fetchone()
        if old:
            return old["tg_id"]
    return None


def qualified_referrals(uid: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM referrals r JOIN users u ON u.tg_id=r.referred_id "
        "WHERE r.referrer_id=? AND r.active=1 AND u.custom_link IS NOT NULL",
        (uid,),
    ).fetchone()["c"]


def progress_bar(cur: int, target: int, slots: int = 10) -> str:
    if target <= 0:
        return ""
    filled = max(0, min(slots, round(slots * cur / target)))
    return "▰" * filled + "▱" * (slots - filled)


# ============================ LINK FLOW ============================
LINK_FLOW_TTL_HOURS = 6


def save_link_flow(user_id: int, target_id: int, state: str, msg_type: str | None = None):
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.execute(
            "INSERT INTO link_flow (user_id, target_id, msg_type, state, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, target_id, msg_type, state, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("save_link_flow: %s", e)


def load_link_flow(user_id: int):
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


def clear_link_flow(user_id: int):
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.commit()
    except Exception as e:
        log.warning("clear_link_flow: %s", e)


# ============================ BOT USERNAME ============================
_BOT_USERNAME: str | None = None


async def get_bot_username(context) -> str:
    global _BOT_USERNAME
    if _BOT_USERNAME is None:
        _BOT_USERNAME = (await context.bot.get_me()).username
    return _BOT_USERNAME


async def build_start_link(context, code: str) -> str:
    return f"t.me/{await get_bot_username(context)}?start={code}"


# ============================ АВТО-ПЕРЕВОД ТОВАРОВ ============================
def _translate_sync(text: str, target: str) -> str:
    if not text or not text.strip():
        return text
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            "&sl=auto&tl=" + urllib.parse.quote(target)
            + "&dt=t&q=" + urllib.parse.quote(text)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return out.strip() or text
    except Exception as e:
        log.warning("translate(%s): %s", target, e)
        return text


async def translate_to_all(text: str):
    ru = await asyncio.to_thread(_translate_sync, text, "ru")
    uz = await asyncio.to_thread(_translate_sync, text, "uz")
    en = await asyncio.to_thread(_translate_sync, text, "en")
    return ru or text, uz or text, en or text


def item_title(item) -> str:
    lang = cur_lang()
    try:
        if lang == "uz" and item["title_uz"]:
            return item["title_uz"]
        if lang == "en" and item["title_en"]:
            return item["title_en"]
    except (KeyError, IndexError, TypeError):
        pass
    return item["title"]
    # ===================== БЛОК 7 / 14 — НАВИГАЦИЯ И УТИЛИТЫ =====================

# ============================ НАВИГАЦИЯ ============================
async def clean_screen(update, context):
    """Удаляет нажатие пользователя + прошлые сообщения меню."""
    try:
        await update.message.delete()
    except TelegramError as e:
        log.debug("clean_screen: %s", e)
    for mid in context.user_data.pop("extra_msg_ids", []):
        await try_delete_message(context, update.effective_chat.id, mid)
    mid = context.user_data.pop("last_menu_msg_id", None)
    if mid:
        await try_delete_message(context, update.effective_chat.id, mid)


def track_extra(context, msg):
    """Запоминает доп. сообщение (карточку ссылки и т.п.) для удаления."""
    context.user_data.setdefault("extra_msg_ids", []).append(msg.message_id)


async def send_menu(update, context, text, reply_markup=None, parse_mode=None):
    """Отправляет новое меню и запоминает его ID."""
    msg = await context.bot.send_message(
        update.effective_chat.id, text,
        reply_markup=reply_markup, parse_mode=parse_mode,
    )
    context.user_data["last_menu_msg_id"] = msg.message_id
    return msg


async def nav(update, context, text, reply_markup=None, parse_mode=None):
    """Удаляет прошлый экран и показывает новый."""
    await clean_screen(update, context)
    return await send_menu(update, context, text, reply_markup, parse_mode)


async def go_home(update, context):
    """Возврат в главное меню + очистка."""
    context.user_data["state"] = None
    await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))


# ============================ УВЕДОМЛЕНИЯ ============================
async def notify_admins(context, text, reply_markup=None, parse_mode=None):
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramError:
            pass


async def notify_staff(context, text, reply_markup=None, parse_mode=None):
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


async def notify_admins_new_user(context, tg_user):
    uname = f"@{tg_user.username}" if getattr(tg_user, "username", None) else "—"
    name = html.escape(tg_user.first_name or "—")
    when = now_dt().strftime("%d.%m.%Y %H:%M")
    try:
        total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    except Exception:
        total = "?"
    text = (
        "🆕 <b>Новый пользователь!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Имя: <b>{name}</b>\n"
        f"ID: <code>{tg_user.id}</code>\n"
        f"Username: {uname}\n"
        f"Время: {when} (UTC)\n"
        f"Всего в боте: <b>{total}</b>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML")
        except TelegramError:
            pass


async def notify_admins_user_event(context, tg_user, kind, extra=None):
    uid = getattr(tg_user, "id", tg_user)
    uname = f"@{tg_user.username}" if getattr(tg_user, "username", None) else "—"
    name = html.escape(getattr(tg_user, "first_name", None) or "—")
    when = now_dt().strftime("%d.%m.%Y %H:%M")
    heads = {
        "blocked": "🚫 <b>Пользователь заблокировал бота</b>",
        "unblocked": "🔓 <b>Пользователь разблокировал бота</b>",
        "banned": "🔨 <b>Пользователь забанен</b>",
    }
    head = heads.get(kind, "📌 <b>Событие пользователя</b>")
    text = (
        f"{head}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Имя: <b>{name}</b>\n"
        f"ID: <code>{uid}</code>\n"
        f"Username: {uname}\n"
        f"Время: {when} (UTC)"
    )
    if extra:
        text += f"\n{extra}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML")
        except TelegramError:
            pass


# ============================ VIP БОНУС ============================
async def grant_daily_bonus(uid: int, context):
    u = get_user(uid)
    if not is_vip(u) or is_unlimited(u):
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if u["last_bonus"] == today:
        return
    conn.execute(
        "UPDATE users SET coins = coins + ?, last_bonus=? WHERE tg_id=?",
        (VIP_DAILY_BONUS, today, uid),
    )
    conn.commit()
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(uid))
        await context.bot.send_message(uid, t("vip_daily_bonus", n=VIP_DAILY_BONUS), parse_mode="HTML")
        set_cur_lang(_sl)
    except TelegramError as e:
        log.debug("grant_daily_bonus(%s): %s", uid, e)


# ============================ АВТО-МЕНЮ ============================
async def deliver_start_menu(context, uid: int, greet: bool = True):
    """Показывает меню с учётом регистрации."""
    user = get_user(uid)
    if not user:
        return
    _sl = cur_lang()
    set_cur_lang(get_lang(uid))
    name = html.escape(user["first_name"] or "друг")
    try:
        if not user["gender"]:
            UD[uid]["state"] = "set_gender_first"
            await context.bot.send_message(uid, t("welcome", name=name),
                                           parse_mode="HTML", reply_markup=gender_kb())
        elif user["age"] is None:
            UD[uid]["state"] = "set_age_first"
            await context.bot.send_message(uid, t("age_register_ask"),
                                           parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        elif greet:
            await context.bot.send_message(uid, t("welcome_back", name=name),
                                           parse_mode="HTML", reply_markup=main_menu_kb(uid))
        else:
            UD[uid]["state"] = None
            await context.bot.send_message(uid, t("main_menu"), reply_markup=main_menu_kb(uid))
    finally:
        set_cur_lang(_sl)


# ============================ РУЛЕТКА-УТИЛИТЫ ============================
def get_active_session(user_id: int):
    return conn.execute(
        "SELECT * FROM roulette_sessions WHERE active=1 AND (user1_id=? OR user2_id=?)",
        (user_id, user_id),
    ).fetchone()


def compatible(a, b) -> bool:
    a_ok = a["pref"] == "any" or a["pref"] == b["gender"]
    b_ok = b["pref"] == "any" or b["pref"] == a["gender"]
    return a_ok and b_ok


def is_banned_pair(u1, u2) -> bool:
    row = conn.execute(
        "SELECT 1 FROM bans WHERE until>? AND "
        "((owner_id=? AND banned_id=?) OR (owner_id=? AND banned_id=?))",
        (now_iso(), u1, u2, u2, u1),
    ).fetchone()
    return row is not None


async def relay_roulette_message(update, context) -> bool:
    """Пересылает сообщение собеседнику в рулетке."""
    session = get_active_session(update.effective_user.id)
    if not session:
        return False

    other_id = (
        session["user2_id"] if session["user1_id"] == update.effective_user.id
        else session["user1_id"]
    )

    try:
        sess_mode = session["mode"] or "normal"
    except (KeyError, IndexError, TypeError):
        sess_mode = "normal"

    txt = update.message.text if update.message else None
    if (sess_mode == "normal" and txt
            and not is_staff(update.effective_user.id)
            and has_forbidden_contacts(txt)):
        try:
            await update.message.reply_text(t("no_contacts"))
        except TelegramError:
            pass
        return True

    try:
        await context.bot.copy_message(
            other_id,
            update.effective_chat.id,
            update.message.message_id,
        )
    except TelegramError as e:
        log.warning("relay_roulette to %s: %s", other_id, e)

    # Трансляция наблюдателям /tg
    await relay_to_spectators(
        context, session, update.effective_user.id,
        update.effective_chat.id, update.message.message_id,
    )
    return True


# ============================ ССЫЛКА-УТИЛИТЫ ============================
LINK_ALPHABET = string.ascii_letters + string.digits + "_-"


def valid_link_code(code: str) -> bool:
    return 1 <= len(code) <= 10 and all(c in LINK_ALPHABET for c in code)


def can_change_link(user_row):
    """Смена ссылки: VIP — всегда, обычным — раз в 3 дня."""
    if is_vip(user_row):
        return True, None
    if not user_row["link_changed_at"]:
        return True, None
    try:
        last_change = datetime.fromisoformat(user_row["link_changed_at"])
        cooldown_end = last_change + timedelta(days=LINK_CHANGE_COOLDOWN_DAYS)
        if now_dt() >= cooldown_end:
            return True, None
        days_left = (cooldown_end - now_dt()).days + 1
        return False, t("link_limit", days=days_left)
    except (ValueError, TypeError):
        return True, None


# ============================ PURGE / DEAD ACCOUNT ============================
def user_is_disposable(uid: int) -> bool:
    """True, если аккаунт пустой и его безопасно удалить."""
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
    if conn.execute("SELECT 1 FROM star_purchases WHERE user_id=? LIMIT 1", (uid,)).fetchone():
        return False
    return True


def purge_user(uid: int, force: bool = False) -> bool:
    """Удаляет пользователя. Без force — только пустые."""
    try:
        if is_admin(uid):
            return False
        if not force and not user_is_disposable(uid):
            return False

        partner_rows = conn.execute(
            "SELECT user1_id, user2_id FROM roulette_sessions "
            "WHERE active=1 AND (user1_id=? OR user2_id=?)",
            (uid, uid),
        ).fetchall()
        partner_ids = {
            (r["user2_id"] if r["user1_id"] == uid else r["user1_id"])
            for r in partner_rows
        }

        conn.execute("DELETE FROM users WHERE tg_id=?", (uid,))
        conn.execute("DELETE FROM referrals WHERE referred_id=? OR referrer_id=?", (uid, uid))
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.execute(
            "UPDATE roulette_sessions SET active=0, ended_at=COALESCE(ended_at, ?) "
            "WHERE active=1 AND (user1_id=? OR user2_id=?)",
            (now_iso(), uid, uid),
        )
        conn.commit()

        if partner_ids:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_notify_purged_partners(partner_ids))
            except RuntimeError:
                pass
        return True
    except Exception as e:
        log.warning("purge_user %s: %s", uid, e)
        return False


async def _notify_purged_partners(partner_ids):
    for pid in partner_ids:
        try:
            UD[pid]["state"] = "rleft"
            _sl = cur_lang()
            set_cur_lang(get_lang(pid))
            try:
                await BOTP.send_message(pid, t("roulette_left"), reply_markup=left_chat_kb())
            finally:
                set_cur_lang(_sl)
        except TelegramError as e:
            log.warning("notify purged partner %s: %s", pid, e)


def _is_dead_account(err) -> bool:
    s = str(err).lower()
    keys = ("blocked", "deactivated", "chat not found", "user not found",
            "bot can't initiate", "bot was blocked", "user is deactivated",
            "peer_id_invalid", "forbidden")
    return any(k in s for k in keys)


def safe_purge_dead(uid: int) -> bool:
    if not user_is_disposable(uid):
        return False
    return purge_user(uid, force=False)


# ============================ ГЛОБАЛЬНЫЕ БУФЕРЫ ============================
BCAST_ALBUMS = {}                        # (uid, media_group_id) -> album data
SPECTATORS = {}                          # mod_id -> session_id
SESSION_SPECTATORS = defaultdict(set)    # session_id -> {mod_id}
# ===================== БЛОК 8 / 14 — /START И ПРОФИЛЬ =====================

# ============================ /start ============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    existed = get_user(tg_user.id) is not None
    user = ensure_user(tg_user.id, tg_user.username, tg_user.first_name)

    if is_banned(user) and not is_admin(tg_user.id):
        await update.message.reply_text(t("banned"))
        return

    if not existed and not is_admin(tg_user.id):
        await notify_admins_new_user(context, tg_user)

    await grant_daily_bonus(tg_user.id, context)

    args = context.args or []
    if args:
        code = args[0]
        if code.startswith("ref_"):
            await handle_referral(update, context, code, existed)
        else:
            await handle_incoming_link(update, context, code)
            return

    # Гейт подписки на вход
    if get_setting("subgate_enabled", "0") == "1" and not is_admin(tg_user.id):
        chans = await get_mandatory_channels()
        if chans and not await user_subscribed_all(context, tg_user.id, chans):
            await update.message.reply_text(
                t("subgate_start"), parse_mode="HTML",
                reply_markup=subscribe_gate_kb(chans),
            )
            return

    # Регистрация — пол
    if not user["gender"]:
        context.user_data["state"] = "set_gender_first"
        name = tg_user.first_name or "друг"
        await update.message.reply_text(
            t("welcome", name=html.escape(name)),
            parse_mode="HTML", reply_markup=gender_kb(),
        )
        return

    # Регистрация — возраст
    if user["age"] is None:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Кулдаун приветствия — 10 минут
    name = tg_user.first_name or "друг"
    show_greet = True
    try:
        last_greet_raw = user["last_greet"] if "last_greet" in user.keys() else None
        if last_greet_raw:
            try:
                if now_dt() - datetime.fromisoformat(last_greet_raw) < timedelta(minutes=WELCOME_COOLDOWN_MIN):
                    show_greet = False
            except (ValueError, TypeError):
                pass
    except (KeyError, IndexError):
        pass

    if show_greet:
        conn.execute("UPDATE users SET last_greet=? WHERE tg_id=?", (now_iso(), tg_user.id))
        conn.commit()
        await update.message.reply_text(
            t("welcome_back", name=html.escape(name)),
            parse_mode="HTML", reply_markup=main_menu_kb(tg_user.id),
        )
    else:
        await update.message.reply_text(
            t("main_menu"),
            reply_markup=main_menu_kb(tg_user.id),
        )


# ============================ ЯЗЫК ============================
async def show_language_menu(update, context):
    context.user_data["state"] = "language"
    await nav(update, context, t("lang_choose"), language_menu_kb())


async def language_router(update, context):
    text = canon(update.message.text)
    if text in ("Назад", "Меню", "Отмена"):
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


# ============================ ГЕНДЕР ============================
async def set_gender_from_text(update, context):
    text = canon(update.message.text)
    state = context.user_data.get("state")

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return

    gender = {"Мужской": "m", "Женский": "f"}.get(text)
    if not gender:
        await update.message.reply_text(
            t("pick_on_kb"),
            reply_markup=gender_kb(state == "set_gender_profile"),
        )
        return

    conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (gender, update.effective_user.id))
    conn.commit()

    g = {"m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
         "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"}}[gender][cur_lang()]

    user = get_user(update.effective_user.id)

    if state == "set_gender_first" and not user["age"]:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(t("gender_set_short", g=g), parse_mode="HTML")
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    context.user_data["state"] = None
    await update.message.reply_text(
        t("gender_saved", g=g), parse_mode="HTML",
        reply_markup=main_menu_kb(update.effective_user.id),
    )


# ============================ ВОЗРАСТ ============================
async def set_age_from_text(update, context):
    text = (update.message.text or "").strip()
    ctext = canon(text)
    state = context.user_data.get("state")
    uid = update.effective_user.id

    if ctext in ("Назад", "Отмена"):
        if state == "set_age_profile":
            await show_profile(update, context)
        else:
            context.user_data["state"] = None
            await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return

    if not text.isdigit():
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return

    new_age = int(text)
    if new_age < 5 or new_age > 99:
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return

    conn.execute("UPDATE users SET age=? WHERE tg_id=?", (str(new_age), uid))
    conn.commit()
    context.user_data["state"] = None
    await update.message.reply_text(
        t("age_saved", age=new_age), parse_mode="HTML",
        reply_markup=main_menu_kb(uid),
    )


# ============================ ПРОФИЛЬ ============================
async def show_profile(update, context):
    uid = update.effective_user.id
    user = get_user(uid)

    if is_unlimited(user):
        vip_status = t("vip_forever")
        coins_display = "∞"
    elif is_vip(user):
        try:
            vip_status = t("vip_until", date=user['vip_until'][:10])
        except (TypeError, KeyError):
            vip_status = t("vip_none")
        coins_display = user['coins']
    else:
        vip_status = t("vip_none")
        coins_display = user['coins']

    # Время в рулетке
    secs = 0
    for s in conn.execute(
        "SELECT started_at, ended_at FROM roulette_sessions WHERE user1_id=? OR user2_id=?",
        (uid, uid),
    ).fetchall():
        try:
            start = datetime.fromisoformat(s["started_at"])
            end = datetime.fromisoformat(s["ended_at"]) if s["ended_at"] else now_dt()
            secs += max(0, (end - start).total_seconds())
        except (ValueError, TypeError):
            continue

    sent = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE from_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    received = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE to_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    stars_spent = conn.execute(
        "SELECT COALESCE(SUM(stars),0) s FROM star_purchases WHERE user_id=? AND refunded=0",
        (uid,),
    ).fetchone()["s"]

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
        id=uid, name=html.escape(name),
        gender=gender_label(user['gender']),
        age=age_display,
        roulette_time=fmt_duration(secs),
        sent=sent, received=received,
        invited=invited, rank=rank,
        coins=coins_display, vip=vip_status,
        stars=stars_spent, reg_date=reg_date,
    )

    await clean_screen(update, context)
    context.user_data["state"] = "profile"
    await send_menu(update, context, text, profile_kb(), parse_mode="HTML")


async def profile_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return

    if text == "Сменить пол":
        context.user_data["state"] = "set_gender_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("choose_new_gender"), gender_kb(with_back=True))
        return

    if text == "Изменить возраст":
        context.user_data["state"] = "set_age_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("age_register_ask"), age_back_kb(), parse_mode="HTML")
        return

    if text == "Подарить коины":
        context.user_data["state"] = "giftcoins_id"
        await clean_screen(update, context)
        await send_menu(update, context, t("giftcoins_ask_id"), cancel_reply_kb(), parse_mode="HTML")
        return

    await context.bot.send_message(uid, t("choose_action"), reply_markup=profile_kb())


# ============================ ПОДАРОК КОИНОВ ============================
async def gift_coins_router(update, context):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    if canon(text) in ("Отмена", "Назад"):
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
        bal = get_user(uid)["coins"] or 0
        await update.message.reply_text(
            t("giftcoins_ask_amount", balance=bal),
            parse_mode="HTML", reply_markup=cancel_reply_kb(),
        )
        return

    if state == "giftcoins_amount":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text(t("giftcoins_amount_number"), reply_markup=cancel_reply_kb())
            return
        amount = int(text)
        user = get_user(uid)
        if not is_unlimited(user) and (user["coins"] or 0) < amount:
            await update.message.reply_text(
                t("giftcoins_not_enough", balance=user["coins"] or 0),
                reply_markup=cancel_reply_kb(),
            )
            return
        target = context.user_data.get("giftcoins_target")
        if not is_unlimited(user):
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (amount, uid))
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amount, target))
        conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("giftcoins_target", None)
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await context.bot.send_message(
                target, t("giftcoins_received", amount=amount),
                parse_mode="HTML", reply_markup=main_menu_kb(target),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await nav(
            update, context,
            t("giftcoins_sent", id=target, amount=amount),
            main_menu_kb(uid), parse_mode="HTML",
        )
        return
        # ===================== БЛОК 8 / 14 — /START И ПРОФИЛЬ =====================

# ============================ /start ============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    existed = get_user(tg_user.id) is not None
    user = ensure_user(tg_user.id, tg_user.username, tg_user.first_name)

    if is_banned(user) and not is_admin(tg_user.id):
        await update.message.reply_text(t("banned"))
        return

    if not existed and not is_admin(tg_user.id):
        await notify_admins_new_user(context, tg_user)

    await grant_daily_bonus(tg_user.id, context)

    args = context.args or []
    if args:
        code = args[0]
        if code.startswith("ref_"):
            await handle_referral(update, context, code, existed)
        else:
            await handle_incoming_link(update, context, code)
            return

    # Гейт подписки на вход
    if get_setting("subgate_enabled", "0") == "1" and not is_admin(tg_user.id):
        chans = await get_mandatory_channels()
        if chans and not await user_subscribed_all(context, tg_user.id, chans):
            await update.message.reply_text(
                t("subgate_start"), parse_mode="HTML",
                reply_markup=subscribe_gate_kb(chans),
            )
            return

    # Регистрация — пол
    if not user["gender"]:
        context.user_data["state"] = "set_gender_first"
        name = tg_user.first_name or "друг"
        await update.message.reply_text(
            t("welcome", name=html.escape(name)),
            parse_mode="HTML", reply_markup=gender_kb(),
        )
        return

    # Регистрация — возраст
    if user["age"] is None:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Кулдаун приветствия — 10 минут
    name = tg_user.first_name or "друг"
    show_greet = True
    try:
        last_greet_raw = user["last_greet"] if "last_greet" in user.keys() else None
        if last_greet_raw:
            try:
                if now_dt() - datetime.fromisoformat(last_greet_raw) < timedelta(minutes=WELCOME_COOLDOWN_MIN):
                    show_greet = False
            except (ValueError, TypeError):
                pass
    except (KeyError, IndexError):
        pass

    if show_greet:
        conn.execute("UPDATE users SET last_greet=? WHERE tg_id=?", (now_iso(), tg_user.id))
        conn.commit()
        await update.message.reply_text(
            t("welcome_back", name=html.escape(name)),
            parse_mode="HTML", reply_markup=main_menu_kb(tg_user.id),
        )
    else:
        await update.message.reply_text(
            t("main_menu"),
            reply_markup=main_menu_kb(tg_user.id),
        )


# ============================ ЯЗЫК ============================
async def show_language_menu(update, context):
    context.user_data["state"] = "language"
    await nav(update, context, t("lang_choose"), language_menu_kb())


async def language_router(update, context):
    text = canon(update.message.text)
    if text in ("Назад", "Меню", "Отмена"):
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


# ============================ ГЕНДЕР ============================
async def set_gender_from_text(update, context):
    text = canon(update.message.text)
    state = context.user_data.get("state")

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return

    gender = {"Мужской": "m", "Женский": "f"}.get(text)
    if not gender:
        await update.message.reply_text(
            t("pick_on_kb"),
            reply_markup=gender_kb(state == "set_gender_profile"),
        )
        return

    conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (gender, update.effective_user.id))
    conn.commit()

    g = {"m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
         "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"}}[gender][cur_lang()]

    user = get_user(update.effective_user.id)

    if state == "set_gender_first" and not user["age"]:
        context.user_data["state"] = "set_age_first"
        await update.message.reply_text(t("gender_set_short", g=g), parse_mode="HTML")
        await update.message.reply_text(
            t("age_register_ask"), parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    context.user_data["state"] = None
    await update.message.reply_text(
        t("gender_saved", g=g), parse_mode="HTML",
        reply_markup=main_menu_kb(update.effective_user.id),
    )


# ============================ ВОЗРАСТ ============================
async def set_age_from_text(update, context):
    text = (update.message.text or "").strip()
    ctext = canon(text)
    state = context.user_data.get("state")
    uid = update.effective_user.id

    if ctext in ("Назад", "Отмена"):
        if state == "set_age_profile":
            await show_profile(update, context)
        else:
            context.user_data["state"] = None
            await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return

    if not text.isdigit():
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return

    new_age = int(text)
    if new_age < 5 or new_age > 99:
        await update.message.reply_text(t("age_enter_number"), parse_mode="HTML")
        return

    conn.execute("UPDATE users SET age=? WHERE tg_id=?", (str(new_age), uid))
    conn.commit()
    context.user_data["state"] = None
    await update.message.reply_text(
        t("age_saved", age=new_age), parse_mode="HTML",
        reply_markup=main_menu_kb(uid),
    )


# ============================ ПРОФИЛЬ ============================
async def show_profile(update, context):
    uid = update.effective_user.id
    user = get_user(uid)

    if is_unlimited(user):
        vip_status = t("vip_forever")
        coins_display = "∞"
    elif is_vip(user):
        try:
            vip_status = t("vip_until", date=user['vip_until'][:10])
        except (TypeError, KeyError):
            vip_status = t("vip_none")
        coins_display = user['coins']
    else:
        vip_status = t("vip_none")
        coins_display = user['coins']

    # Время в рулетке
    secs = 0
    for s in conn.execute(
        "SELECT started_at, ended_at FROM roulette_sessions WHERE user1_id=? OR user2_id=?",
        (uid, uid),
    ).fetchall():
        try:
            start = datetime.fromisoformat(s["started_at"])
            end = datetime.fromisoformat(s["ended_at"]) if s["ended_at"] else now_dt()
            secs += max(0, (end - start).total_seconds())
        except (ValueError, TypeError):
            continue

    sent = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE from_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    received = conn.execute(
        "SELECT COUNT(*) c FROM anon_messages WHERE to_id=? AND msg_type IN ('question','valentine')",
        (uid,),
    ).fetchone()["c"]
    stars_spent = conn.execute(
        "SELECT COALESCE(SUM(stars),0) s FROM star_purchases WHERE user_id=? AND refunded=0",
        (uid,),
    ).fetchone()["s"]

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
        id=uid, name=html.escape(name),
        gender=gender_label(user['gender']),
        age=age_display,
        roulette_time=fmt_duration(secs),
        sent=sent, received=received,
        invited=invited, rank=rank,
        coins=coins_display, vip=vip_status,
        stars=stars_spent, reg_date=reg_date,
    )

    await clean_screen(update, context)
    context.user_data["state"] = "profile"
    await send_menu(update, context, text, profile_kb(), parse_mode="HTML")


async def profile_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return

    if text == "Сменить пол":
        context.user_data["state"] = "set_gender_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("choose_new_gender"), gender_kb(with_back=True))
        return

    if text == "Изменить возраст":
        context.user_data["state"] = "set_age_profile"
        await clean_screen(update, context)
        await send_menu(update, context, t("age_register_ask"), age_back_kb(), parse_mode="HTML")
        return

    if text == "Подарить коины":
        context.user_data["state"] = "giftcoins_id"
        await clean_screen(update, context)
        await send_menu(update, context, t("giftcoins_ask_id"), cancel_reply_kb(), parse_mode="HTML")
        return

    await context.bot.send_message(uid, t("choose_action"), reply_markup=profile_kb())


# ============================ ПОДАРОК КОИНОВ ============================
async def gift_coins_router(update, context):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    if canon(text) in ("Отмена", "Назад"):
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
        bal = get_user(uid)["coins"] or 0
        await update.message.reply_text(
            t("giftcoins_ask_amount", balance=bal),
            parse_mode="HTML", reply_markup=cancel_reply_kb(),
        )
        return

    if state == "giftcoins_amount":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text(t("giftcoins_amount_number"), reply_markup=cancel_reply_kb())
            return
        amount = int(text)
        user = get_user(uid)
        if not is_unlimited(user) and (user["coins"] or 0) < amount:
            await update.message.reply_text(
                t("giftcoins_not_enough", balance=user["coins"] or 0),
                reply_markup=cancel_reply_kb(),
            )
            return
        target = context.user_data.get("giftcoins_target")
        if not is_unlimited(user):
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (amount, uid))
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amount, target))
        conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("giftcoins_target", None)
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await context.bot.send_message(
                target, t("giftcoins_received", amount=amount),
                parse_mode="HTML", reply_markup=main_menu_kb(target),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await nav(
            update, context,
            t("giftcoins_sent", id=target, amount=amount),
            main_menu_kb(uid), parse_mode="HTML",
        )
        return
        # ===================== БЛОК 9 / 14 — ССЫЛКА И АНОНИМКА =====================

# ============================ ССЫЛКА ============================
async def show_link_menu(update, context):
    await clean_screen(update, context)
    context.user_data["state"] = "link_menu"
    await send_menu(update, context, t("link_section"), link_menu_kb(), parse_mode="HTML")


async def link_menu_router(update, context):
    text = canon(update.message.text)
    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return
    if text == "Показать ссылку":
        await show_my_link(update, context)
        return
    if text == "Сменить ссылку":
        await start_change_link(update, context)
        return
    await update.message.reply_text(t("link_menu"), reply_markup=link_menu_kb())


async def show_my_link(update, context):
    """Показывает активную ссылку (и старую, если ещё жива)."""
    user = get_user(update.effective_user.id)
    if not user["custom_link"]:
        context.user_data["state"] = "awaiting_link_code"
        await nav(update, context, t("link_no_link"), link_code_kb())
        return

    await clean_screen(update, context)

    link = await build_start_link(context, user["custom_link"])
    text = t("link_show", link=html.escape(link))

    # Старая ссылка (если ещё активна — 24 часа)
    try:
        old = user["old_link"]
        old_until = user["old_link_until"]
        if old and old_until:
            try:
                if datetime.fromisoformat(old_until) > now_dt():
                    old_link = await build_start_link(context, old)
                    text += (
                        "\n\n<b>Предыдущая ссылка</b> (работает до "
                        + old_until[:16].replace("T", " ")
                        + " UTC):\n<blockquote>"
                        + html.escape(old_link)
                        + "</blockquote>"
                    )
            except (ValueError, TypeError):
                pass
    except (KeyError, IndexError):
        pass

    msg = await context.bot.send_message(
        update.effective_chat.id, text,
        parse_mode="HTML",
        reply_markup=share_kb(link, t("share_text")),
    )
    track_extra(context, msg)
    await send_menu(update, context, t("link_section"), link_menu_kb(), parse_mode="HTML")


async def start_change_link(update, context):
    user = get_user(update.effective_user.id)
    can_change, error_msg = can_change_link(user)
    if not can_change:
        await clean_screen(update, context)
        await send_menu(update, context, error_msg, link_menu_kb())
        return
    context.user_data["state"] = "awaiting_link_code"
    await nav(update, context, t("link_change"), link_code_kb())


async def process_link_code(update, context, code):
    code = (code or "").strip()
    if canon(code) in ("Отмена", "Назад"):
        context.user_data["state"] = "link_menu"
        await show_link_menu(update, context)
        return
    if not valid_link_code(code):
        await update.message.reply_text(t("link_invalid"), reply_markup=link_code_kb())
        return

    uid = update.effective_user.id
    exists = conn.execute("SELECT tg_id FROM users WHERE custom_link=?", (code,)).fetchone()
    if exists and exists["tg_id"] != uid:
        await update.message.reply_text(t("link_taken"), reply_markup=link_code_kb())
        return

    # Сохраняем старую ссылку на 24 часа
    user = get_user(uid)
    old_link = user["custom_link"] if user else None
    old_until = None
    if old_link and old_link != code:
        try:
            old_until = (now_dt() + timedelta(hours=LINK_OLD_TTL_HOURS)).isoformat()
        except Exception:
            old_until = None

    conn.execute(
        "UPDATE users SET custom_link=?, old_link=?, old_link_until=?, link_changed_at=? WHERE tg_id=?",
        (code, old_link, old_until, now_iso(), uid),
    )
    conn.commit()

    context.user_data["state"] = "link_menu"
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


# ============================ ВХОД ПО ССЫЛКЕ ============================
async def handle_incoming_link(update, context, code):
    sender_id = update.effective_user.id
    sender_row = ensure_user(sender_id, update.effective_user.username, update.effective_user.first_name)

    if is_banned(sender_row):
        await update.message.reply_text(t("banned"))
        return

    # Ищем владельца: сначала по активной, потом по старой (если жива)
    owner = conn.execute("SELECT * FROM users WHERE custom_link=?", (code,)).fetchone()
    if not owner:
        owner = conn.execute(
            "SELECT * FROM users WHERE old_link=? AND old_link_until > ?",
            (code, now_iso()),
        ).fetchone()

    if not owner:
        await update.message.reply_text(t("anon_invalid_link"))
        await deliver_start_menu(context, sender_id, greet=False)
        return

    if owner["tg_id"] == sender_id:
        await update.message.reply_text(t("anon_own_link"), reply_markup=main_menu_kb(sender_id))
        return

    ban = conn.execute(
        "SELECT * FROM bans WHERE owner_id=? AND banned_id=? AND until>?",
        (owner["tg_id"], sender_id, now_iso()),
    ).fetchone()
    if ban:
        await update.message.reply_text(t("anon_banned"))
        await deliver_start_menu(context, sender_id, greet=False)
        return

    context.user_data["state"] = "awaiting_anon_type"
    context.user_data["anon_target"] = owner["tg_id"]
    save_link_flow(sender_id, owner["tg_id"], "awaiting_anon_type")
    await update.message.reply_text(t("anon_what_send"), reply_markup=anon_type_kb())


async def on_anon_type_text(update, context):
    text = canon(update.message.text)

    if text == "Отмена":
        context.user_data["state"] = None
        context.user_data.pop("anon_target", None)
        clear_link_flow(update.effective_user.id)
        await deliver_start_menu(context, update.effective_user.id, greet=False)
        return

    if text == "Вопрос":
        msg_type = "question"
    elif text == "Валентинка":
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
        reply_markup=ReplyKeyboardRemove(),
    )


# ============================ ДОСТАВКА АНОНИМКИ ============================
def anon_header(msg_type: str) -> str:
    return {
        "question": t("anon_hdr_question"),
        "valentine": t("anon_hdr_valentine"),
        "reply": t("anon_hdr_reply"),
    }.get(msg_type, t("anon_hdr_new"))


def anon_preview(row) -> str:
    if not row:
        return ""
    if row["content_type"] == "text" and row["text"]:
        p = row["text"]
    elif row["content_type"] == "voice":
        p = t("preview_voice")
    else:
        p = t("preview_media")
    return p[:150] + "…" if len(p) > 150 else p


async def extract_anon_content(update, is_v: bool):
    m = update.message
    is_media = bool(m.photo or m.sticker or m.animation or m.video or m.video_note or m.document)

    if m.text:
        return "text", m.text, None
    if m.voice:
        return "voice", None, m.voice.file_id
    if is_media:
        if not is_v:
            await update.message.reply_text(t("anon_vip_media"))
            return None
        return "media", None, None

    await update.message.reply_text(
        t("anon_formats", vip=t("anon_formats_vip") if is_v else "")
    )
    return None


async def deliver_anon(context, author_id, recipient_id, msg_type, content_type,
                       text=None, voice_file_id=None,
                       src_chat_id=None, src_message_id=None,
                       parent_id=None, allow_report=True, vip_badge=False):
    ban = conn.execute(
        "SELECT 1 FROM bans WHERE owner_id=? AND banned_id=? AND until>?",
        (recipient_id, author_id, now_iso()),
    ).fetchone()
    if ban:
        return None

    cur = conn.execute(
        "INSERT INTO anon_messages (from_id, to_id, msg_type, content_type, text, voice_file_id, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (author_id, recipient_id, msg_type, content_type, text, voice_file_id, parent_id, now_iso()),
    )
    conn.commit()
    mid = cur.lastrowid

    _saved_lang = cur_lang()
    set_cur_lang(get_lang(recipient_id))

    quote = ""
    if parent_id:
        parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (parent_id,)).fetchone()
        prev = anon_preview(parent)
        if prev:
            quote = f"{t('anon_quote_reply')}\n<blockquote>{html.escape(prev)}</blockquote>\n"

    header = anon_header(msg_type)
    buttons = [[
        InlineKeyboardButton(t("btn_reply"), callback_data=f"reply:{mid}"),
        InlineKeyboardButton(t("btn_report"), callback_data=f"report_anon:{mid}"),
    ]]
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
        else:
            sent = await context.bot.copy_message(
                recipient_id, src_chat_id, src_message_id,
                caption=f"{quote}{header}:", parse_mode="HTML", reply_markup=kb,
            )
    except TelegramError as e:
        log.warning("deliver_anon to %s: %s", recipient_id, e)
        set_cur_lang(_saved_lang)
        return None

    conn.execute("UPDATE anon_messages SET owner_chat_message_id=? WHERE id=?", (sent.message_id, mid))
    conn.commit()

    set_cur_lang(_saved_lang)

    del_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_delete"), callback_data=f"del:{mid}")]])
    try:
        author_msg = await context.bot.send_message(author_id, t("anon_sent"), reply_markup=del_kb)
        conn.execute("UPDATE anon_messages SET sender_chat_message_id=? WHERE id=?", (author_msg.message_id, mid))
        conn.commit()
    except TelegramError:
        pass

    # Трансляция наблюдателям /anon
    await relay_to_anon_watchers(context, recipient_id, mid)

    return mid


# ============================ ОБРАБОТКА КОНТЕНТА ============================
async def process_anon_content(update, context):
    sender = update.effective_user
    sender_row = ensure_user(sender.id, sender.username, sender.first_name)
    target_id = context.user_data.get("anon_target")
    msg_type = context.user_data.get("anon_type")
    is_v = is_vip(sender_row)

    if not is_v:
        since = (now_dt() - timedelta(days=1)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) c FROM anon_messages "
            "WHERE from_id=? AND msg_type IN ('question','valentine') AND created_at>?",
            (sender.id, since),
        ).fetchone()["c"]
        if count >= DAILY_LIMIT:
            await update.message.reply_text(
                t("anon_limit", n=DAILY_LIMIT),
                reply_markup=main_menu_kb(sender.id),
            )
            context.user_data["state"] = None
            clear_link_flow(sender.id)
            return

    extracted = await extract_anon_content(update, is_v)
    if extracted is None:
        return
    content_type, text, voice_file_id = extracted

    if content_type == "text" and not is_staff(sender.id) and has_forbidden_contacts(text):
        await update.message.reply_text(t("no_contacts"))
        return

    m = update.message
    mid = await deliver_anon(
        context, author_id=sender.id, recipient_id=target_id,
        msg_type=msg_type, content_type=content_type,
        text=text, voice_file_id=voice_file_id,
        src_chat_id=m.chat_id, src_message_id=m.message_id,
        parent_id=None, allow_report=True, vip_badge=is_v,
    )

    context.user_data["state"] = None
    context.user_data.pop("anon_target", None)
    context.user_data.pop("anon_type", None)
    clear_link_flow(sender.id)

    if mid is None:
        await context.bot.send_message(sender.id, t("anon_failed"))
        await deliver_start_menu(context, sender.id, greet=False)
        return

    await reward_link_activity(context, sender.id, "sent")
    await deliver_start_menu(context, sender.id, greet=False)


# ============================ ОТВЕТ НА АНОНИМКУ ============================
async def on_reply_button(update, context):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split(":")[1])
    context.user_data["state"] = "awaiting_reply"
    context.user_data["reply_target_msg"] = msg_id

    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    reply_to = row["owner_chat_message_id"] if row else None

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

    recipient_id = parent["from_id"] if replier.id == parent["to_id"] else parent["to_id"]
    is_v = is_vip(replier_row)

    extracted = await extract_anon_content(update, is_v)
    if extracted is None:
        return
    content_type, text, voice_file_id = extracted

    if content_type == "text" and not is_staff(replier.id) and has_forbidden_contacts(text):
        await update.message.reply_text(t("no_contacts"))
        return

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


# ============================ УДАЛЕНИЕ АНОНИМКИ ============================
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
    if row["owner_chat_message_id"]:
        try:
            await context.bot.delete_message(row["to_id"], row["owner_chat_message_id"])
            deleted_recipient = True
        except TelegramError:
            pass

    if row["sender_chat_message_id"]:
        try:
            await context.bot.delete_message(row["from_id"], row["sender_chat_message_id"])
        except TelegramError:
            pass

    try:
        await query.message.delete()
    except TelegramError:
        pass

    conn.execute("UPDATE anon_messages SET deleted=1 WHERE id=?", (msg_id,))
    conn.commit()

    if deleted_recipient:
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(row["to_id"]))
            await context.bot.send_message(row["to_id"], t("anon_deleted_notice"))
            set_cur_lang(_sl)
        except TelegramError:
            pass

    try:
        await query.answer(
            t("del_both") if deleted_recipient else t("del_only_me"),
            show_alert=True,
        )
    except TelegramError:
        pass


# ============================ ЖАЛОБА ============================
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

    if text == "Отмена":
        context.user_data["state"] = None
        for k in ("report_context", "report_ref_id", "reported_id"):
            context.user_data.pop(k, None)
        await update.message.reply_text(
            t("report_cancelled"), reply_markup=main_menu_kb(update.effective_user.id),
        )
        return

    reason_map = {
        "Мат": "Мат",
        "Мошенничество": "Мошенничество",
        "Оскорбление": "Оскорбление",
        "Не нравится": "Не нравится",
    }
    reason = reason_map.get(text)
    if not reason:
        await update.message.reply_text(t("pick_on_kb"), reply_markup=report_reason_kb())
        return

    ctx = context.user_data.get("report_context")
    ref_id = context.user_data.get("report_ref_id")
    reported_id = context.user_data.get("reported_id")

    cur = conn.execute(
        "INSERT INTO reports (reporter_id, reported_id, context, reason, ref_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (update.effective_user.id, reported_id, ctx, reason, ref_id, now_iso()),
    )
    conn.commit()
    report_id = cur.lastrowid

    await update.message.reply_text(
        t("report_sent"), reply_markup=main_menu_kb(update.effective_user.id),
    )
    context.user_data["state"] = None
    for k in ("report_context", "report_ref_id", "reported_id"):
        context.user_data.pop(k, None)

    if ctx == "anon":
        msg = conn.execute("SELECT * FROM anon_messages WHERE id=?", (ref_id,)).fetchone()
        content_preview = msg["text"] if msg and msg["content_type"] == "text" else "[голосовое]"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Бан навсегда", callback_data=f"repadm:ok:{report_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"repadm:no:{report_id}"),
        ]])
        await notify_staff(
            context,
            f"🚩 Жалоба на анонимку #{ref_id}\n"
            f"Причина: {reason}\nТип: {msg['msg_type'] if msg else '?'}\n"
            f"Содержание: {content_preview}",
            reply_markup=kb,
        )
    else:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Бан 30 дн.", callback_data=f"repadm:ok:{report_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"repadm:no:{report_id}"),
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
        if is_staff(report["reported_id"]):
            conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (report_id,))
            conn.commit()
            await query.edit_message_text(t("cant_ban_staff"))
            return

        is_anon = report["context"] == "anon"
        until = ANON_BAN_FOREVER if is_anon else (now_dt() + timedelta(days=ROULETTE_BAN_DAYS)).isoformat()
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
                report["reporter_id"],
                t("report_confirmed_forever") if is_anon
                else t("report_confirmed_user", days=ROULETTE_BAN_DAYS),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass

        try:
            _sl2 = cur_lang()
            set_cur_lang(get_lang(report["reported_id"]))
            await context.bot.send_message(
                report["reported_id"],
                t("you_were_banned_forever") if is_anon
                else t("you_were_banned", days=ROULETTE_BAN_DAYS),
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


# ============================ РЕФЕРАЛЫ: НАЧИСЛЕНИЕ ============================
async def handle_referral(update, context, code: str, existed: bool):
    if existed:
        return

    inviter_id = resolve_ref_code(code[4:])
    if inviter_id is None:
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
    invited_bonus = REF_INVITED_BONUS_VIP if is_vip(inviter) else REF_INVITED_BONUS

    conn.execute(
        "INSERT INTO referrals (referrer_id, referred_id, coins_awarded, active, created_at) "
        "VALUES (?, ?, ?, 1, ?)",
        (inviter_id, uid, reward, now_iso()),
    )
    conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (reward, inviter_id))
    conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (invited_bonus, uid))
    conn.commit()

    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(inviter_id))
        await context.bot.send_message(
            inviter_id, t("ref_friend_joined", reward=reward), parse_mode="HTML",
        )
        set_cur_lang(_sl)
    except TelegramError:
        pass

    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(uid))
        await context.bot.send_message(
            uid, t("ref_welcome_bonus", n=invited_bonus), parse_mode="HTML",
        )
        set_cur_lang(_sl)
    except TelegramError:
        pass


async def reward_link_activity(context, uid: int, kind: str):
    """Бонус +20 коинов за каждые 10 действий по ссылке. VIP — без бонуса."""
    u = get_user(uid)
    if not u or is_vip(u):
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
            _sl = cur_lang()
            set_cur_lang(get_lang(uid))
            await context.bot.send_message(
                uid, t("link_reward", coins=reward, n=total), parse_mode="HTML",
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
    else:
        conn.execute(f"UPDATE users SET {col_total}=? WHERE tg_id=?", (total, uid))
        conn.commit()
        # ===================== БЛОК 10 / 14 — РУЛЕТКА И ПОБЛИЗОСТИ =====================

# ============================ РУЛЕТКА: ВХОД ============================
async def show_roulette_entry(update, context):
    user = get_user(update.effective_user.id)
    active = get_active_session(user["tg_id"])
    await clean_screen(update, context)

    if active:
        UD[user["tg_id"]]["state"] = "rchat"
        await context.bot.send_message(
            update.effective_chat.id, t("roulette_already_chat"), reply_markup=in_chat_kb(),
        )
        return

    in_queue = conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (user["tg_id"],)).fetchone()
    if in_queue:
        await context.bot.send_message(
            update.effective_chat.id, t("roulette_searching"), reply_markup=searching_kb(),
        )
        return

    context.user_data["state"] = "roulette_pref"
    await send_menu(update, context, t("roulette_who"), roulette_pref_reply_kb())


async def roulette_pref_router(update, context):
    text = canon(update.message.text)

    if text in ("Назад", "Меню", "Отмена"):
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return

    pref = {"Парня": "m", "Девушку": "f", "Любого": "any"}.get(text)
    if not pref:
        await context.bot.send_message(
            update.effective_chat.id, t("pick_on_kb"), reply_markup=roulette_pref_reply_kb(),
        )
        return

    user = get_user(update.effective_user.id)
    if not user["gender"]:
        context.user_data["state"] = "set_gender_first"
        await context.bot.send_message(
            update.effective_chat.id, t("gender_needed_for_search"),
            reply_markup=gender_kb(with_back=False),
        )
        return

    conn.execute("UPDATE users SET search_pref=? WHERE tg_id=?", (pref, user["tg_id"]))
    conn.execute(
        "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) "
        "VALUES (?, ?, ?, ?, 'normal', ?) "
        "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, "
        "is_vip=excluded.is_vip, mode=excluded.mode, joined_at=excluded.joined_at",
        (user["tg_id"], user["gender"], pref, 1 if is_vip(user) else 0, now_iso()),
    )
    conn.commit()
    context.user_data["state"] = None
    await clean_screen(update, context)
    await context.bot.send_message(
        update.effective_chat.id, t("roulette_finding_partner"), reply_markup=searching_kb(),
    )


async def on_roulette_cancel(update, context):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
    conn.commit()
    try:
        await query.edit_message_text(t("roulette_stop"))
    except TelegramError:
        pass
    context.user_data["state"] = "roulette_pref"
    await context.bot.send_message(uid, t("roulette_who"), reply_markup=roulette_pref_reply_kb())


# ============================ МАТЧМЕЙКЕР ============================
async def roulette_matchmaker(context):
    rows = conn.execute(
        "SELECT * FROM roulette_queue WHERE mode='normal' ORDER BY is_vip DESC, joined_at ASC"
    ).fetchall()
    matched_ids = set()

    for i, a in enumerate(rows):
        if a["user_id"] in matched_ids:
            continue
        for b in rows[i + 1:]:
            if b["user_id"] in matched_ids:
                continue
            if not compatible(a, b):
                continue
            if is_banned_pair(a["user_id"], b["user_id"]):
                continue

            conn.execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", (a["user_id"], b["user_id"]))
            conn.execute(
                "INSERT INTO roulette_sessions (user1_id, user2_id, active, mode, started_at) "
                "VALUES (?, ?, 1, 'normal', ?)",
                (a["user_id"], b["user_id"], now_iso()),
            )
            conn.commit()
            matched_ids.add(a["user_id"])
            matched_ids.add(b["user_id"])

            for uid in (a["user_id"], b["user_id"]):
                try:
                    _sl = cur_lang()
                    set_cur_lang(get_lang(uid))
                    await context.bot.send_message(
                        uid, t("roulette_found"),
                        parse_mode="HTML", reply_markup=in_chat_kb(),
                    )
                    UD[uid]["state"] = "rchat"
                    set_cur_lang(_sl)
                except TelegramError:
                    pass
            break


# ============================ ЗАВЕРШЕНИЕ СЕССИЙ ============================
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

    await handle_spectators_on_end(context, session["id"])

    UD[other_id]["state"] = "rleft"
    UD[other_id]["last_session"] = session["id"]

    _sl = cur_lang()
    set_cur_lang(get_lang(other_id))
    try:
        await context.bot.send_message(other_id, t("roulette_left"), reply_markup=left_chat_kb())
    except TelegramError as e:
        log.warning("end_roulette_session to %s: %s", other_id, e)
    set_cur_lang(_sl)

    if requeue_ender:
        user = get_user(ender_id)
        if not user or not user["gender"]:
            return session
        pref = user["search_pref"] or "any"
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) "
            "VALUES (?, ?, ?, ?, 'normal', ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, "
            "is_vip=excluded.is_vip, mode=excluded.mode, joined_at=excluded.joined_at",
            (ender_id, user["gender"], pref, 1 if is_vip(user) else 0, now_iso()),
        )
        conn.commit()

    return session


async def force_end_session(context, session_id):
    s = conn.execute("SELECT * FROM roulette_sessions WHERE id=? AND active=1", (session_id,)).fetchone()
    if not s:
        return

    conn.execute("UPDATE roulette_sessions SET active=0, ended_at=? WHERE id=?", (now_iso(), session_id))
    conn.execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", (s["user1_id"], s["user2_id"]))
    conn.commit()

    await handle_spectators_on_end(context, session_id)

    for uid in (s["user1_id"], s["user2_id"]):
        st = (UD.get(uid) or {}).get("state")
        if st in ("rchat", "nearby_chat"):
            UD[uid]["state"] = "rleft"
            UD[uid]["last_session"] = session_id
            try:
                _sl = cur_lang()
                set_cur_lang(get_lang(uid))
                await context.bot.send_message(uid, t("roulette_left"), reply_markup=left_chat_kb())
                set_cur_lang(_sl)
            except TelegramError:
                pass


async def end_dead_sessions(context):
    rows = conn.execute("SELECT * FROM roulette_sessions WHERE active=1").fetchall()
    ended = 0
    for s in rows:
        if get_user(s["user1_id"]) is None or get_user(s["user2_id"]) is None:
            await force_end_session(context, s["id"])
            ended += 1
    if ended:
        log.info("end_dead_sessions: завершено %d", ended)


# ============================ ОБСЛУЖИВАНИЕ ОЧЕРЕДИ ============================
_QUEUE_REMIND = {}


async def queue_maintenance(context):
    now = now_dt()
    rows = conn.execute("SELECT * FROM roulette_queue").fetchall()
    alive_ids = set()

    for r in rows:
        uid = r["user_id"]
        alive_ids.add(uid)
        try:
            joined = datetime.fromisoformat(r["joined_at"])
        except (ValueError, TypeError):
            continue
        mins = (now - joined).total_seconds() / 60.0

        if mins >= SEARCH_TIMEOUT_MIN:
            conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
            conn.commit()
            _QUEUE_REMIND.pop(uid, None)
            if UD.get(uid):
                UD[uid]["state"] = None
            try:
                _sl = cur_lang()
                set_cur_lang(get_lang(uid))
                await context.bot.send_message(
                    uid, t("search_timeout", min=SEARCH_TIMEOUT_MIN),
                    parse_mode="HTML", reply_markup=main_menu_kb(uid),
                )
                set_cur_lang(_sl)
            except TelegramError:
                pass
        else:
            last = _QUEUE_REMIND.get(uid, joined)
            if (now - last).total_seconds() / 60.0 >= SEARCH_REMIND_MIN:
                _QUEUE_REMIND[uid] = now
                try:
                    _sl = cur_lang()
                    set_cur_lang(get_lang(uid))
                    await context.bot.send_message(
                        uid, t("search_still", min=int(mins)),
                        parse_mode="HTML", reply_markup=searching_kb(),
                    )
                    set_cur_lang(_sl)
                except TelegramError:
                    pass

    for gone in [k for k in _QUEUE_REMIND if k not in alive_ids]:
        _QUEUE_REMIND.pop(gone, None)


# ============================ КНОПКИ ЧАТА ============================
async def _requeue_and_search(context, uid: int):
    user = get_user(uid)
    conn.execute(
        "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) "
        "VALUES (?, ?, ?, ?, 'normal', ?) "
        "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, "
        "is_vip=excluded.is_vip, mode=excluded.mode, joined_at=excluded.joined_at",
        (uid, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, now_iso()),
    )
    conn.commit()
    UD[uid]["state"] = None
    await context.bot.send_message(uid, t("roulette_finding_partner"), reply_markup=searching_kb())


async def rchat_next(update, context):
    uid = update.effective_user.id
    await end_roulette_session(context, uid, requeue_ender=False)
    context.user_data["state"] = None

    user = get_user(uid)
    if not user or not user["gender"]:
        await context.bot.send_message(uid, t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    await _requeue_and_search(context, uid)


async def rchat_stop(update, context):
    uid = update.effective_user.id
    await end_roulette_session(context, uid, requeue_ender=False)
    context.user_data["state"] = "roulette_pref"
    await context.bot.send_message(uid, t("roulette_who"), reply_markup=roulette_pref_reply_kb())


async def rleft_research(update, context):
    uid = update.effective_user.id
    context.user_data["state"] = None
    context.user_data.pop("last_session", None)
    if get_active_session(uid):
        return
    if conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (uid,)).fetchone():
        await context.bot.send_message(uid, t("roulette_finding_partner"), reply_markup=searching_kb())
        return
    await _requeue_and_search(context, uid)


async def rleft_report(update, context):
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


# ============================ ПОБЛИЗОСТИ ============================
async def nearby_menu(update, context):
    """Главное меню Поблизости."""
    uid = update.effective_user.id
    await clean_screen(update, context)

    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?", (uid,)).fetchone()

    if not prof:
        context.user_data["state"] = "nearby_name"
        context.user_data["nearby_new"] = {}
        await send_menu(
            update, context,
            t("nearby_create_title") + t("nearby_ask_name"),
            cancel_reply_kb(), parse_mode="HTML"
        )
        return

    context.user_data["state"] = "nearby_menu"
    text = (
        t("nearby_title") + "\n"
        f"<blockquote>"
        f"👤 {html.escape(prof['name'])}\n"
        f"🎂 {prof['age']}\n"
        f"💬 {html.escape(prof['bio'] or '—')}"
        f"</blockquote>"
    )
    await send_menu(update, context, text, nearby_menu_kb(), parse_mode="HTML")


async def nearby_create_router(update, context):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()

    if canon(text) in ("Отмена", "Назад"):
        context.user_data["state"] = None
        context.user_data.pop("nearby_new", None)
        await go_home(update, context)
        return

    p = context.user_data.setdefault("nearby_new", {})

    if state == "nearby_name":
        if len(text) < 2 or len(text) > 30:
            await update.message.reply_text(t("nearby_name_invalid"), reply_markup=cancel_reply_kb())
            return
        p["name"] = text
        context.user_data["state"] = "nearby_age"
        await update.message.reply_text(t("nearby_ask_age"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    if state == "nearby_age":
        if not text.isdigit() or int(text) < 12 or int(text) > 99:
            await update.message.reply_text(t("nearby_age_invalid"), reply_markup=cancel_reply_kb())
            return
        p["age"] = int(text)
        context.user_data["state"] = "nearby_gender"
        await update.message.reply_text(t("nearby_ask_gender"), parse_mode="HTML", reply_markup=nearby_gender_kb())
        return

    if state == "nearby_gender":
        g = {"Мужской": "m", "Женский": "f"}.get(canon(text))
        if not g:
            await update.message.reply_text("Выбери пол:", reply_markup=nearby_gender_kb())
            return
        p["gender"] = g
        context.user_data["state"] = "nearby_looking"
        await update.message.reply_text(t("nearby_ask_looking"), parse_mode="HTML", reply_markup=nearby_looking_kb())
        return

    if state == "nearby_looking":
        pref = {"Парня": "m", "Девушку": "f", "Любого": "any"}.get(canon(text))
        if not pref:
            await update.message.reply_text("Выбери вариант:", reply_markup=nearby_looking_kb())
            return
        p["looking_for"] = pref
        context.user_data["state"] = "nearby_bio"
        await update.message.reply_text(t("nearby_ask_bio"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    if state == "nearby_bio":
        if len(text) < 5 or len(text) > 200:
            await update.message.reply_text(t("nearby_bio_invalid"), reply_markup=cancel_reply_kb())
            return
        p["bio"] = text
        context.user_data["state"] = "nearby_photo"
        await update.message.reply_text(t("nearby_ask_photo"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    if state == "nearby_photo":
        if text == "-":
            p["photo_id"] = None
            await _save_nearby_profile(update, context, p)
            return
        await update.message.reply_text(t("nearby_photo_required"), reply_markup=cancel_reply_kb())
        return


async def nearby_photo_handler(update, context):
    if not update.message or not update.message.photo:
        await update.message.reply_text(t("nearby_photo_required"), reply_markup=cancel_reply_kb())
        return
    p = context.user_data.get("nearby_new", {})
    p["photo_id"] = update.message.photo[-1].file_id
    await _save_nearby_profile(update, context, p)


async def _save_nearby_profile(update, context, p):
    uid = update.effective_user.id
    conn.execute("DELETE FROM nearby_profiles WHERE user_id=?", (uid,))
    conn.execute(
        "INSERT INTO nearby_profiles "
        "(user_id, name, age, gender, looking_for, bio, photo_id, active, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (uid, p["name"], p["age"], p["gender"], p["looking_for"],
         p["bio"], p.get("photo_id"), now_iso(), now_iso()),
    )
    conn.commit()
    context.user_data["state"] = None
    context.user_data.pop("nearby_new", None)

    await update.message.reply_text(
        t("nearby_profile_saved"), parse_mode="HTML", reply_markup=main_menu_kb(uid)
    )
    context.user_data["state"] = "nearby_menu"
    await nearby_menu(update, context)


async def nearby_browse(update, context):
    uid = update.effective_user.id
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?", (uid,)).fetchone()
    if not prof:
        await nearby_menu(update, context)
        return

    row = conn.execute(
        "SELECT * FROM nearby_profiles "
        "WHERE user_id != ? AND active = 1 "
        "AND (looking_for = 'any' OR looking_for = ?) "
        "AND (gender = ? OR ? = 'any') "
        "AND user_id NOT IN (SELECT to_id FROM nearby_likes WHERE from_id = ?) "
        "ORDER BY RANDOM() LIMIT 1",
        (uid, prof["gender"], prof["looking_for"], prof["looking_for"], uid),
    ).fetchone()

    if not row:
        await clean_screen(update, context)
        await send_menu(update, context, t("nearby_no_more"), nearby_browse_kb(), parse_mode="HTML")
        return

    context.user_data["state"] = "nearby_view"
    context.user_data["nearby_current"] = row["user_id"]

    caption = f"<b>{html.escape(row['name'])}, {row['age']}</b>\n\n{html.escape(row['bio'] or '—')}"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❤️", callback_data=f"nl:{row['user_id']}"),
            InlineKeyboardButton("👎", callback_data=f"nd:{row['user_id']}"),
        ],
        [InlineKeyboardButton("🚩 Пожаловаться", callback_data=f"nr:{row['user_id']}")],
    ])

    await clean_screen(update, context)
    if row["photo_id"]:
        try:
            await context.bot.send_photo(
                update.effective_chat.id, row["photo_id"],
                caption=caption, parse_mode="HTML", reply_markup=kb
            )
            return
        except TelegramError:
            pass

    await context.bot.send_message(update.effective_chat.id, caption, parse_mode="HTML", reply_markup=kb)


async def on_nearby_like(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("nl:"):
        action = "like"
        target = int(data.split(":")[1])
    elif data.startswith("nd:") or data.startswith("nr:"):
        action = "dislike"
        target = int(data.split(":")[1])
    else:
        return

    uid = query.from_user.id
    if target == uid:
        return

    conn.execute(
        "INSERT OR REPLACE INTO nearby_likes (from_id, to_id, action, created_at) "
        "VALUES (?, ?, ?, ?)",
        (uid, target, action, now_iso()),
    )
    conn.commit()

    if action == "like":
        back = conn.execute(
            "SELECT 1 FROM nearby_likes WHERE from_id=? AND to_id=? AND action='like'",
            (target, uid),
        ).fetchone()
        if back:
            u1, u2 = sorted([uid, target])
            try:
                conn.execute(
                    "INSERT INTO nearby_matches (user1_id, user2_id, created_at) VALUES (?, ?, ?)",
                    (u1, u2, now_iso()),
                )
                conn.commit()
            except Exception:
                pass

            for u in (uid, target):
                try:
                    partner_id = target if u == uid else uid
                    partner = get_user(partner_id)
                    partner_name = (partner["first_name"] if partner else None) or "пользователь"
                    partner_uname = partner["username"] if partner else None

                    if partner_uname:
                        contact = f"@{partner_uname}"
                    else:
                        contact = f'<a href="tg://user?id={partner_id}">Открыть ЛС</a>'

                    bot_username = await get_bot_username(context)
                    text = (
                        t("nearby_match_title") + "\n"
                        + t("nearby_match_contact", name=html.escape(partner_name), contact=contact) + "\n\n"
                        + t("nearby_match_footer", bot=bot_username)
                    )
                    await context.bot.send_message(
                        u, text, parse_mode="HTML", reply_markup=main_menu_kb(u),
                    )
                except TelegramError:
                    pass
            return

    try:
        await query.message.delete()
    except TelegramError:
        pass
    await nearby_browse(update, context)


async def nearby_matches_list(update, context):
    uid = update.effective_user.id
    matches = conn.execute(
        "SELECT * FROM nearby_matches WHERE user1_id=? OR user2_id=? ORDER BY id DESC LIMIT 20",
        (uid, uid),
    ).fetchall()

    if not matches:
        await clean_screen(update, context)
        await send_menu(update, context, t("nearby_no_matches"), nearby_matches_kb(), parse_mode="HTML")
        return

    lines = [t("nearby_matches_list", n=len(matches))]
    for m in matches:
        partner_id = m["user2_id"] if m["user1_id"] == uid else m["user1_id"]
        partner = get_user(partner_id)
        if not partner:
            continue
        name = partner["first_name"] or f"ID{partner_id}"
        uname = f"@{partner['username']}" if partner["username"] else f'<a href="tg://user?id={partner_id}">ЛС</a>'
        lines.append(f"👤 <b>{html.escape(name)}</b> — {uname}")

    lines.append("\n<i>" + t("nearby_matches_footer") + "</i>")

    await clean_screen(update, context)
    await send_menu(update, context, "\n".join(lines), nearby_matches_kb(), parse_mode="HTML")


async def nearby_router(update, context):
    """Роутер кнопок раздела Поблизости."""
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    if text == "Смотреть анкеты":
        await nearby_browse(update, context)
        return
    if text == "Мои мэтчи":
        await nearby_matches_list(update, context)
        return
    if text == "Редактировать анкету":
        conn.execute("DELETE FROM nearby_profiles WHERE user_id=?", (uid,))
        conn.commit()
        context.user_data["state"] = "nearby_name"
        context.user_data["nearby_new"] = {}
        await update.message.reply_text(t("nearby_ask_name"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    await update.message.reply_text(t("choose_on_kb"), reply_markup=nearby_menu_kb())
    # ===================== БЛОК 11 / 14 — РЕФЕРАЛЫ И МАГАЗИН =====================

# ============================ РЕФЕРАЛЫ: ЭКРАН ============================
async def show_referral(update, context):
    uid = update.effective_user.id
    await clean_screen(update, context)
    context.user_data.pop("top_msg_id", None)

    link = await build_start_link(context, f"ref_{get_or_create_ref_code(uid)}")
    total = conn.execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)
    ).fetchone()["c"]
    earned = conn.execute(
        "SELECT COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE referrer_id=? AND active=1",
        (uid,),
    ).fetchone()["s"]

    vip = is_vip(get_user(uid))
    reward = REF_REWARD_VIP if vip else REF_REWARD_NORMAL
    bonus = t("referral_bonus_vip") if vip else t("referral_bonus_normal")

    # Прогресс показывается ТОЛЬКО если юзер создал свою анон-ссылку
    user = get_user(uid)
    has_own_link = bool(user and user["custom_link"])
    progress_block = ""
    if has_own_link:
        qual = qualified_referrals(uid)
        fw = t("ref_friends_word")
        vip_thr = cfg_vip_threshold()
        mod_thr = cfg_moder_threshold()
        prog_lines = [t("ref_progress_title")]
        if vip_thr > 0:
            prog_lines.append(f"VIP: {progress_bar(qual, vip_thr)} {min(qual, vip_thr)}/{vip_thr} {fw}")
        if mod_thr > 0:
            prog_lines.append(f"Moder: {progress_bar(qual, mod_thr)} {min(qual, mod_thr)}/{mod_thr} {fw}")
        progress_block = "\n".join(prog_lines)

    caption = t(
        "referral_screen", reward=reward, bonus=bonus,
        total=total, earned=earned, link=html.escape(link),
    )
    if progress_block:
        caption += "\n\n" + progress_block
    caption += "\n\n" + t(
        "ref_rewards_title",
        vip_n=cfg_vip_threshold(), mod_n=cfg_moder_threshold(),
        vip_d=cfg_vip_days(), mod_d=cfg_moder_days(),
    )

    context.user_data["state"] = "referral"
    photo = get_setting("ref_photo")
    kb = ref_rewards_kb(uid, link)

    if photo:
        try:
            msg = await context.bot.send_photo(
                update.effective_chat.id, photo,
                caption=caption, parse_mode="HTML", reply_markup=kb,
            )
        except TelegramError:
            msg = await context.bot.send_message(
                update.effective_chat.id, caption,
                parse_mode="HTML", reply_markup=kb,
            )
    else:
        msg = await context.bot.send_message(
            update.effective_chat.id, caption,
            parse_mode="HTML", reply_markup=kb,
        )
    track_extra(context, msg)
    await send_menu(update, context, t("ref_menu_hint"), referral_kb(uid))


async def referral_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Назад":
        context.user_data.pop("top_msg_id", None)
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return
    if text == "Топ пригласивших":
        await show_top(update, context)
        return
    if text == "Изменить" and is_admin(uid):
        await show_ref_settings(update, context)
        return
    await update.message.reply_text(t("choose_action"), reply_markup=referral_kb(uid))


async def show_top(update, context):
    """Топ-10 пригласивших НАД реф-ссылкой."""
    try:
        await update.message.delete()
    except TelegramError:
        pass

    prev = context.user_data.get("top_msg_id")
    if prev:
        await try_delete_message(context, update.effective_chat.id, prev)

    rows = conn.execute(
        "SELECT referrer_id, COUNT(*) c, COALESCE(SUM(coins_awarded),0) s FROM referrals "
        "WHERE active=1 GROUP BY referrer_id ORDER BY c DESC, s DESC LIMIT 10"
    ).fetchall()

    if not rows:
        text = t("top_empty")
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = [t("top_title"), "━━━━━━━━━━━━━━━━━━━━"]
        for i, r in enumerate(rows):
            u = conn.execute("SELECT * FROM users WHERE tg_id=?", (r["referrer_id"],)).fetchone()
            name = u["first_name"] if (u and u["first_name"]) else f"ID {r['referrer_id']}"
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {html.escape(name)} — {r['c']} ({r['s']})")
        text = "\n".join(lines)

    msg = await context.bot.send_message(update.effective_chat.id, text, parse_mode="HTML")
    context.user_data["top_msg_id"] = msg.message_id
    track_extra(context, msg)


# ============================ НАГРАДЫ ЗА РЕФЕРАЛОВ ============================
async def refresh_ref_rewards(update, context):
    query = update.callback_query
    try:
        link = await build_start_link(context, f"ref_{get_or_create_ref_code(query.from_user.id)}")
        await query.edit_message_reply_markup(reply_markup=ref_rewards_kb(query.from_user.id, link))
    except TelegramError:
        pass


async def on_claim_vip(update, context):
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
    try:
        base = max(now_dt(), datetime.fromisoformat(u["vip_until"])) if u["vip_until"] else now_dt()
    except (ValueError, TypeError):
        base = now_dt()
    new_until = base + timedelta(days=days)

    conn.execute(
        "UPDATE users SET vip_until=?, ref_vip_claims=? WHERE tg_id=?",
        (new_until.isoformat(), claimed + 1, uid),
    )
    conn.commit()

    await context.bot.send_message(uid, t("ref_vip_granted", days=days), parse_mode="HTML")
    await refresh_ref_rewards(update, context)


async def on_claim_moder(update, context):
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
    await query.answer(
        t("ref_info_alert", n=REF_REWARD_NORMAL, v=REF_REWARD_VIP),
        show_alert=True,
    )


# ============================ НАСТРОЙКИ РЕФ-НАГРАД (АДМИН) ============================
async def show_ref_settings(update, context):
    context.user_data["state"] = "ref_settings"
    photo_state = "есть" if get_setting("ref_photo") else "нет"
    text = (
        "<b>Настройки реферальных наград</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"VIP: <b>{cfg_vip_days()}</b> дн. за <b>{cfg_vip_threshold()}</b> друзей\n"
        f"Модер: <b>{cfg_moder_days()}</b> дн. за <b>{cfg_moder_threshold()}</b> друзей\n"
        f"Фото на экране «Пригласить»: {photo_state}\n\n"
        "Выбери что изменить"
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
        "VIP: дней": ("ref_set_vip_days", "Введите, на сколько ДНЕЙ давать VIP:"),
        "VIP: друзей": ("ref_set_vip_threshold", "Введите, сколько ДРУЗЕЙ нужно для VIP:"),
        "Модер: дней": ("ref_set_moder_days", "Введите, на сколько ДНЕЙ давать модерку:"),
        "Модер: друзей": ("ref_set_moder_threshold", "Введите, сколько ДРУЗЕЙ нужно для модерки:"),
    }

    if text == "Назад":
        await show_referral(update, context)
        return
    if text == "Фото":
        context.user_data["state"] = "ref_set_photo"
        await nav(update, context, "Отправьте фото для экрана «Пригласить» (или «Отмена»):", cancel_reply_kb())
        return
    if text == "Убрать фото":
        set_setting("ref_photo", "")
        await update.message.reply_text("Фото убрано.")
        await show_ref_settings(update, context)
        return
    if text in mp:
        st, prompt = mp[text]
        context.user_data["state"] = st
        await nav(update, context, prompt, cancel_reply_kb())
        return

    await update.message.reply_text("Выбери пункт на клавиатуре", reply_markup=ref_settings_kb())


async def process_ref_setting_value(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text.strip())

    if text == "Отмена":
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
    await update.message.reply_text(f"{label}: {val}")
    await show_ref_settings(update, context)


# ============================ МАГАЗИН ============================
async def show_shop(update, context):
    items = conn.execute("SELECT * FROM shop_items WHERE active=1").fetchall()
    context.user_data["state"] = "shop"
    viewer = get_user(update.effective_user.id)

    shop_map = {}
    rows = []
    for it in items:
        disp = effective_price(it["price"], viewer)
        label = f"{item_title(it)} — {disp}"
        shop_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    context.user_data["shop_map"] = shop_map

    if is_admin(update.effective_user.id):
        rows.append([KeyboardButton("➕ Добавить товар"), KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])

    base = t("shop_title") if items else t("shop_empty")
    if items and is_unlimited(viewer):
        base += "\n<i>У вас безлимитный баланс.</i>"
    elif items and is_vip(viewer):
        base += "\n" + t("shop_vip_note")

    await nav(
        update, context, base,
        tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)),
        parse_mode="HTML",
    )


async def shop_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Меню":
        await go_home(update, context)
        return

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(uid))
        return

    if text == "Добавить товар" and is_admin(uid):
        context.user_data["state"] = "shop_add_title"
        context.user_data["new_item"] = {}
        await nav(update, context, "Название товара (текст кнопки):", cancel_reply_kb())
        return

    if text == "Изменить" and is_admin(uid):
        await shop_edit_list(update, context)
        return

    item_id = context.user_data.get("shop_map", {}).get(text)
    if item_id is None:
        await nav(
            update, context, t("shop_pick_item"),
            tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)),
        )
        return

    item = conn.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        await nav(update, context, t("item_unavailable"), main_menu_kb(uid))
        return

    context.user_data["pending_item"] = item_id
    context.user_data["state"] = "shop_confirm"
    price = effective_price(item["price"], get_user(uid))

    if price != item["price"]:
        price_txt = t("price_vip", price=price, orig=item["price"])
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

    if text == "Отмена":
        await show_shop(update, context)
        return

    if text != "Да":
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

    if not unlimited:
        if (user["coins"] or 0) < price:
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
    if price != item["price"]:
        price_line = f"{price} (VIP −{VIP_DISCOUNT_PERCENT}%, обычно {item['price']})"
    else:
        price_line = str(price)
    await notify_admins(
        context,
        "🛒 <b>Покупка</b>\n"
        f"Покупатель: {user_mention(user)}\n"
        f"Товар: <b>{html.escape(item['title'])}</b>\n"
        f"Цена: <b>{price_line}</b>\n"
        f"Тип награды: <code>{item['reward_type'] or 'manual'}</code>",
        parse_mode="HTML",
    )

    rt = (item["reward_type"] or "manual").strip().lower()
    if rt not in ("coins", "vip", "moder", "manual"):
        rt = "manual"
    if rt == "manual" and item["is_vip"] and not item["reward_amount"]:
        rt = "vip"

    if rt == "coins":
        amt = item["reward_amount"] or 0
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, uid))
        conn.commit()
        context.user_data["state"] = None
        await nav(update, context, t("purchase_coins", amt=amt), main_menu_kb(uid), parse_mode="HTML")

    elif rt == "vip":
        days = item["reward_amount"] or item["duration_days"] or 30
        user = get_user(uid)
        base = now_dt()
        try:
            if user["vip_until"] and datetime.fromisoformat(user["vip_until"]) > now_dt():
                base = datetime.fromisoformat(user["vip_until"])
        except (ValueError, TypeError):
            base = now_dt()
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
                [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")],
                 [KeyboardButton("❌ Отмена")]],
                resize_keyboard=True,
            )),
            parse_mode="HTML",
        )

    else:
        context.user_data["state"] = None
        await nav(update, context, t("purchase_manual"), main_menu_kb(uid), parse_mode="HTML")


# ============================ ФОРМА МОДЕРА ============================
async def moder_q_router(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text in ("Отмена", "Назад", "Меню"):
        price = context.user_data.get("moder_price", 0)
        buyer = get_user(uid)
        if price and buyer and not is_unlimited(buyer):
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
        (uid, item_id, price, app.get("gender"), app.get("age"),
         app.get("tg_time"), app.get("availability"), now_iso()),
    )
    conn.commit()
    app_id = cur.lastrowid

    context.user_data["state"] = None
    context.user_data.pop("moder_app", None)
    user = get_user(uid)

    text = (
        f"📨 Заявка на модератора #{app_id}\n"
        f"Пользователь: {user_mention(user)}\n"
        f"Пол: {html.escape(app.get('gender') or '—')}\n"
        f"Возраст: {html.escape(app.get('age') or '—')}\n"
        f"Время в ТГ/день: {html.escape(app.get('tg_time') or '—')}\n"
        f"Доступность: {html.escape(app.get('availability') or '—')}\n"
        f"Оплачено: {price}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id, text,
                parse_mode="HTML", reply_markup=moder_decision_kb(app_id),
            )
        except TelegramError:
            pass

    await update.message.reply_text(t("moder_form_sent"), reply_markup=main_menu_kb(uid))


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
                buyer_id, t("moder_granted_shop"),
                parse_mode="HTML", reply_markup=main_menu_kb(buyer_id),
            )
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await query.edit_message_text(t("moder_granted_staff"))
    else:
        buyer = get_user(buyer_id)
        if buyer and not is_unlimited(buyer):
            conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (app["price_paid"], buyer_id))
        conn.execute("UPDATE moder_apps SET status='rejected' WHERE id=?", (app_id,))
        conn.commit()
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(buyer_id))
            await context.bot.send_message(buyer_id, t("moder_rejected_user", coins=app["price_paid"]))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        await query.edit_message_text(t("moder_rejected_staff"))


# ============================ РЕДАКТИРОВАНИЕ ТОВАРА ============================
async def process_shop_add(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    item = context.user_data.setdefault("new_item", {})

    if text == "Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(update.effective_user.id))
        await show_shop(update, context)
        return

    if state == "shop_add_title":
        await update.message.reply_text("Перевожу название на 3 языка…")
        ru, uz, en = await translate_to_all(text)
        item["title"] = ru
        item["title_uz"] = uz
        item["title_en"] = en
        context.user_data["state"] = "shop_add_price"
        await update.message.reply_text(
            f"Название сохранено:\n{ru}\n{uz}\n{en}\n\nЦена в коинах:",
            reply_markup=cancel_reply_kb(),
        )

    elif state == "shop_add_price":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        item["price"] = int(text)
        context.user_data["state"] = "shop_add_reward"
        await update.message.reply_text("Что получит покупатель?", reply_markup=reward_type_kb())

    elif state == "shop_add_reward":
        mp = {"Коины": "coins", "VIP": "vip", "Модер": "moder", "Вручную": "manual"}
        rt = mp.get(text)
        if not rt:
            await update.message.reply_text("Выберите тип награды", reply_markup=reward_type_kb())
            return
        item["reward_type"] = rt

        if rt == "coins":
            context.user_data["state"] = "shop_add_amount"
            await update.message.reply_text("Сколько коинов начислять?", reply_markup=cancel_reply_kb())
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
    item = context.user_data.get("new_item", {})
    save_new_item(item)
    context.user_data["state"] = None
    await update.message.reply_text(
        "✅ Товар добавлен в магазин!",
        parse_mode="HTML", reply_markup=main_menu_kb(update.effective_user.id),
    )
    await show_shop(update, context)


def save_new_item(item):
    rt = item.get("reward_type", "manual")
    conn.execute(
        "INSERT INTO shop_items "
        "(title, title_uz, title_en, price, is_vip, duration_days, reward_type, reward_amount, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            item["title"], item.get("title_uz"), item.get("title_en"), item["price"],
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
        await update.message.reply_text(
            "Нет товаров для редактирования.",
            reply_markup=main_menu_kb(update.effective_user.id),
        )
        return

    edit_map = {}
    rows = []
    for it in items:
        label = f"{it['title']} — {it['price']}"
        edit_map[label] = it["id"]
        rows.append([KeyboardButton(label)])
    rows.append([KeyboardButton("⬅️ Назад")])

    context.user_data["edit_map"] = edit_map
    context.user_data["state"] = "shop_edit_pick"
    await update.message.reply_text(
        "Выберите товар для изменения",
        reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)),
    )


async def shop_edit_router(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text)
    uid = update.effective_user.id

    if state == "shop_edit_pick":
        if text == "Назад":
            await show_shop(update, context)
            return
        item_id = context.user_data.get("edit_map", {}).get(text)
        if item_id is None:
            await update.message.reply_text("Выберите товар на клавиатуре")
            return
        context.user_data["edit_item_id"] = item_id
        context.user_data["state"] = "shop_edit_menu"
        item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
        await update.message.reply_text(
            f"Товар: {item['title']} — {item['price']}\nЧто изменить?",
            reply_markup=shop_edit_item_kb(item),
        )
        return

    item_id = context.user_data.get("edit_item_id")
    item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        await show_shop(update, context)
        return

    if text == "Назад":
        await shop_edit_list(update, context)
        return
    if text == "Название":
        context.user_data["state"] = "shop_edit_name"
        await update.message.reply_text("Новое название:", reply_markup=cancel_reply_kb())
        return
    if text == "Цена":
        context.user_data["state"] = "shop_edit_price"
        await update.message.reply_text("Новая цена в коинах:", reply_markup=cancel_reply_kb())
        return
    if text == "Сумма коинов":
        context.user_data["state"] = "shop_edit_amount"
        await update.message.reply_text("Новая сумма коинов:", reply_markup=cancel_reply_kb())
        return
    if text == "Срок VIP":
        context.user_data["state"] = "shop_edit_days"
        await update.message.reply_text("Новый срок VIP (дней):", reply_markup=cancel_reply_kb())
        return
    if text == "Удалить товар":
        conn.execute("UPDATE shop_items SET active=0 WHERE id=?", (item_id,))
        conn.commit()
        await update.message.reply_text("Товар удалён.", reply_markup=main_menu_kb(uid))
        await show_shop(update, context)
        return

    await update.message.reply_text("Выберите действие", reply_markup=shop_edit_item_kb(item))


async def process_shop_edit_value(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())
    item_id = context.user_data.get("edit_item_id")

    if text == "Отмена":
        context.user_data["state"] = "shop_edit_menu"
        item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
        await update.message.reply_text("Отменено.", reply_markup=shop_edit_item_kb(item))
        return

    if state == "shop_edit_name":
        ru, uz, en = await translate_to_all(text)
        conn.execute(
            "UPDATE shop_items SET title=?, title_uz=?, title_en=? WHERE id=?",
            (ru, uz, en, item_id),
        )
        conn.commit()
        msg = f"Название изменено:\n{ru}\n{uz}\n{en}"
    elif state == "shop_edit_price":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET price=? WHERE id=?", (int(text), item_id))
        conn.commit()
        msg = "Цена изменена."
    elif state == "shop_edit_amount":
        if not text.isdigit():
            await update.message.reply_text("Введите число:", reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE shop_items SET reward_amount=? WHERE id=?", (int(text), item_id))
        conn.commit()
        msg = "Сумма коинов изменена."
    elif state == "shop_edit_days":
        if not text.isdigit():
            await update.message.reply_text("Введите число дней:", reply_markup=cancel_reply_kb())
            return
        conn.execute(
            "UPDATE shop_items SET reward_amount=?, duration_days=? WHERE id=?",
            (int(text), int(text), item_id),
        )
        conn.commit()
        msg = "Срок VIP изменён."
    else:
        msg = "Готово."

    context.user_data["state"] = "shop_edit_menu"
    item = conn.execute("SELECT * FROM shop_items WHERE id=?", (item_id,)).fetchone()
    await update.message.reply_text(msg, reply_markup=shop_edit_item_kb(item))
    # ===================== БЛОК 12 / 14 — STARS, ВОЗВРАТ, РАСКРЫТИЕ =====================

# ============================ ВИТРИНА ПАКЕТОВ ============================
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
    await nav(
        update, context, t("stars_title"),
        tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)),
        parse_mode="HTML",
    )


async def star_shop_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text in ("Назад", "Меню", "Отмена"):
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
        t("stars_buy_confirm", title=html.escape(item_title(pkg)),
          coins=pkg['coins'], stars=pkg['price_stars']),
        yes_no_kb(), parse_mode="HTML",
    )


async def star_confirm_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Отмена":
        await show_star_shop(update, context)
        return
    if text != "Да":
        await update.message.reply_text(t("choose_on_kb"), reply_markup=yes_no_kb())
        return

    pid = context.user_data.get("star_pending")
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=? AND active=1", (pid,)).fetchone()
    if not pkg:
        await nav(update, context, t("pkg_unavailable"), main_menu_kb(uid))
        return

    context.user_data["state"] = None
    await context.bot.send_message(uid, t("stars_invoice_sent"), reply_markup=main_menu_kb(uid))
    await context.bot.send_invoice(
        chat_id=uid,
        title=item_title(pkg),
        description=t("stars_pkg_desc", coins=pkg['coins']),
        payload=f"coins:{pkg['id']}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(item_title(pkg), pkg["price_stars"])],
    )


# ============================ ОПЛАТА ============================
async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    uid = update.effective_user.id
    payload = sp.invoice_payload or ""
    try:
        await _do_successful_payment(update, context, sp, uid, payload)
    except Exception as e:
        log.error("Ошибка платежа payload=%s uid=%s: %s", payload, uid, e, exc_info=True)
        await notify_admins(
            context,
            "⚠️ <b>Платёж не обработан</b>\n"
            f"User: <code>{uid}</code>\n"
            f"Payload: <code>{html.escape(payload)}</code>\n"
            f"Amount: {sp.total_amount} {sp.currency}\n"
            f"Charge ID: <code>{html.escape(sp.telegram_payment_charge_id)}</code>\n\n"
            f"Ошибка: <code>{html.escape(str(e)[:200])}</code>",
            parse_mode="HTML",
        )


async def _do_successful_payment(update, context, sp, uid, payload):
    # Раскрытие отправителя
    if payload.startswith("reveal:"):
        mid = int(payload.split(":")[1])
        row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (mid,)).fetchone()
        if not row:
            await update.message.reply_text(t("msg_not_found"))
            return
        txt = reveal_sender_text(row)
        await update.message.reply_text(txt or t("anon_not_found"), parse_mode="HTML")
        return

    # Покупка коинов
    if not payload.startswith("coins:"):
        return

    pid = int(payload.split(":")[1])
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=?", (pid,)).fetchone()
    coins = pkg["coins"] if pkg else 0

    conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (coins, uid))
    conn.execute(
        "INSERT INTO star_purchases (user_id, package_id, coins, stars, charge_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, pid, coins, sp.total_amount, sp.telegram_payment_charge_id, now_iso()),
    )
    conn.commit()

    await update.message.reply_text(
        t("stars_paid", coins=coins),
        parse_mode="HTML", reply_markup=main_menu_kb(uid),
    )
    user = get_user(uid)
    await notify_admins(
        context,
        "💰 Покупка коинов!\n"
        f"{user_mention(user)}\n"
        f"Пакет: {html.escape(pkg['title']) if pkg else '—'}\n"
        f"Коинов: {coins} / Звёзд: {sp.total_amount}\n"
        f"Charge ID: <code>{html.escape(sp.telegram_payment_charge_id)}</code>",
        parse_mode="HTML",
    )


# ============================ АДМИН: ПАКЕТЫ ============================
async def show_star_admin(update, context):
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    lst = "\n".join(
        f"• {p['title']} — {p['coins']} за ⭐{p['price_stars']}" for p in pkgs
    ) or "(пакетов нет)"
    context.user_data["state"] = "star_admin"
    await update.message.reply_text(
        f"Пакеты коинов за Stars:\n{lst}",
        reply_markup=star_admin_kb(),
    )


async def star_admin_router(update, context):
    text = canon(update.message.text)

    if text == "Назад":
        await show_admin_menu(update, context)
        return

    if text == "Добавить пакет коинов":
        context.user_data["state"] = "star_add_title"
        context.user_data["new_star"] = {}
        await update.message.reply_text("Название пакета:", reply_markup=cancel_reply_kb())
        return

    if text == "Удалить пакет коинов":
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
        await update.message.reply_text(
            "Какой пакет удалить?",
            reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)),
        )
        return

    await update.message.reply_text("Выбери действие", reply_markup=star_admin_kb())


async def process_star_wizard(update, context):
    state = context.user_data.get("state")
    text = canon(update.message.text.strip())

    if text == "Отмена":
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
        await update.message.reply_text("Пакет удалён.", reply_markup=star_admin_kb())
        return

    item = context.user_data.setdefault("new_star", {})

    if state == "star_add_title":
        item["title"] = text
        context.user_data["state"] = "star_add_coins"
        await update.message.reply_text("Сколько коинов даёт пакет?", reply_markup=cancel_reply_kb())
    elif state == "star_add_coins":
        if not text.isdigit():
            await update.message.reply_text("Введи число:")
            return
        item["coins"] = int(text)
        context.user_data["state"] = "star_add_price"
        await update.message.reply_text("Цена в звёздах:", reply_markup=cancel_reply_kb())
    elif state == "star_add_price":
        if not text.isdigit():
            await update.message.reply_text("Введи число:")
            return
        await update.message.reply_text("Перевожу название…")
        ru, uz, en = await translate_to_all(item["title"])
        conn.execute(
            "INSERT INTO star_packages (title, title_uz, title_en, coins, price_stars) "
            "VALUES (?, ?, ?, ?, ?)",
            (ru, uz, en, item["coins"], int(text)),
        )
        conn.commit()
        context.user_data["state"] = "star_admin"
        await update.message.reply_text(
            f"Пакет добавлен!\n{ru}\n{uz}\n{en}",
            reply_markup=star_admin_kb(),
        )


# ============================ ВОЗВРАТ STARS (ТОЛЬКО SUPER_ADMIN) ============================
async def show_stars_refund(update, context):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text(t("super_admin_only"))
        return

    rows = conn.execute(
        "SELECT * FROM star_purchases WHERE refunded=0 ORDER BY id DESC LIMIT 20"
    ).fetchall()

    if not rows:
        await update.message.reply_text(
            "💫 <b>Возврат Stars</b>\n\nНет покупок для возврата.",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
        return

    lines = ["💫 <b>Возврат Stars</b>", "━━━━━━━━━━━━━━━━━━━━"]
    kb_rows = []
    purchases_map = {}

    for i, r in enumerate(rows):
        u = get_user(r["user_id"])
        name = (u["first_name"] if u else None) or "—"
        uname = f"@{u['username']}" if (u and u["username"]) else ""
        try:
            dt_str = datetime.fromisoformat(r["created_at"]).strftime("%d.%m %H:%M")
        except Exception:
            dt_str = "—"

        charge = r["charge_id"] or ""
        lines.append(
            f"\n{i+1}. <b>{dt_str}</b> · ⭐{r['stars']} · 💎{r['coins']}\n"
            f"   {html.escape(name)} {uname}\n"
            f"   ID: <code>{r['user_id']}</code>\n"
            f"   Charge: <code>{html.escape(charge[:24])}...</code>"
        )

        if charge:
            purchases_map[i] = {
                "user_id": r["user_id"],
                "charge_id": charge,
                "stars": r["stars"],
                "coins": r["coins"],
            }
            kb_rows.append([InlineKeyboardButton(
                f"↩️ Вернуть #{i+1} ({r['stars']} ⭐)",
                callback_data=f"refund_pick:{i}",
            )])

    context.user_data["admin_refunds"] = purchases_map
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else admin_menu_kb(),
    )


async def on_refund_pick(update, context):
    query = update.callback_query
    await query.answer()
    if not is_super_admin(query.from_user.id):
        await query.answer(t("super_admin_only"), show_alert=True)
        return

    try:
        idx = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    purchases = context.user_data.get("admin_refunds", {})
    p = purchases.get(idx)
    if not p:
        await query.answer("Данные устарели. Введи кнопку заново.", show_alert=True)
        return

    refund_coins = int(p["coins"] * STARS_REFUND_PERCENT / 100)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить возврат", callback_data=f"refund_do:{idx}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="refund_cancel")],
    ])
    await query.edit_message_text(
        "⚠️ <b>Подтверждение возврата</b>\n\n"
        f"Пользователь: <code>{p['user_id']}</code>\n"
        f"Звёзд к возврату: <b>⭐{p['stars']}</b>\n"
        f"Коинов спишется: <b>{refund_coins}</b> ({STARS_REFUND_PERCENT}% от {p['coins']})\n"
        f"Charge ID: <code>{html.escape(p['charge_id'][:24])}...</code>\n\n"
        "<i>Действие необратимо. Возврат возможен в течение 21 дня от покупки.</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def on_refund_do(update, context):
    query = update.callback_query
    await query.answer()
    if not is_super_admin(query.from_user.id):
        return

    try:
        idx = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    purchases = context.user_data.get("admin_refunds", {})
    p = purchases.get(idx)
    if not p:
        await query.edit_message_text("Данные устарели.")
        return

    try:
        await context.bot.refund_star_payment(
            user_id=p["user_id"],
            telegram_payment_charge_id=p["charge_id"],
        )
    except TelegramError as e:
        msg = str(e)
        if "CHARGE_ALREADY_REFUNDED" in msg:
            await query.edit_message_text("⚠️ Этот платёж уже был возвращён ранее.")
        elif "CHARGE_ID_INVALID" in msg:
            await query.edit_message_text("❌ Неверный charge_id.")
        elif "USER_ID_INVALID" in msg:
            await query.edit_message_text("❌ Неверный user_id.")
        elif "too old" in msg.lower() or "expired" in msg.lower():
            await query.edit_message_text("❌ Прошло более 21 дня — возврат невозможен.")
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{html.escape(msg[:200])}</code>",
                parse_mode="HTML",
            )
        return

    # Возврат прошёл — списываем коины (% от полученных)
    refund_coins = int(p["coins"] * STARS_REFUND_PERCENT / 100)
    buyer = get_user(p["user_id"])
    if buyer:
        current = buyer["coins"] or 0
        new_balance = max(0, current - refund_coins)
        conn.execute("UPDATE users SET coins=? WHERE tg_id=?", (new_balance, p["user_id"]))
        conn.commit()

    conn.execute(
        "UPDATE star_purchases SET refunded=1, refunded_at=? WHERE charge_id=?",
        (now_iso(), p["charge_id"]),
    )
    conn.commit()

    await query.edit_message_text(
        "✅ <b>Возврат выполнен успешно</b>\n\n"
        f"⭐{p['stars']} → пользователю <code>{p['user_id']}</code>\n"
        f"💎 Списано коинов: <b>{refund_coins}</b>",
        parse_mode="HTML",
    )

    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(p["user_id"]))
        await context.bot.send_message(
            p["user_id"],
            f"💸 <b>Возврат выполнен</b>\n\n"
            f"Тебе вернули ⭐{p['stars']}.\n"
            f"Коины списаны: <b>{refund_coins}</b>.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(p["user_id"]),
        )
        set_cur_lang(_sl)
    except TelegramError:
        pass


async def on_refund_cancel(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Возврат отменён.")


# ============================ РАСКРЫТИЕ ОТПРАВИТЕЛЯ ============================
def reveal_sender_text(row) -> str | None:
    sender = get_user(row["from_id"])
    if not sender:
        return None
    name = sender["first_name"] or "—"
    uname = (
        f"@{sender['username']}"
        if sender["username"]
        else f"<a href='tg://user?id={sender['tg_id']}'>{t('reveal_profile_link')}</a>"
    )
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

    if is_unlimited(get_user(query.from_user.id)):
        await context.bot.send_message(
            query.from_user.id,
            reveal_sender_text(row) or t("anon_not_found"),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_reveal_yes"), callback_data=f"reveal_pay:{mid}")],
        [InlineKeyboardButton(t("btn_cancel_accent"), callback_data="reveal_cancel")],
    ])
    await context.bot.send_message(
        query.from_user.id, t("reveal_confirm"),
        parse_mode="HTML", reply_markup=kb,
    )


async def on_reveal_pay(update, context):
    query = update.callback_query
    await query.answer()
    mid = int(query.data.split(":")[1])
    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (mid,)).fetchone()
    if not row:
        await query.edit_message_text(t("anon_not_found"))
        return
    await query.edit_message_text(t("reveal_paying"))

    reveal_stars = max(1, get_setting_int("reveal_stars", 1))
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=t("reveal_title"),
        description=t("reveal_desc"),
        payload=f"reveal:{mid}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="", amount=reveal_stars)],
    )


async def on_reveal_cancel(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("cancelled"))
    # ===================== БЛОК 13 / 14 — АДМИНКА И МОДЕРАЦИЯ =====================

# ============================ МЕНЮ ============================
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


# ============================ СТАТИСТИКА ============================
async def adm_stats_msg(update, context):
    users_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    msgs_count = conn.execute("SELECT COUNT(*) c FROM anon_messages").fetchone()["c"]
    sessions_count = conn.execute("SELECT COUNT(*) c FROM roulette_sessions").fetchone()["c"]
    vip_count = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE vip_until>?", (now_iso(),)
    ).fetchone()["c"]
    moders_count = conn.execute("SELECT COUNT(*) c FROM users WHERE is_moder=1").fetchone()["c"]
    anon_links = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE custom_link IS NOT NULL AND custom_link<>''"
    ).fetchone()["c"]
    ref_links = conn.execute("SELECT COUNT(*) c FROM referrals").fetchone()["c"]
    nearby_count = conn.execute("SELECT COUNT(*) c FROM nearby_profiles").fetchone()["c"]
    matches_count = conn.execute("SELECT COUNT(*) c FROM nearby_matches").fetchone()["c"]
    stars_total = conn.execute(
        "SELECT COALESCE(SUM(stars),0) s FROM star_purchases WHERE refunded=0"
    ).fetchone()["s"]

    def _fmt(b):
        if b >= 1024 ** 3:
            return f"{b / 1024 ** 3:.2f} ГБ"
        if b >= 1024 ** 2:
            return f"{b / 1024 ** 2:.2f} МБ"
        if b >= 1024:
            return f"{b / 1024:.1f} КБ"
        return f"{b} Б"

    try:
        if USE_PG:
            PG_LIMIT_BYTES = 512 * 1024 * 1024
            r = conn.execute("SELECT pg_database_size(current_database()) AS sz").fetchone()
            used_bytes = int(r[0] or 0)
            total_bytes = PG_LIMIT_BYTES
            free_bytes = max(0, total_bytes - used_bytes)
            fill_pct = round(used_bytes / total_bytes * 100, 2) if total_bytes else 0
        else:
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
            used_pages = page_count - free_pages
            used_bytes = used_pages * page_size
            total_bytes = page_count * page_size
            free_bytes = free_pages * page_size
            fill_pct = round(used_pages / page_count * 100, 2) if page_count else 0

        bar_filled = min(10, int(fill_pct // 10))
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        if USE_PG:
            db_line = (
                f"💾 <b>База данных (Neon Free)</b>\n"
                f"   Лимит:    <b>{_fmt(total_bytes)}</b>\n"
                f"   Занято:   <b>{_fmt(used_bytes)}</b>\n"
                f"   Свободно: <b>{_fmt(free_bytes)}</b>\n"
                f"   [{bar}] {fill_pct}% от лимита"
            )
        else:
            db_line = (
                f"💾 <b>База данных (SQLite)</b>\n"
                f"   Всего:    <b>{_fmt(total_bytes)}</b>\n"
                f"   Занято:   <b>{_fmt(used_bytes)}</b>\n"
                f"   Свободно: <b>{_fmt(free_bytes)}</b>\n"
                f"   [{bar}] {fill_pct}%"
            )
    except Exception as _e:
        db_line = f"💾 Размер БД: — (<i>{_e}</i>)"

    reveal_stars = get_setting_int("reveal_stars", 1)
    kb = admin_menu_kb() if is_admin(update.effective_user.id) else moder_menu_kb()

    await update.message.reply_text(
        "<b>📊 Статистика бота</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"👑 VIP сейчас: <b>{vip_count}</b>\n"
        f"🛡 Модераторов: <b>{moders_count}</b>\n"
        "────────────\n"
        f"🔗 Анон-ссылок: <b>{anon_links}</b>\n"
        f"📨 Рефералов: <b>{ref_links}</b>\n"
        f"📍 Анкет Поблизости: <b>{nearby_count}</b>\n"
        f"💕 Мэтчей: <b>{matches_count}</b>\n"
        "────────────\n"
        f"💬 Анон-сообщений: <b>{msgs_count}</b>\n"
        f"🎲 Сессий рулетки: <b>{sessions_count}</b>\n"
        f"⭐ Куплено звёзд: <b>{stars_total}</b>\n"
        "────────────\n"
        f"{db_line}\n"
        "────────────\n"
        f"⭐ Цена раскрытия: <b>{reveal_stars} Star</b>"
        "</blockquote>",
        parse_mode="HTML", reply_markup=kb,
    )


async def adm_export_msg(update, context):
    rows = conn.execute("SELECT tg_id, username, gender FROM users").fetchall()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users_export.txt")
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"id={r['tg_id']} | username=@{r['username']} | gender={r['gender']}\n")
    with open(path, "rb") as f:
        await context.bot.send_document(update.effective_user.id, document=f)


# ============================ VIP ПО ID И МАССОВО ============================
async def admin_vip_router(update, context):
    text = canon(update.message.text.strip())
    state = context.user_data.get("state")
    uid = update.effective_user.id
    if not is_admin(uid):
        return

    if state == "vip_bulk_menu":
        bulk_filter = context.user_data.get("vip_bulk_filter", "all")
        if text == "Назад":
            context.user_data["state"] = "admin_vip"
            await update.message.reply_text(t("admin_vip_menu"), parse_mode="HTML", reply_markup=admin_vip_kb())
            return
        if text == "Меню":
            context.user_data["state"] = None
            await go_home(update, context)
            return

        _BULK_GIVE = {
            "Выдать VIP всем": ("all", "всем"),
            "Выдать VIP девушкам": ("female", "девушкам (Ж)"),
            "Выдать VIP парням": ("male", "парням (М)"),
        }
        if text in _BULK_GIVE:
            filt, label = _BULK_GIVE[text]
            context.user_data["vip_bulk_filter"] = filt
            context.user_data["state"] = "vip_bulk_days"
            await update.message.reply_text(
                t("vip_bulk_ask_days", target=label),
                parse_mode="HTML", reply_markup=cancel_reply_kb(),
            )
            return

        _BULK_TAKE = {
            "Забрать у всех": ("all", "всех"),
            "Забрать у девушек": ("female", "девушек (Ж)"),
            "Забрать у парней": ("male", "парней (М)"),
        }
        if text in _BULK_TAKE:
            filt, label = _BULK_TAKE[text]
            q = {"all": "", "female": " WHERE gender='f'", "male": " WHERE gender='m'"}[filt]
            count = conn.execute(f"SELECT COUNT(*) as c FROM users{q}").fetchone()["c"]
            conn.execute(f"UPDATE users SET vip_until=NULL{q}")
            rows = conn.execute(f"SELECT tg_id FROM users{q}").fetchall()
            conn.commit()
            context.user_data["state"] = "admin_vip"
            context.user_data.pop("vip_bulk_filter", None)

            _sl = cur_lang()
            for r in rows:
                try:
                    set_cur_lang(get_lang(r["tg_id"]))
                    await context.bot.send_message(r["tg_id"], t("vip_taken_user"), parse_mode="HTML")
                except TelegramError:
                    pass
                await asyncio.sleep(0.03)
            set_cur_lang(_sl)

            await update.message.reply_text(
                t("vip_bulk_revoke_done", target=label, count=count),
                parse_mode="HTML", reply_markup=admin_vip_kb(),
            )
            return

        await update.message.reply_text(t("choose_on_kb"), reply_markup=vip_bulk_menu_kb(bulk_filter))
        return

    if text in ("Назад", "Меню"):
        context.user_data["state"] = None
        if text == "Меню":
            await go_home(update, context)
        else:
            await show_admin_menu(update, context)
        return

    if state == "admin_vip":
        if text == "Выдать VIP":
            context.user_data["state"] = "vip_give_id"
            await update.message.reply_text(t("vip_ask_id"), parse_mode="HTML", reply_markup=cancel_reply_kb())
            return
        if text == "Забрать VIP":
            context.user_data["state"] = "vip_take_id"
            await update.message.reply_text(t("vip_ask_id"), parse_mode="HTML", reply_markup=cancel_reply_kb())
            return

        _BULK_OPEN = {
            "VIP всем": ("all", "всем"),
            "VIP девушкам": ("female", "девушкам (Ж)"),
            "VIP парням": ("male", "парням (М)"),
        }
        if text in _BULK_OPEN:
            filt, label = _BULK_OPEN[text]
            context.user_data["vip_bulk_filter"] = filt
            context.user_data["state"] = "vip_bulk_menu"
            await update.message.reply_text(
                t("vip_bulk_menu_title", target=label),
                parse_mode="HTML", reply_markup=vip_bulk_menu_kb(filt),
            )
            return

        await update.message.reply_text(t("choose_on_kb"), reply_markup=admin_vip_kb())
        return

    if text == "Отмена":
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
                _sl = cur_lang()
                set_cur_lang(get_lang(target))
                await context.bot.send_message(target, t("vip_taken_user"), parse_mode="HTML")
                set_cur_lang(_sl)
            except TelegramError:
                pass
            context.user_data["state"] = "admin_vip"
            await update.message.reply_text(
                t("vip_taken_admin", id=target),
                parse_mode="HTML", reply_markup=admin_vip_kb(),
            )
            return

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
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await context.bot.send_message(target, t("vip_granted_user", days=days), parse_mode="HTML")
            set_cur_lang(_sl)
        except TelegramError:
            pass

        context.user_data["state"] = "admin_vip"
        context.user_data.pop("vip_target", None)
        await update.message.reply_text(
            t("vip_granted_admin", id=target, days=days),
            parse_mode="HTML", reply_markup=admin_vip_kb(),
        )
        return

    if state == "vip_bulk_days":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text(t("vip_days_number"), reply_markup=cancel_reply_kb())
            return
        days = int(text)
        bulk_filter = context.user_data.get("vip_bulk_filter", "all")
        new_until = (now_dt() + timedelta(days=days)).isoformat()
        q = {"all": "", "female": " WHERE gender='f'", "male": " WHERE gender='m'"}[bulk_filter]
        label_map = {"all": "всем", "female": "девушкам (Ж)", "male": "парням (М)"}
        conn.execute(f"UPDATE users SET vip_until=?{q}", (new_until,))
        conn.commit()
        count = conn.execute(f"SELECT COUNT(*) as c FROM users{q}").fetchone()["c"]
        rows = conn.execute(f"SELECT tg_id FROM users{q}").fetchall()
        context.user_data["state"] = "admin_vip"
        context.user_data.pop("vip_bulk_filter", None)

        _sl = cur_lang()
        for r in rows:
            try:
                set_cur_lang(get_lang(r["tg_id"]))
                await context.bot.send_message(r["tg_id"], t("vip_granted_user", days=days), parse_mode="HTML")
            except TelegramError:
                pass
            await asyncio.sleep(0.03)
        set_cur_lang(_sl)

        await update.message.reply_text(
            t("vip_bulk_done", target=label_map[bulk_filter], days=days, count=count),
            parse_mode="HTML", reply_markup=admin_vip_kb(),
        )
        return


# ============================ МОДЕРАТОРЫ ============================
async def show_admin_moder(update, context):
    context.user_data["state"] = "admin_moder"
    rows = conn.execute(
        "SELECT * FROM users WHERE is_moder=1 OR (moder_until IS NOT NULL AND moder_until>?) "
        "ORDER BY tg_id",
        (now_iso(),),
    ).fetchall()

    if not rows:
        text = "<b>Модераторы</b>\n━━━━━━━━━━━━━━━━━━━━\nПока нет ни одного модератора."
    else:
        lines = [f"<b>Модераторы</b> — всего: <b>{len(rows)}</b>", "━━━━━━━━━━━━━━━━━━━━"]
        for i, u in enumerate(rows, 1):
            name = u["first_name"] or "—"
            uname = f"@{u['username']}" if u["username"] else "без юзернейма"
            if u["is_moder"]:
                kind = "постоянный"
            else:
                try:
                    kind = "до " + datetime.fromisoformat(u["moder_until"]).strftime("%d.%m.%Y")
                except (ValueError, TypeError):
                    kind = "временный"
            key = " · админ-доступ" if u["admin_unlocked"] else ""
            lines.append(f"{i}. {html.escape(name)} ({uname})\n   <code>{u['tg_id']}</code> · {kind}{key}")
        text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=admin_moder_kb())


async def admin_moder_router(update, context):
    text = canon(update.message.text)

    if text == "Назад":
        await show_admin_menu(update, context)
        return
    if text == "Выдать модера":
        context.user_data["state"] = "moder_give_id"
        await update.message.reply_text("Введите ID для выдачи модерки:", reply_markup=cancel_reply_kb())
        return
    if text == "Забрать модера":
        context.user_data["state"] = "moder_take_id"
        await update.message.reply_text("Введите ID для снятия модерки:", reply_markup=cancel_reply_kb())
        return
    await update.message.reply_text("Выберите действие", reply_markup=admin_moder_kb())


async def process_moder_give_take(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())

    if text == "Отмена":
        await show_admin_moder(update, context)
        return
    if not text.isdigit():
        await update.message.reply_text("ID должен быть числом:", reply_markup=cancel_reply_kb())
        return

    target = int(text)
    if not get_user(target):
        await update.message.reply_text(
            "Пользователь не найден (он должен хоть раз запустить бота).",
            reply_markup=admin_moder_kb(),
        )
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
        await update.message.reply_text(
            f"Модерка выдана пользователю {target}.", reply_markup=admin_moder_kb(),
        )
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
        await update.message.reply_text(
            f"Модерка снята у пользователя {target}.", reply_markup=admin_moder_kb(),
        )
    context.user_data["state"] = "admin_moder"


# ============================ БАН ============================
async def start_ban(update, context, back_state: str):
    context.user_data["ban_back"] = back_state
    context.user_data["state"] = "ban_id"
    await update.message.reply_text(
        "Введите ID для бана/разбана (повторный ввод снимет бан):",
        reply_markup=cancel_reply_kb(),
    )


async def process_ban(update, context):
    text = canon(update.message.text.strip())
    back_state = context.user_data.get("ban_back", "admin")
    back_kb = admin_menu_kb() if back_state == "admin" else moder_menu_kb()

    if text == "Отмена":
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

    if new_val:
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (target,))
        conn.commit()
        try:
            await context.bot.send_message(target, "Вы заблокированы в боте.")
        except TelegramError:
            pass
        await update.message.reply_text(f"Пользователь {target} забанен.", reply_markup=back_kb)
    else:
        conn.commit()
        try:
            await context.bot.send_message(target, "Вы разблокированы.", reply_markup=main_menu_kb(target))
        except TelegramError:
            pass
        await update.message.reply_text(f"Пользователь {target} разблокирован.", reply_markup=back_kb)

    context.user_data["state"] = back_state


# ============================ ПАНЕЛЬ МОДЕРА ============================
async def moder_panel_router(update, context):
    text = canon(update.message.text)
    uid = update.effective_user.id

    if text == "Назад":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if text == "Жалобы":
        await show_pending_reports(update, context)
        return
    if text == "Бан / Разбан":
        await start_ban(update, context, "moder")
        return
    if text == "Статистика":
        await adm_stats_msg(update, context)
        return
    if text == "Выгрузить пользователей":
        await adm_export_msg(update, context)
        return
    if text == "Обязательные каналы":
        await adm_channels_msg(update, context)
        return
    if text == "Помощь":
        await update.message.reply_text(
            t("moder_help"), parse_mode="HTML", reply_markup=moder_menu_kb(),
        )
        return
    await update.message.reply_text("Выберите действие", reply_markup=moder_menu_kb())


async def show_pending_reports(update, context):
    reports = conn.execute(
        "SELECT * FROM reports WHERE status='pending' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    back_kb = admin_menu_kb() if is_admin(update.effective_user.id) else moder_menu_kb()

    if not reports:
        await update.message.reply_text("Нет необработанных жалоб", reply_markup=back_kb)
        return

    await update.message.reply_text(f"Необработанных жалоб: {len(reports)}", reply_markup=back_kb)

    for r in reports:
        if r["context"] == "anon":
            msg = conn.execute("SELECT * FROM anon_messages WHERE id=?", (r["ref_id"],)).fetchone()
            preview = (
                msg["text"] if msg and msg["content_type"] == "text" else "[голосовое]"
            ) if msg else "—"
            body = f"🚩 Жалоба #{r['id']} (анон)\nПричина: {r['reason']}\nСодержание: {preview}"
        else:
            body = f"🚩 Жалоба #{r['id']} (рулетка)\nПричина: {r['reason']}"

        ban_label = "Бан навсегда" if r["context"] == "anon" else "Бан 30 дн."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(ban_label, callback_data=f"repadm:ok:{r['id']}"),
            InlineKeyboardButton("Отклонить", callback_data=f"repadm:no:{r['id']}"),
        ]])
        await context.bot.send_message(update.effective_chat.id, body, reply_markup=kb)


# ============================ ОБЯЗАТЕЛЬНЫЕ КАНАЛЫ ============================
async def adm_channels_msg(update, context):
    channels = await get_mandatory_channels()
    if channels:
        lst = "\n".join(
            f"{i + 1}. {channel_title(c)} → {c['chat_username']}"
            for i, c in enumerate(channels)
        )
    else:
        lst = "(пусто)"

    context.user_data["state"] = "adm_channels_menu"
    await update.message.reply_text(
        f"<b>Обязательные каналы</b> ({len(channels)}/10)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>{lst}</blockquote>\n"
        "Это каналы/чаты/боты, на которые нужно подписаться, чтобы <b>удалить сообщение</b>.\n"
        "Выбери действие",
        parse_mode="HTML", reply_markup=adm_channels_kb(update.effective_user.id),
    )


async def adm_channels_router(update, context):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    ctext = canon(text)
    uid = update.effective_user.id

    if not is_staff(uid):
        context.user_data["state"] = None
        return

    if ctext in ("Назад", "Меню") and state == "adm_channels_menu":
        context.user_data["state"] = None
        if ctext == "Меню":
            await go_home(update, context)
        elif is_admin(uid):
            await show_admin_menu(update, context)
        else:
            await show_moder_menu(update, context)
        return

    if ctext == "Отмена":
        context.user_data.pop("new_channel", None)
        await adm_channels_msg(update, context)
        return

    if state == "adm_channels_menu":
        if "Подписка для входа" in ctext:
            if not is_admin(uid):
                await update.message.reply_text(
                    "Эта настройка доступна только администратору.",
                    reply_markup=adm_channels_kb(uid),
                )
                return
            cur = get_setting("subgate_enabled", "0") == "1"
            set_setting("subgate_enabled", "0" if cur else "1")
            await update.message.reply_text(
                "Подписка для входа ВЫКЛЮЧЕНА." if cur else "Подписка для входа ВКЛЮЧЕНА.",
                reply_markup=adm_channels_kb(uid),
            )
            return

        if ctext == "Добавить канал":
            cnt = conn.execute("SELECT COUNT(*) c FROM mandatory_channels").fetchone()["c"]
            if cnt >= 10:
                await update.message.reply_text(
                    "Достигнут максимум — 10 каналов.", reply_markup=adm_channels_kb(uid),
                )
                return
            context.user_data["new_channel"] = {}
            context.user_data["state"] = "adm_ch_name"
            await update.message.reply_text(
                "Введите <b>название кнопки</b>:",
                parse_mode="HTML", reply_markup=cancel_reply_kb(),
            )
            return

        if ctext == "Удалить канал":
            channels = channels_deletable_by(uid)
            if not channels:
                msg = (
                    "Каналов нет." if is_admin(uid)
                    else "У тебя нет каналов для удаления."
                )
                await update.message.reply_text(msg, reply_markup=adm_channels_kb(uid))
                return
            rows, del_map = [], {}
            for i, c in enumerate(channels):
                label = f"{i + 1}. {channel_title(c)}"
                rows.append([KeyboardButton(label)])
                del_map[label] = c["id"]
            rows.append([KeyboardButton("⬅️ Назад")])
            context.user_data["del_map"] = del_map
            context.user_data["state"] = "adm_ch_delete"
            await update.message.reply_text(
                "Выбери канал для удаления",
                reply_markup=tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True)),
            )
            return

        await update.message.reply_text("Выбери действие", reply_markup=adm_channels_kb(uid))
        return

    if state == "adm_ch_name":
        context.user_data["new_channel"]["title"] = text
        context.user_data["state"] = "adm_ch_link"
        await update.message.reply_text(
            "Теперь вставь <b>@канал</b> или ссылку (https://t.me/...):",
            parse_mode="HTML", reply_markup=cancel_reply_kb(),
        )
        return

    if state == "adm_ch_link":
        link = text.strip()
        url = channel_url(link)
        if not is_valid_btn_url(url):
            await update.message.reply_text(
                "Ссылка выглядит неправильно. Пришли <b>@username</b> или ссылку <code>https://t.me/...</code>:",
                parse_mode="HTML", reply_markup=cancel_reply_kb(),
            )
            return
        context.user_data["new_channel"]["link"] = link
        title = context.user_data["new_channel"]["title"]
        context.user_data["state"] = "adm_ch_confirm"
        save_kb = tr_kb(ReplyKeyboardMarkup(
            [[KeyboardButton("💾 Сохранить")], [KeyboardButton("❌ Отмена")]],
            resize_keyboard=True,
        ))
        try:
            preview_kb = InlineKeyboardMarkup([[InlineKeyboardButton(title, url=url)]])
            await update.message.reply_text(
                "<b>Предпросмотр кнопки:</b>\n"
                f"Название: <b>{html.escape(title)}</b>\n"
                f"Ссылка: {html.escape(url)}\n\nВсё верно?",
                parse_mode="HTML", reply_markup=preview_kb,
            )
        except TelegramError:
            await update.message.reply_text(
                "<b>Предпросмотр:</b>\n"
                f"Название: <b>{html.escape(title)}</b>\n"
                f"Ссылка: {html.escape(url)}",
                parse_mode="HTML",
            )
        await update.message.reply_text("Сохранить канал?", reply_markup=save_kb)
        return

    if state == "adm_ch_confirm":
        if ctext == "Сохранить" or canon(text) == "Да":
            nc = context.user_data.get("new_channel", {})
            link = nc.get("link") or ""
            if not link:
                context.user_data["state"] = "adm_channels_menu"
                await update.message.reply_text("Данные канала потерялись. Начни заново.", reply_markup=adm_channels_kb(uid))
                return
            saved = False
            try:
                conn.execute(
                    "INSERT INTO mandatory_channels (chat_username, title, added_by) VALUES (?, ?, ?)",
                    (link, nc.get("title"), int(uid)),
                )
                conn.commit()
                saved = True
            except Exception as e:
                log.warning("save channel (with added_by) failed: %s", e)
                try:
                    conn.execute(
                        "INSERT INTO mandatory_channels (chat_username, title) VALUES (?, ?)",
                        (link, nc.get("title")),
                    )
                    conn.commit()
                    saved = True
                except Exception as e2:
                    log.error("save channel failed: %s", e2)
            context.user_data.pop("new_channel", None)

            if saved:
                await update.message.reply_text(
                    "Канал добавлен!",
                    reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb(),
                )
            else:
                await update.message.reply_text(
                    "Не удалось сохранить канал.",
                    reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb(),
                )
            await adm_channels_msg(update, context)
            return
        await update.message.reply_text("Нажми «Сохранить» или «Отмена».")
        return

    if state == "adm_ch_delete":
        if ctext == "Назад":
            await adm_channels_msg(update, context)
            return
        cid = context.user_data.get("del_map", {}).get(text)
        if cid is None:
            await update.message.reply_text("Выбери канал на клавиатуре")
            return
        ch = conn.execute("SELECT * FROM mandatory_channels WHERE id=?", (cid,)).fetchone()
        if ch is not None and not is_admin(uid) and _ch_added_by(ch) != int(uid):
            await update.message.reply_text(
                "Удалять можно только те каналы, которые добавил ты сам.",
                reply_markup=adm_channels_kb(uid),
            )
            context.user_data.pop("del_map", None)
            await adm_channels_msg(update, context)
            return
        conn.execute("DELETE FROM mandatory_channels WHERE id=?", (cid,))
        conn.commit()
        context.user_data.pop("del_map", None)
        await update.message.reply_text(
            "Канал удалён.",
            reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb(),
        )
        await adm_channels_msg(update, context)
        return


# ============================ РАССЫЛКА ============================
async def process_bcast_audience_text(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id

    if text == "Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text(
            "Отменено.",
            reply_markup=admin_menu_kb() if is_admin(uid) else moder_menu_kb(),
        )
        return

    mp = {"Всем": "all", "Мужчинам": "m", "Женщинам": "f"}
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


async def process_bcast_content(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()

    if canon(update.message.text) == "Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return

    msg = update.message

    if msg.photo and msg.media_group_id:
        key = (uid, msg.media_group_id)
        buf = BCAST_ALBUMS.get(key)
        if buf is None:
            buf = {
                "file_ids": [], "caption": None, "task": None,
                "aud": context.user_data.get("bcast_aud", "all"),
                "is_admin": is_admin(uid),
            }
            BCAST_ALBUMS[key] = buf
        buf["file_ids"].append(msg.photo[-1].file_id)
        if msg.caption and not buf["caption"]:
            buf["caption"] = msg.caption
        if buf["task"]:
            buf["task"].cancel()
        buf["task"] = asyncio.create_task(_flush_bcast_album(context, key))
        return

    context.user_data["bcast_msg"] = {
        "text": msg.text,
        "photo_id": msg.photo[-1].file_id if msg.photo else None,
        "caption": msg.caption,
        "voice_id": msg.voice.file_id if msg.voice else None,
    }
    context.user_data["state"] = "adm_bcast_btn_ask"
    await update.message.reply_text(
        "Добавить кнопку к рассылке?\nОтветьте «Да» или «-» (без кнопки):",
        reply_markup=tr_kb(ReplyKeyboardMarkup(
            [[KeyboardButton("✅ Да")], [KeyboardButton("❌ Отмена")]],
            resize_keyboard=True,
        )),
    )


async def process_bcast_btn_ask(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    text = canon(update.message.text.strip()) if update.message.text else ""

    if text == "Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return

    if text == "Да":
        context.user_data["state"] = "adm_bcast_btn_text"
        await update.message.reply_text("Введите текст кнопки:", reply_markup=cancel_reply_kb())
        return

    await _do_bcast_send(update, context, button_text=None, button_url=None)


async def process_bcast_btn_text(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    text = update.message.text.strip() if update.message.text else ""

    if canon(text) == "Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return

    context.user_data["bcast_btn_text"] = text
    context.user_data["state"] = "adm_bcast_btn_url"
    await update.message.reply_text("Введите URL для кнопки:", reply_markup=cancel_reply_kb())


async def process_bcast_btn_url(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    text = update.message.text.strip() if update.message.text else ""

    if canon(text) == "Отмена":
        context.user_data["state"] = "admin" if is_admin(uid) else "moder"
        await update.message.reply_text("Отменено.", reply_markup=back_kb)
        return

    btn_text = context.user_data.get("bcast_btn_text", "")
    await _do_bcast_send(update, context, button_text=btn_text, button_url=text)


async def _do_bcast_send(update, context, button_text, button_url):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    bcast = context.user_data.get("bcast_msg", {})
    aud = context.user_data.get("bcast_aud", "all")

    if aud == "all":
        rows = conn.execute("SELECT tg_id FROM users").fetchall()
    else:
        rows = conn.execute("SELECT tg_id FROM users WHERE gender=?", (aud,)).fetchall()

    markup = None
    if button_text and button_url:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, url=button_url)]])

    sent, failed = 0, 0
    dead_ids = []
    prefix_text = "Админ:\n\n"

    for r in rows:
        try:
            if bcast.get("text"):
                await context.bot.send_message(r["tg_id"], prefix_text + bcast["text"], reply_markup=markup)
            elif bcast.get("photo_id"):
                caption = (prefix_text + bcast["caption"]) if bcast.get("caption") else prefix_text
                await context.bot.send_photo(r["tg_id"], bcast["photo_id"], caption=caption, reply_markup=markup)
            elif bcast.get("voice_id"):
                await context.bot.send_message(r["tg_id"], prefix_text, reply_markup=markup)
                await context.bot.send_voice(r["tg_id"], bcast["voice_id"])
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            dead_ids.append(r["tg_id"])
        except TelegramError as e:
            failed += 1
            if _is_dead_account(e):
                dead_ids.append(r["tg_id"])
        await asyncio.sleep(0.03)

    removed = 0
    for bid in dead_ids:
        if safe_purge_dead(bid):
            removed += 1

    context.user_data["state"] = "admin" if is_admin(uid) else "moder"
    await update.message.reply_text(
        f"📢 Рассылка завершена.\nДоставлено: {sent}\nНе удалось: {failed}\nУдалено недоступных: {removed}",
        reply_markup=back_kb,
    )


async def _flush_bcast_album(context, key):
    try:
        await asyncio.sleep(1.5)
    except asyncio.CancelledError:
        return

    buf = BCAST_ALBUMS.pop(key, None)
    if not buf or not buf["file_ids"]:
        return

    uid = key[0]
    back_kb = admin_menu_kb() if buf["is_admin"] else moder_menu_kb()
    aud = buf["aud"]

    if aud == "all":
        rows = conn.execute("SELECT tg_id FROM users").fetchall()
    else:
        rows = conn.execute("SELECT tg_id FROM users WHERE gender=?", (aud,)).fetchall()

    prefix_text = "Админ:\n\n"
    caption = prefix_text + (buf["caption"] or "")
    file_ids = buf["file_ids"][:10]

    sent, failed, removed = 0, 0, 0
    for r in rows:
        try:
            media = [
                InputMediaPhoto(media=fid, caption=caption if i == 0 else None)
                for i, fid in enumerate(file_ids)
            ]
            await context.bot.send_media_group(r["tg_id"], media)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
            if safe_purge_dead(r["tg_id"]):
                removed += 1
        except TelegramError as e:
            failed += 1
            if _is_dead_account(e) and safe_purge_dead(r["tg_id"]):
                removed += 1
        await asyncio.sleep(0.03)

    UD[uid]["state"] = "admin" if buf["is_admin"] else "moder"
    try:
        await context.bot.send_message(
            uid,
            f"📢 Рассылка завершена (альбом из {len(file_ids)} фото).\n"
            f"Доставлено: {sent}\nНе удалось: {failed}\nУдалено: {removed}",
            reply_markup=back_kb,
        )
    except TelegramError:
        pass


# ============================ ЦЕНА РАСКРЫТИЯ / КОИНЫ ============================
async def process_adm_reveal_price(update, context):
    text = update.message.text.strip()
    if canon(text) == "Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("↩️ Отменено.", reply_markup=admin_menu_kb())
        return
    try:
        val = int(text)
        if val < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите целое число ≥ 1:", reply_markup=cancel_reply_kb())
        return
    set_setting("reveal_stars", val)
    context.user_data["state"] = None
    await update.message.reply_text(
        f"✅ Цена раскрытия обновлена: <b>{val} Star</b>",
        parse_mode="HTML", reply_markup=admin_menu_kb(),
    )


async def process_adm_coins_wizard(update, context):
    state = context.user_data["state"]
    text = canon(update.message.text.strip())

    if text == "Отмена":
        context.user_data["state"] = None
        await update.message.reply_text("Отменено.", reply_markup=admin_menu_kb())
        return

    if state == "adm_coins_id":
        target = resolve_user_ref(update.message.text.strip())
        if target is None:
            await update.message.reply_text(
                "Пользователь не найден. Введите ID или @username:",
                reply_markup=cancel_reply_kb(),
            )
            return
        context.user_data["coins_target"] = target
        context.user_data["state"] = "adm_coins_amount"
        await update.message.reply_text(
            "На сколько изменить баланс (можно отрицательное число)?",
            reply_markup=cancel_reply_kb(),
        )
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
        await update.message.reply_text(
            f"Баланс пользователя {target} изменён на {amount}",
            reply_markup=admin_menu_kb(),
        )
        try:
            await context.bot.send_message(target, f"Твой баланс коинов изменён на {amount}")
        except TelegramError:
            pass
            # ===================== БЛОК 14 / 14 — КОМАНДЫ / РОУТЕРЫ / ЗАПУСК =====================

# ============================ /tg — МОНИТОРИНГ РУЛЕТКИ ============================
def tg_watch_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("🚪 Выйти")]], resize_keyboard=True))


def tg_ban_kb(session):
    u1 = get_user(session["user1_id"])
    u2 = get_user(session["user2_id"])
    n1 = (u1["first_name"] if u1 else None) or str(session["user1_id"])
    n2 = (u2["first_name"] if u2 else None) or str(session["user2_id"])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Бан 1️⃣ {n1[:12]}", callback_data=f"tgban:{session['id']}:1"),
        InlineKeyboardButton(f"Бан 2️⃣ {n2[:12]}", callback_data=f"tgban:{session['id']}:2"),
    ]])


def detach_spectator(mod_id: int):
    sid = SPECTATORS.pop(mod_id, None)
    if sid is not None:
        SESSION_SPECTATORS[sid].discard(mod_id)
        if not SESSION_SPECTATORS[sid]:
            SESSION_SPECTATORS.pop(sid, None)


async def attach_spectator(context, mod_id: int, session, auto: bool = False):
    detach_spectator(mod_id)
    SPECTATORS[mod_id] = session["id"]
    SESSION_SPECTATORS[session["id"]].add(mod_id)
    UD[mod_id]["state"] = "tg_watch"

    u1 = get_user(session["user1_id"])
    u2 = get_user(session["user2_id"])
    head = "🔔 <b>Новая сессия для наблюдения</b>" if auto else "👁 <b>Вы наблюдаете за сессией</b>"
    info = (
        f"{head}  (Обычный чат)\n"
        f"1️⃣ {user_mention(u1)}\n"
        f"2️⃣ {user_mention(u2)}\n\n"
        "Сообщения участников приходят сюда. Кнопки ниже — забанить."
    )
    try:
        await context.bot.send_message(mod_id, info, parse_mode="HTML", reply_markup=tg_watch_kb())
        await context.bot.send_message(mod_id, "Действия", reply_markup=tg_ban_kb(session))
    except TelegramError:
        pass


async def relay_to_spectators(context, session, sender_id: int, from_chat_id: int, message_id: int):
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


async def handle_spectators_on_end(context, session_id: int):
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
            await context.bot.send_message(mod_id, "Наблюдаемая сессия завершена.")
            if nxt:
                await attach_spectator(context, mod_id, nxt, auto=True)
            else:
                UD[mod_id]["state"] = "tg_watch"
                await context.bot.send_message(
                    mod_id, "Других активных сессий нет. Нажмите Выйти.",
                    reply_markup=tg_watch_kb(),
                )
        except TelegramError:
            pass


def active_sessions_list_text() -> str | None:
    rows = conn.execute(
        "SELECT * FROM roulette_sessions WHERE active=1 ORDER BY id DESC LIMIT 30"
    ).fetchall()
    if not rows:
        return None
    lines = ["<b>Активные сессии рулетки</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for s in rows:
        u1 = get_user(s["user1_id"])
        u2 = get_user(s["user2_id"])
        g1 = gender_label(u1["gender"]) if u1 and u1["gender"] else "—"
        g2 = gender_label(u2["gender"]) if u2 and u2["gender"] else "—"
        lines.append(
            f"#{s['id']}: 1️⃣ <code>{s['user1_id']}</code> ({g1}) "
            f"2️⃣ <code>{s['user2_id']}</code> ({g2})"
        )
    lines.append("\nВведите ID одного из участников, чтобы наблюдать:")
    return "\n".join(lines)


async def tg_start(update, context):
    text = active_sessions_list_text()
    uid = update.effective_user.id
    if not text:
        await update.message.reply_text("Сейчас нет активных сессий рулетки.", reply_markup=main_menu_kb(uid))
        return
    context.user_data["state"] = "tg_pick"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=cancel_reply_kb())


async def process_tg_pick(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id

    if text == "Отмена":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if not text.isdigit():
        await update.message.reply_text("Введите ID числом (или «Отмена»):", reply_markup=cancel_reply_kb())
        return

    session = get_active_session(int(text))
    if not session:
        await update.message.reply_text(
            "Активная сессия с таким участником не найдена. Попробуйте другой ID:",
            reply_markup=cancel_reply_kb(),
        )
        return
    await attach_spectator(context, uid, session)


async def on_tg_ban(update, context):
    query = update.callback_query
    if not is_staff(query.from_user.id):
        await query.answer(t("staff_only"), show_alert=True)
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

    await force_end_session(context, session["id"])

    try:
        await context.bot.send_message(target, "Вы заблокированы в боте.")
    except TelegramError:
        pass

    await query.answer(f"Пользователь {target} забанен, сессия завершена", show_alert=True)
    try:
        await context.bot.send_message(
            query.from_user.id,
            f"Забанен {which}️⃣ (ID <code>{target}</code>). Сессия завершена.",
            parse_mode="HTML",
        )
    except TelegramError:
        pass


# ============================ /next — НАПИСАТЬ ЮЗЕРУ ============================
async def modmsg_start(update, context):
    context.user_data["state"] = "modmsg_id"
    await update.message.reply_text("Введите ID пользователя, которому написать:", reply_markup=cancel_reply_kb())


async def process_modmsg_id(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id

    if text == "Отмена":
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

    if canon(raw.strip()) == "Отмена":
        context.user_data["state"] = None
        context.user_data.pop("modmsg_target", None)
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return

    target = context.user_data.get("modmsg_target")
    moder = get_user(uid)
    moder_name = (moder["first_name"] if moder else None) or "Модератор"

    ok = False
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(target))
        await context.bot.send_message(
            target,
            t("mod_message", name=html.escape(moder_name), text=html.escape(raw)),
            parse_mode="HTML",
        )
        set_cur_lang(_sl)
        ok = True
    except TelegramError:
        pass

    context.user_data["state"] = None
    context.user_data.pop("modmsg_target", None)
    await update.message.reply_text(
        "Отправлено." if ok else "Не удалось отправить (возможно, юзер заблокировал бота).",
        reply_markup=main_menu_kb(uid),
    )


# ============================ /anon — НАБЛЮДЕНИЕ ============================
async def anon_start(update, context):
    uid = update.effective_user.id
    context.user_data["state"] = "anon_pick"
    await update.message.reply_text(
        t("anon_watch_prompt"),
        parse_mode="HTML",
        reply_markup=cancel_reply_kb(),
    )


async def process_anon_pick(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id

    if text == "Отмена":
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return
    if not text.isdigit():
        await update.message.reply_text("ID должен быть числом:", reply_markup=cancel_reply_kb())
        return

    target_id = int(text)
    if not get_user(target_id):
        await update.message.reply_text("Пользователь не найден.", reply_markup=cancel_reply_kb())
        return

    rows = conn.execute(
        "SELECT * FROM anon_messages WHERE to_id=? OR from_id=? ORDER BY id ASC LIMIT 500",
        (target_id, target_id),
    ).fetchall()

    if not rows:
        await update.message.reply_text(t("anon_watch_empty"), reply_markup=cancel_reply_kb())
        return

    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<style>body{font-family:Arial;padding:20px;background:#1a1a1a;color:#eee}",
        ".msg{margin:8px 0;padding:10px;border-radius:10px;background:#2a2a2a;max-width:70%}",
        ".in{background:#3a2a5a}.out{background:#2a3a5a;margin-left:auto}",
        ".meta{font-size:11px;opacity:0.6}</style></head><body>",
        f"<h2>Переписка пользователя {target_id}</h2>",
    ]
    for r in rows:
        cls = "out" if r["from_id"] == target_id else "in"
        when = (r["created_at"] or "")[:19].replace("T", " ")
        if r["content_type"] == "text":
            body = html.escape(r["text"] or "")
        elif r["content_type"] == "voice":
            body = "[голосовое сообщение]"
        else:
            body = "[медиа]"
        lines.append(
            f"<div class='msg {cls}'><div class='meta'>{r['id']} · "
            f"{'→' if r['from_id'] == target_id else '←'} "
            f"{when} · {r['msg_type']}</div>{body}</div>"
        )
    lines.append("</body></html>")

    html_data = "\n".join(lines).encode("utf-8")
    file = BufferedInputFile(html_data, filename=f"anon_{target_id}.html")

    try:
        conn.execute("DELETE FROM anon_watchers WHERE mod_id=? AND target_id=?", (uid, target_id))
        conn.execute(
            "INSERT INTO anon_watchers (mod_id, target_id, active, created_at) VALUES (?, ?, 1, ?)",
            (uid, target_id, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("anon_watchers insert: %s", e)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Выйти", callback_data="anon_watch_leave")],
    ])
    context.user_data["state"] = "anon_watch"
    context.user_data["anon_watch_target"] = target_id

    await context.bot.send_document(
        uid, file,
        caption=t("anon_watch_file_caption", uid=target_id),
        parse_mode="HTML",
        reply_markup=kb,
    )


async def relay_to_anon_watchers(context, target_id, msg_id):
    """Трансляция новой анонимки наблюдателям /anon."""
    try:
        watchers = conn.execute(
            "SELECT * FROM anon_watchers WHERE target_id=? AND active=1", (target_id,)
        ).fetchall()
    except Exception:
        return

    if not watchers:
        return

    row = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    if not row:
        return

    sender = get_user(row["from_id"])
    sname = (sender["first_name"] if sender else None) or "—"
    when = (row["created_at"] or "")[:19].replace("T", " ")

    for w in watchers:
        try:
            header = t("anon_watch_new_msg", uid=target_id, sname=html.escape(sname),
                       sfid=row["from_id"], when=when)
            await context.bot.send_message(w["mod_id"], header, parse_mode="HTML")
        except TelegramError:
            pass


async def on_anon_watch_leave(update, context):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    target = context.user_data.get("anon_watch_target")
    if target:
        try:
            conn.execute("UPDATE anon_watchers SET active=0 WHERE mod_id=? AND target_id=?", (uid, target))
            conn.commit()
        except Exception:
            pass
    context.user_data["state"] = None
    context.user_data.pop("anon_watch_target", None)
    try:
        await query.edit_message_caption(caption=t("anon_watch_leave"))
    except TelegramError:
        try:
            await query.edit_message_text(t("anon_watch_leave"))
        except TelegramError:
            pass
    await context.bot.send_message(uid, t("main_menu"), reply_markup=main_menu_kb(uid))


# ============================ /sex — КОМНАТА ДЛЯ ДЕВУШЕК ============================
def sex_room_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("💬 Комната"), KeyboardButton("👥 Участники")],
        [KeyboardButton("🚪 Запросить выход")],
        [KeyboardButton("✏️ Переименовать"), KeyboardButton("🗑 Удалить комнату")],
    ], resize_keyboard=True))


async def sex_start(update, context):
    """Команда /sex — открыть или создать комнату. Только модер."""
    uid = update.effective_user.id
    u = get_user(uid)
    if not is_moder(u):
        await update.message.reply_text(t("sex_only_moder"))
        return

    room = conn.execute("SELECT * FROM sex_rooms ORDER BY id LIMIT 1").fetchone()

    if not room:
        # Нет комнаты — только модер создаёт
        context.user_data["state"] = "sex_create_name"
        await update.message.reply_text(t("sex_create_prompt"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    # Комната есть — заходим
    role = "moder" if is_moder(get_user(uid)) else "girl"
    existing = conn.execute(
        "SELECT * FROM sex_members WHERE room_id=? AND user_id=?", (room["id"], uid)
    ).fetchone()
    if not existing:
        num = conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM sex_members WHERE room_id=?", (room["id"],)
        ).fetchone()["n"]
        conn.execute(
            "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) VALUES (?, ?, ?, ?, ?)",
            (room["id"], uid, role, num, now_iso()),
        )
        conn.commit()
    context.user_data["state"] = "sex_room"
    context.user_data["sex_room_id"] = room["id"]
    await update.message.reply_text(
        t("sex_room_joined", title=html.escape(room["title"])),
        parse_mode="HTML", reply_markup=sex_room_kb(),
    )


async def sex_create_router(update, context):
    """Ввод названия комнаты."""
    text = canon(update.message.text.strip())
    uid = update.effective_user.id
    if text in ("Отмена", "Назад"):
        context.user_data["state"] = None
        await update.message.reply_text(t("main_menu"), reply_markup=main_menu_kb(uid))
        return

    title = (update.message.text or "").strip()
    if len(title) < 2 or len(title) > 40:
        await update.message.reply_text("Название 2-40 символов:", reply_markup=cancel_reply_kb())
        return

    conn.execute("DELETE FROM sex_members")
    conn.execute("DELETE FROM sex_messages")
    conn.execute("DELETE FROM sex_rooms")
    cur = conn.execute(
        "INSERT INTO sex_rooms (title, owner_id, created_at) VALUES (?, ?, ?)",
        (title, uid, now_iso()),
    )
    conn.commit()
    room_id = cur.lastrowid

    # Модер добавляется первым
    conn.execute(
        "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) VALUES (?, ?, 'moder', 1, ?)",
        (room_id, uid, now_iso()),
    )
    conn.commit()

    # Приглашаем всех девушек в боте
    girls = conn.execute("SELECT tg_id FROM users WHERE gender='f'").fetchall()
    added = 0
    for g in girls:
        gid = g["tg_id"]
        if gid == uid:
            continue
        try:
            exists = conn.execute(
                "SELECT 1 FROM sex_members WHERE room_id=? AND user_id=?", (room_id, gid)
            ).fetchone()
            if exists:
                continue
            num = conn.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM sex_members WHERE room_id=?", (room_id,)
            ).fetchone()["n"]
            conn.execute(
                "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) VALUES (?, ?, 'girl', ?, ?)",
                (room_id, gid, num, now_iso()),
            )
            conn.commit()
            added += 1
            try:
                _sl = cur_lang()
                set_cur_lang(get_lang(gid))
                await context.bot.send_message(
                    gid,
                    f"💬 <b>Тебя пригласили в комнату «{html.escape(title)}»</b>\n\n"
                    f"Набери /sex чтобы войти.",
                    parse_mode="HTML",
                )
                set_cur_lang(_sl)
            except TelegramError:
                pass
            await asyncio.sleep(0.05)
        except Exception as e:
            log.warning("sex_add_girl %s: %s", gid, e)

    context.user_data["state"] = "sex_room"
    context.user_data["sex_room_id"] = room_id
    await update.message.reply_text(
        t("sex_room_created", title=html.escape(title)) + f"\n\nПриглашено девушек: {added}",
        parse_mode="HTML", reply_markup=sex_room_kb(),
    )


async def sex_room_router(update, context):
    """Роутер внутри комнаты /sex."""
    text = canon(update.message.text)
    uid = update.effective_user.id
    room_id = context.user_data.get("sex_room_id")

    if not room_id:
        room = conn.execute("SELECT * FROM sex_rooms ORDER BY id LIMIT 1").fetchone()
        if not room:
            context.user_data["state"] = None
            await update.message.reply_text(t("sex_no_room"))
            return
        room_id = room["id"]
        context.user_data["sex_room_id"] = room_id

    room = conn.execute("SELECT * FROM sex_rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        context.user_data["state"] = None
        await update.message.reply_text(t("sex_no_room"))
        return

    member = conn.execute(
        "SELECT * FROM sex_members WHERE room_id=? AND user_id=?", (room_id, uid)
    ).fetchone()
    if not member:
        # Не в комнате — добавляем как модера (если модер)
        u = get_user(uid)
        if is_moder(u):
            num = conn.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM sex_members WHERE room_id=?", (room_id,)
            ).fetchone()["n"]
            conn.execute(
                "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) VALUES (?, ?, 'moder', ?, ?)",
                (room_id, uid, num, now_iso()),
            )
            conn.commit()
            member = conn.execute(
                "SELECT * FROM sex_members WHERE room_id=? AND user_id=?", (room_id, uid)
            ).fetchone()
        else:
            context.user_data["state"] = None
            await update.message.reply_text(t("sex_no_room"))
            return

    if text == "Участники":
        members = conn.execute(
            "SELECT * FROM sex_members WHERE room_id=? ORDER BY number", (room_id,)
        ).fetchall()
        lines = [f"👥 <b>Участники «{html.escape(room['title'])}»</b>", "━━━━━━━━━━━━━━━━━━━━"]
        for m in members:
            muser = get_user(m["user_id"])
            name = (muser["first_name"] if muser else None) or f"ID{m['user_id']}"
            icon = "🛡" if m["role"] == "moder" else "👩"
            lines.append(f"{icon} <b>{m['number']}</b> · {html.escape(name)}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=sex_room_kb())
        return

    if text == "Комната":
        await update.message.reply_text(
            f"💬 <b>{html.escape(room['title'])}</b>\n\nПиши сообщения — они уйдут всем участникам.",
            parse_mode="HTML", reply_markup=sex_room_kb(),
        )
        return

    if text == "Запросить выход":
        # Только девушка может запросить выход
        if member["role"] == "girl":
            exists = conn.execute(
                "SELECT * FROM sex_exit_requests WHERE room_id=? AND user_id=?", (room_id, uid)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO sex_exit_requests (room_id, user_id, status, created_at) VALUES (?, ?, 'pending', ?)",
                    (room_id, uid, now_iso()),
                )
                conn.commit()
            # Уведомляем модеров комнаты
            moders = conn.execute(
                "SELECT user_id FROM sex_members WHERE room_id=? AND role='moder'", (room_id,)
            ).fetchall()
            for m in moders:
                try:
                    await context.bot.send_message(
                        m["user_id"],
                        f"🚪 Девушка #{member['number']} (ID <code>{uid}</code>) хочет выйти из комнаты.\n"
                        f"Одобрить: <code>/sex_approve {uid}</code>",
                        parse_mode="HTML",
                    )
                except TelegramError:
                    pass
            await update.message.reply_text(t("sex_exit_requested"), reply_markup=sex_room_kb())
        else:
            await update.message.reply_text(
                "Выйти из комнаты может только девушка. Модер может удалить комнату.",
                reply_markup=sex_room_kb(),
            )
        return

    if text == "Переименовать":
        if member["role"] != "moder":
            await update.message.reply_text(t("sex_only_owner_can_rename"), reply_markup=sex_room_kb())
            return
        if room["owner_id"] != uid:
            await update.message.reply_text(t("sex_only_owner_can_rename"), reply_markup=sex_room_kb())
            return
        context.user_data["state"] = "sex_rename"
        await update.message.reply_text(t("sex_renamed_prompt"), parse_mode="HTML", reply_markup=cancel_reply_kb())
        return

    if text == "Удалить комнату":
        if room["owner_id"] != uid:
            await update.message.reply_text(t("sex_only_owner_can_delete"), reply_markup=sex_room_kb())
            return
        conn.execute("DELETE FROM sex_members WHERE room_id=?", (room_id,))
        conn.execute("DELETE FROM sex_messages WHERE room_id=?", (room_id,))
        conn.execute("DELETE FROM sex_exit_requests WHERE room_id=?", (room_id,))
        conn.execute("DELETE FROM sex_rooms WHERE id=?", (room_id,))
        conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("sex_room_id", None)
        await update.message.reply_text(t("sex_room_deleted"), reply_markup=main_menu_kb(uid))
        return

    # Обычное сообщение — рассылаем всем участникам кроме отправителя
    if update.message.text or update.message.voice or update.message.photo:
        content_type = "text" if update.message.text else "voice"
        text_content = update.message.text or None
        voice_id = update.message.voice.file_id if update.message.voice else None

        cur = conn.execute(
            "INSERT INTO sex_messages (room_id, sender_number, content_type, text, voice_file_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (room_id, member["number"], content_type, text_content, voice_id, now_iso()),
        )
        conn.commit()

        recipients = conn.execute(
            "SELECT user_id FROM sex_members WHERE room_id=? AND user_id<>?", (room_id, uid)
        ).fetchall()

        header = t("sex_msg_from", num=member["number"])
        for r in recipients:
            try:
                if content_type == "text":
                    await context.bot.send_message(r["user_id"], f"{header}\n{update.message.text}")
                else:
                    await context.bot.send_voice(
                        r["user_id"], voice_id,
                        caption=header, parse_mode="HTML",
                    )
            except TelegramError:
                pass
        return

    await update.message.reply_text("Пиши текст, голосовое или фото:", reply_markup=sex_room_kb())


async def sex_rename_router(update, context):
    text = canon(update.message.text.strip())
    uid = update.effective_user.id
    if text in ("Отмена", "Назад"):
        context.user_data["state"] = "sex_room"
        await update.message.reply_text(t("main_menu"), reply_markup=sex_room_kb())
        return
    new_title = (update.message.text or "").strip()
    if len(new_title) < 2 or len(new_title) > 40:
        await update.message.reply_text("Название 2-40 символов:", reply_markup=cancel_reply_kb())
        return
    room_id = context.user_data.get("sex_room_id")
    conn.execute("UPDATE sex_rooms SET title=? WHERE id=?", (new_title, room_id))
    conn.commit()
    context.user_data["state"] = "sex_room"
    await update.message.reply_text(
        t("sex_room_renamed", title=html.escape(new_title)),
        parse_mode="HTML", reply_markup=sex_room_kb(),
    )


async def sex_approve_cmd(update, context, user_id):
    """Модер одобряет выход девушки. Вызывается из text_router по /sex_approve."""
    uid = update.effective_user.id
    u = get_user(uid)
    if not is_moder(u):
        return
    room = conn.execute("SELECT * FROM sex_rooms ORDER BY id LIMIT 1").fetchone()
    if not room:
        await update.message.reply_text(t("sex_no_room"))
        return
    req = conn.execute(
        "SELECT * FROM sex_exit_requests WHERE room_id=? AND user_id=? AND status='pending'",
        (room["id"], user_id),
    ).fetchone()
    if not req:
        await update.message.reply_text("Запрос не найден.")
        return
    conn.execute("UPDATE sex_exit_requests SET status='approved' WHERE id=?", (req["id"],))
    conn.execute("DELETE FROM sex_members WHERE room_id=? AND user_id=?", (room["id"], user_id))
    conn.commit()
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(user_id))
        await context.bot.send_message(user_id, t("sex_exit_approved"))
        set_cur_lang(_sl)
    except TelegramError:
        pass
    await update.message.reply_text(f"✅ Выход одобрен для {user_id}.", reply_markup=sex_room_kb())


# ============================ CALLBACKS ============================
_CALLBACKS = [
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
    ("roulette_report:", on_roulette_report, False),
    ("modapp:", on_moder_app_decision, False),
    ("claim_vip", on_claim_vip, True),
    ("claim_moder", on_claim_moder, True),
    ("ref_info", on_ref_info, True),
    ("tgban:", on_tg_ban, False),
    ("nl:", on_nearby_like, False),
    ("nd:", on_nearby_like, False),
    ("nr:", on_nearby_like, False),
    ("refund_pick:", on_refund_pick, False),
    ("refund_do:", on_refund_do, False),
    ("refund_cancel", on_refund_cancel, True),
    ("anon_watch_leave", on_anon_watch_leave, True),
]


# ============================ НАВИГАЦИЯ В ШАПКЕ ============================
async def on_subgate_check(update, context):
    """Проверка подписки на входе."""
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


async def on_roulette_report(update, context):
    """Жалоба из рулетки по инлайн-кнопке."""
    query = update.callback_query
    await query.answer()
    session_id = int(query.data.split(":")[1])
    session = conn.execute("SELECT * FROM roulette_sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        await query.answer(t("session_not_found"), show_alert=True)
        return
    reporter_id = query.from_user.id
    if reporter_id == session["user1_id"]:
        reported_id = session["user2_id"]
    elif reporter_id == session["user2_id"]:
        reported_id = session["user1_id"]
    else:
        return
    context.user_data["state"] = "awaiting_report_reason"
    context.user_data["report_context"] = "roulette"
    context.user_data["report_ref_id"] = session_id
    context.user_data["reported_id"] = reported_id
    await query.message.reply_text(t("report_choose"), reply_markup=report_reason_kb())


async def show_help(update, context):
    """Кнопка Помощь."""
    uid = update.effective_user.id
    await nav(update, context, t("help"), main_menu_kb(uid), parse_mode="HTML")


async def process_adm_ad_wizard(update, context):
    """Заглушка для рекламы (если что-то вызовет)."""
    context.user_data["state"] = None
    await update.message.reply_text("Функция недоступна.", reply_markup=admin_menu_kb())


# ============================ TEXT ROUTER ============================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех текстовых сообщений."""
    state = context.user_data.get("state")
    text = canon(update.message.text) if update.message else None
    raw_text = update.message.text if update.message else ""

    _u = get_user(update.effective_user.id)
    if _u and is_banned(_u) and not is_admin(update.effective_user.id):
        await update.message.reply_text(t("banned"))
        return

    # Скрытая команда /sex_approve <id> — только для модера
    if raw_text and raw_text.startswith("/sex_approve"):
        uid = update.effective_user.id
        if is_moder(get_user(uid)):
            parts = raw_text.split()
            if len(parts) == 2 and parts[1].isdigit():
                await sex_approve_cmd(update, context, int(parts[1]))
            else:
                await update.message.reply_text("Использование: /sex_approve <user_id>")
        return

    # Восстановление незавершённого анона по ссылке
    if not state:
        _fl = load_link_flow(update.effective_user.id)
        if _fl:
            context.user_data["state"] = _fl["state"]
            context.user_data["anon_target"] = _fl["target_id"]
            if _fl["msg_type"]:
                context.user_data["anon_type"] = _fl["msg_type"]
            state = _fl["state"]

    _NO_NAV = {
        "awaiting_anon_content", "awaiting_reply", "modmsg_text",
        "rchat", "tg_watch", "sex_room", "sex_create_name", "sex_rename",
        "anon_watch",
        "shop_add_title", "shop_edit_name",
        "adm_bcast_content", "adm_bcast_btn_ask", "adm_bcast_btn_text", "adm_bcast_btn_url",
        "adm_ch_name", "adm_ch_link", "adm_ch_confirm",
    }

    _NAV = {
        "Моя ссылка": show_link_menu,
        "Поблизости": nearby_menu,
        "Чат-рулетка": show_roulette_entry,
        "Профиль": show_profile,
        "Магазин": show_shop,
        "Пригласить": show_referral,
        "Помощь": show_help,
        "Язык": show_language_menu,
        "Купить коины": show_star_shop,
        "Меню": go_home,
    }

    if (text in _NAV and state not in _NO_NAV
            and not (state and state.startswith("moder_q_"))):
        if text in ("Магазин",):
            context.user_data["state"] = None
        await _NAV[text](update, context)
        return

    # --- Чат-рулетка ---
    if state == "rchat":
        if text == "Далее":
            await rchat_next(update, context)
            return
        if text == "Стоп":
            await rchat_stop(update, context)
            return
        if await relay_roulette_message(update, context):
            return
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return

    if state == "rleft":
        if text == "Новый поиск":
            await rleft_research(update, context)
            return
        if text == "Пожаловаться":
            await rleft_report(update, context)
            return
        if text == "Назад":
            context.user_data["state"] = None
            await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
            return
        await update.message.reply_text(t("roulette_left"), reply_markup=left_chat_kb())
        return

    # --- Регистрация ---
    if state in ("set_gender_first", "set_gender_profile"):
        await set_gender_from_text(update, context)
        return
    if state in ("set_age_first", "set_age_profile"):
        await set_age_from_text(update, context)
        return

    # --- Основные флоу ---
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

    # --- Поблизости (мастер) ---
    if state and state.startswith("nearby_") and state != "nearby_menu":
        if state == "nearby_view":
            await update.message.reply_text(t("choose_on_kb"), reply_markup=nearby_browse_kb())
            return
        await nearby_create_router(update, context)
        return
    if state == "nearby_menu":
        await nearby_router(update, context)
        return

    # --- Рулетка-меню ---
    if state == "roulette_pref":
        await roulette_pref_router(update, context)
        return

    # --- Язык ---
    if state == "language":
        await language_router(update, context)
        return

    # --- Ссылка-меню ---
    if state == "link_menu":
        await link_menu_router(update, context)
        return

    # --- Профиль ---
    if state == "profile":
        await profile_router(update, context)
        return

    # --- Подарок коинов ---
    if state in ("giftcoins_id", "giftcoins_amount"):
        await gift_coins_router(update, context)
        return

    # --- Магазин ---
    if state == "shop":
        await shop_router(update, context)
        return
    if state == "shop_confirm":
        await shop_confirm_router(update, context)
        return
    if state in ("shop_add_title", "shop_add_price", "shop_add_reward",
                 "shop_add_amount", "shop_add_days"):
        await process_shop_add(update, context)
        return
    if state in ("shop_edit_name", "shop_edit_price", "shop_edit_amount", "shop_edit_days"):
        await process_shop_edit_value(update, context)
        return
    if state in ("shop_edit_pick", "shop_edit_menu"):
        await shop_edit_router(update, context)
        return

    # --- Анкета модера ---
    if state and state.startswith("moder_q_"):
        await moder_q_router(update, context)
        return
    if state in ("moder_give_id", "moder_take_id"):
        await process_moder_give_take(update, context)
        return

    # --- Рефералы ---
    if state == "referral":
        await referral_router(update, context)
        return
    if state == "ref_settings":
        await ref_settings_router(update, context)
        return
    if state in ("ref_set_vip_days", "ref_set_vip_threshold",
                 "ref_set_moder_days", "ref_set_moder_threshold"):
        await process_ref_setting_value(update, context)
        return

    # --- Stars ---
    if state == "star_shop":
        await star_shop_router(update, context)
        return
    if state == "star_confirm":
        await star_confirm_router(update, context)
        return
    if state in ("star_add_title", "star_add_coins", "star_add_price", "star_del"):
        await process_star_wizard(update, context)
        return
    if state == "star_admin":
        await star_admin_router(update, context)
        return

    # --- Бан ---
    if state == "ban_id":
        await process_ban(update, context)
        return

    # --- /tg /next /anon ---
    if state == "tg_pick":
        await process_tg_pick(update, context)
        return
    if state == "tg_watch":
        if canon(update.message.text) == "Выйти":
            detach_spectator(update.effective_user.id)
            context.user_data["state"] = None
            await update.message.reply_text(
                t("main_menu"), reply_markup=main_menu_kb(update.effective_user.id),
            )
        return
    if state == "modmsg_id":
        await process_modmsg_id(update, context)
        return
    if state == "modmsg_text":
        await process_modmsg_text(update, context)
        return
    if state == "anon_pick":
        await process_anon_pick(update, context)
        return
    if state == "anon_watch":
        await update.message.reply_text("Наблюдение активно. Кнопка «Выйти» — под файлом.")
        return

    # --- /sex ---
    if state == "sex_create_name":
        await sex_create_router(update, context)
        return
    if state == "sex_rename":
        await sex_rename_router(update, context)
        return
    if state == "sex_room":
        await sex_room_router(update, context)
        return

    # --- Админка ---
    if state == "admin_moder":
        await admin_moder_router(update, context)
        return
    if state in ("admin_vip", "vip_give_id", "vip_give_days", "vip_take_id",
                 "vip_bulk_days", "vip_bulk_menu"):
        await admin_vip_router(update, context)
        return
    if state and state.startswith("adm_coins_"):
        await process_adm_coins_wizard(update, context)
        return
    if state == "adm_reveal_price":
        await process_adm_reveal_price(update, context)
        return
    if state in ("adm_channels_menu", "adm_ch_name", "adm_ch_link",
                 "adm_ch_confirm", "adm_ch_delete"):
        await adm_channels_router(update, context)
        return
    if state == "adm_bcast_audience":
        await process_bcast_audience_text(update, context)
        return
    if state == "adm_bcast_content":
        await process_bcast_content(update, context)
        return
    if state == "adm_bcast_btn_ask":
        await process_bcast_btn_ask(update, context)
        return
    if state == "adm_bcast_btn_text":
        await process_bcast_btn_text(update, context)
        return
    if state == "adm_bcast_btn_url":
        await process_bcast_btn_url(update, context)
        return

    # Релей рулетки
    if await relay_roulette_message(update, context):
        return

    # --- Отмена поиска ---
    if text == "Отменить поиск":
        uid = update.effective_user.id
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.commit()
        context.user_data["state"] = "roulette_pref"
        await nav(update, context,
                  t("search_cancelled") + "\n\n" + t("roulette_who"),
                  roulette_pref_reply_kb())
        return

    # --- Кнопки админки ---
    if is_admin(update.effective_user.id):
        if text == "Статистика":
            await adm_stats_msg(update, context)
            return
        if text == "Выгрузить пользователей":
            await adm_export_msg(update, context)
            return
        if text == "Начислить коины":
            context.user_data["state"] = "adm_coins_id"
            await update.message.reply_text("Введи tg_id или @username:", reply_markup=cancel_reply_kb())
            return
        if text == "Обязательные каналы":
            await adm_channels_msg(update, context)
            return
        if text == "Рассылка":
            context.user_data["state"] = "adm_bcast_audience"
            await update.message.reply_text("Кому отправить рассылку?", reply_markup=bcast_audience_kb())
            return
        if text == "Модеры":
            await show_admin_moder(update, context)
            return
        if text == "Бан / Разбан":
            await start_ban(update, context, "admin")
            return
        if text == "Коины за Stars":
            await show_star_admin(update, context)
            return
        if text == "Возврат Stars":
            await show_stars_refund(update, context)
            return
        if text == "Цена раскрытия":
            cur = get_setting_int("reveal_stars", 1)
            context.user_data["state"] = "adm_reveal_price"
            await update.message.reply_text(
                f"⭐ Цена раскрытия отправителя\n\nСейчас: <b>{cur} Star</b>\n\nВведите новое число ≥ 1:",
                parse_mode="HTML", reply_markup=cancel_reply_kb(),
            )
            return
        if text == "VIP по ID":
            context.user_data["state"] = "admin_vip"
            await update.message.reply_text(
                t("admin_vip_menu"), parse_mode="HTML", reply_markup=admin_vip_kb(),
            )
            return

    # --- Главное меню (кнопки) ---
    if text == "Моя ссылка":
        await show_link_menu(update, context)
        return
    if text == "Поблизости":
        await nearby_menu(update, context)
        return
    if text == "Чат-рулетка":
        await show_roulette_entry(update, context)
        return
    if text == "Профиль":
        await show_profile(update, context)
        return
    if text == "Магазин":
        context.user_data["state"] = None
        await show_shop(update, context)
        return
    if text == "Купить коины":
        await show_star_shop(update, context)
        return
    if text == "Пригласить":
        await show_referral(update, context)
        return
    if text == "Помощь":
        await show_help(update, context)
        return
    if text == "Язык":
        await show_language_menu(update, context)
        return
    if text == "Админка":
        context.user_data["state"] = None
        await show_admin_menu(update, context)
        return
    if text == "Модерка":
        await show_moder_menu(update, context)
        return

    # --- Панель модера ---
    if state == "moder":
        await moder_panel_router(update, context)
        return

    if text == "Назад":
        context.user_data["state"] = None
        await nav(update, context, t("main_menu"), main_menu_kb(update.effective_user.id))
        return

    await nav(update, context, t("not_understood"), main_menu_kb(update.effective_user.id))


# ============================ MEDIA ROUTER ============================
async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Голос/фото/стикеры/видео/кружки/документы."""
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

    if state == "ref_set_photo" and is_admin(update.effective_user.id):
        if update.message and update.message.photo:
            set_setting("ref_photo", update.message.photo[-1].file_id)
            await update.message.reply_text("Фото сохранено.")
            await show_ref_settings(update, context)
        else:
            await update.message.reply_text("Отправьте именно фото (или «Отмена»).", reply_markup=cancel_reply_kb())
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
    if state == "nearby_photo":
        await nearby_photo_handler(update, context)
        return
    if state == "sex_room":
        await sex_room_router(update, context)
        return

    if await relay_roulette_message(update, context):
        return


# ============================ HANDLER REGISTRATION ============================
def _mu(message):
    return UpdateShim(message=message, effective_user=message.from_user,
                      effective_chat=message.chat)


def _cu(cq):
    return UpdateShim(callback_query=_CB(cq), effective_user=cq.from_user,
                      effective_chat=(cq.message.chat if cq.message else None))


async def _lang_middleware(handler, event, data):
    user = data.get("event_from_user")
    if user:
        set_cur_lang(get_lang(user.id))
        touch_user(user.id)
    else:
        set_cur_lang("ru")
    return await handler(event, data)


async def _h_start(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    await cmd_start(_mu(message), Ctx(message.from_user.id, args=args))


async def _h_payment(message: Message):
    await on_successful_payment(_mu(message), Ctx(message.from_user.id))


async def _h_precheckout(pcq: PreCheckoutQuery):
    upd = UpdateShim(pre_checkout_query=pcq, effective_user=pcq.from_user)
    await on_precheckout(upd, Ctx(pcq.from_user.id))


async def _h_my_chat_member(event: ChatMemberUpdated):
    upd = UpdateShim(my_chat_member=event, effective_user=event.from_user, effective_chat=event.chat)
    await on_my_chat_member(upd, Ctx(event.from_user.id))


async def _h_media(message: Message):
    await media_router(_mu(message), Ctx(message.from_user.id))


async def _h_text(message: Message):
    await text_router(_mu(message), Ctx(message.from_user.id))


async def _h_cmd_tg(message: Message):
    if not is_staff(message.from_user.id):
        return
    await tg_start(_mu(message), Ctx(message.from_user.id))


async def _h_cmd_next(message: Message):
    if not is_staff(message.from_user.id):
        return
    await modmsg_start(_mu(message), Ctx(message.from_user.id))


async def _h_cmd_anon(message: Message):
    if not is_staff(message.from_user.id):
        return
    await anon_start(_mu(message), Ctx(message.from_user.id))


async def _h_cmd_sex(message: Message):
    # /sex — ТОЛЬКО для модераторов (не админ)
    uid = message.from_user.id
    if is_admin(uid):
        await message.answer("🛡 Команда доступна только модераторам, не админам.")
        return
    u = get_user(uid)
    if not is_moder(u):
        await message.answer(t("sex_only_moder"))
        return
    await sex_start(_mu(message), Ctx(message.from_user.id))


def _make_cb_handler(fn):
    async def _handler(cq: CallbackQuery):
        await fn(_cu(cq), Ctx(cq.from_user.id))
    return _handler


def register_handlers():
    dp.update.outer_middleware(_lang_middleware)
    dp.errors.register(on_error)

    dp.message.register(_h_start, CommandStart())
    dp.message.register(_h_cmd_tg, Command("tg"))
    dp.message.register(_h_cmd_next, Command("next"))
    dp.message.register(_h_cmd_anon, Command("anon"))
    dp.message.register(_h_cmd_sex, Command("sex"))
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


# ============================ ON_ERROR ============================
async def on_error(event: ErrorEvent):
    err = event.exception
    if isinstance(err, TelegramConflictError):
        log.warning("⚠️ Conflict: бот запущен в нескольких местах!")
        return True
    if isinstance(err, TelegramForbiddenError):
        log.debug("Forbidden: %s", err)
        return True
    log.error("Ошибка апдейта: %s", err, exc_info=True)
    return True


# ============================ ON_MY_CHAT_MEMBER ============================
async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловим блокировку/разблокировку бота."""
    cm = update.my_chat_member
    if not cm or cm.chat.type != "private":
        return
    new_status = cm.new_chat_member.status
    try:
        old_status = cm.old_chat_member.status
    except AttributeError:
        old_status = None
    uid = cm.from_user.id

    if new_status in ("kicked", "banned"):
        try:
            sess = get_active_session(uid)
            if sess:
                await force_end_session(context, sess["id"])
        except Exception as e:
            log.warning("end session on block %s: %s", uid, e)
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.commit()
        ref = conn.execute("SELECT * FROM referrals WHERE referred_id=? AND active=1", (uid,)).fetchone()
        if ref:
            conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?",
                         (ref["coins_awarded"], ref["referrer_id"]))
            conn.execute("UPDATE referrals SET active=0 WHERE id=?", (ref["id"],))
            conn.commit()
            try:
                _sl = cur_lang()
                set_cur_lang(get_lang(ref["referrer_id"]))
                await context.bot.send_message(
                    ref["referrer_id"],
                    t("ref_coins_refunded", n=ref["coins_awarded"]),
                    parse_mode="HTML",
                )
                set_cur_lang(_sl)
            except TelegramError:
                pass
        purged = False
        if user_is_disposable(uid):
            if purge_user(uid):
                purged = True
        extra = "Пустой аккаунт удалён из базы." if purged else None
        await notify_admins_user_event(context, cm.from_user, "blocked", extra=extra)
    elif new_status == "member":
        ref = conn.execute("SELECT * FROM referrals WHERE referred_id=? AND active=0", (uid,)).fetchone()
        if ref:
            conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?",
                         (ref["coins_awarded"], ref["referrer_id"]))
            conn.execute("UPDATE referrals SET active=1 WHERE id=?", (ref["id"],))
            conn.commit()
        if old_status in ("kicked", "banned"):
            await notify_admins_user_event(context, cm.from_user, "unblocked")


# ============================ ФОНОВЫЕ ЦИКЛЫ ============================
async def _matchmaker_loop():
    ctx = Ctx(0)
    tick = 0
    while True:
        await asyncio.sleep(ROULETTE_TICK_SECONDS)
        try:
            await roulette_matchmaker(ctx)
        except Exception as e:
            log.error("matchmaker: %s", e)
        tick += 1
        if tick % 20 == 0:
            try:
                await queue_maintenance(ctx)
                await end_dead_sessions(ctx)
            except Exception as e:
                log.error("queue_maintenance: %s", e)


def run_safe_cleanup():
    """Безопасная очистка мусора."""
    try:
        six_h = (now_dt() - timedelta(hours=6)).isoformat()
        ten_min = (now_dt() - timedelta(minutes=120)).isoformat()
        old_sessions = (now_dt() - timedelta(days=30)).isoformat()
        old_anon = (now_dt() - timedelta(days=90)).isoformat()
        del_anon = (now_dt() - timedelta(days=1)).isoformat()
        old_reports = (now_dt() - timedelta(days=30)).isoformat()

        conn.execute("DELETE FROM link_flow WHERE updated_at < ?", (six_h,))
        conn.execute("DELETE FROM roulette_queue WHERE joined_at < ?", (ten_min,))
        conn.execute("DELETE FROM bans WHERE until < ?", (now_iso(),))
        conn.execute(
            "DELETE FROM roulette_sessions WHERE active=0 AND ended_at IS NOT NULL AND ended_at < ?",
            (old_sessions,),
        )
        conn.execute("DELETE FROM anon_messages WHERE deleted=1 AND created_at < ?", (del_anon,))
        conn.execute("DELETE FROM anon_messages WHERE created_at < ?", (old_anon,))
        conn.execute("DELETE FROM reports WHERE status <> 'pending' AND created_at < ?", (old_reports,))
        # Удаление истёкших старых ссылок
        conn.execute("UPDATE users SET old_link=NULL, old_link_until=NULL WHERE old_link_until IS NOT NULL AND old_link_until < ?", (now_iso(),))
        # Удаление заявок на выход старше 3 часов
        three_h = (now_dt() - timedelta(hours=3)).isoformat()
        conn.execute("DELETE FROM sex_exit_requests WHERE status='pending' AND created_at < ?", (three_h,))
        conn.commit()

        if not DATABASE_URL:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as _e:
                log.warning("wal_checkpoint: %s", _e)
        log.info("janitor: безопасная очистка выполнена")
    except Exception as e:
        log.warning("safe_cleanup: %s", e)


async def _nudge_user(u) -> bool:
    uid = u["tg_id"]
    try:
        na = u["nudged_at"]
        if na:
            try:
                if now_dt() - datetime.fromisoformat(na) < timedelta(days=JANITOR_PERIOD_DAYS - 1):
                    return False
            except (ValueError, TypeError):
                pass
        _sl = cur_lang()
        set_cur_lang(get_lang(uid))
        await BOTP.send_message(uid, t("inactive_nudge"), parse_mode="HTML")
        set_cur_lang(_sl)
        conn.execute("UPDATE users SET nudged_at=? WHERE tg_id=?", (now_iso(), uid))
        conn.commit()
        await asyncio.sleep(0.05)
        return True
    except TelegramError:
        return False
    except Exception as e:
        log.warning("nudge %s: %s", uid, e)
        return False


async def janitor_heavy():
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
        if is_admin(uid) or is_staff(uid):
            continue
        has_stars = conn.execute("SELECT 1 FROM star_purchases WHERE user_id=? LIMIT 1", (uid,)).fetchone()
        has_ref = conn.execute("SELECT 1 FROM referrals WHERE referrer_id=? AND active=1 LIMIT 1", (uid,)).fetchone()
        invested = (u["coins"] or 0) > 0 or is_vip(u) or bool(has_stars)

        if invested:
            if await _nudge_user(u):
                nudged += 1
        elif has_ref or u["custom_link"]:
            if await _nudge_user(u):
                nudged += 1
        else:
            active_sess = conn.execute(
                "SELECT id FROM roulette_sessions WHERE active=1 AND (user1_id=? OR user2_id=?) LIMIT 1",
                (uid, uid),
            ).fetchone()
            if active_sess:
                continue
            try:
                conn.execute("DELETE FROM users WHERE tg_id=?", (uid,))
                conn.execute("DELETE FROM referrals WHERE referred_id=?", (uid,))
                conn.execute("DELETE FROM link_flow WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
                conn.commit()
                deleted += 1
            except Exception as e:
                log.warning("janitor delete %s: %s", uid, e)

    log.info("janitor (раз в 2 недели): удалено=%d, уведомлено=%d", deleted, nudged)
    if ADMIN_IDS and (deleted or nudged):
        for aid in ADMIN_IDS:
            try:
                await BOTP.send_message(
                    aid,
                    f"🧹 Авто-обслуживание:\n"
                    f"Удалено пустых аккаунтов: {deleted}\n"
                    f"Напоминаний неактивным: {nudged}",
                )
            except TelegramError:
                pass


async def janitor_unreachable_sweep():
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
            await bot.send_chat_action(tid, "typing")
        except TelegramForbiddenError:
            if user_is_disposable(tid) and purge_user(tid):
                removed += 1
        except TelegramError:
            pass
        await asyncio.sleep(0.1)
    if removed:
        log.info("janitor sweep: проверено=%d, удалено=%d", checked, removed)
    return checked, removed


async def _janitor_loop():
    await asyncio.sleep(120)
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
                if not DATABASE_URL:
                    try:
                        conn.commit()
                        conn.execute("VACUUM")
                        log.info("janitor: VACUUM выполнен")
                    except Exception as e:
                        log.warning("VACUUM: %s", e)
        except Exception as e:
            log.error("janitor_loop: %s", e)
        await asyncio.sleep(JANITOR_WAKE_HOURS * 3600)


# ============================ KEEP-ALIVE ============================
def _keep_alive_server():
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
    except Exception as e:
        log.warning("keep-alive server: %s", e)


# ============================ ЗАПУСК ============================
async def _run():
    init_db()
    register_handlers()

    try:
        await bot.set_my_commands([BotCommand(command="start", description="Запустить бота")])
    except Exception as e:
        log.warning("set_my_commands: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    asyncio.create_task(_matchmaker_loop())
    asyncio.create_task(_janitor_loop())

    log.info("🚀 Бот запущен, поллинг...")
    while True:
        try:
            await dp.start_polling(bot)
            break
        except TelegramConflictError as e:
            log.error("❌ Conflict: несколько инстансов бота. %s", e)
            break
        except Exception as e:
            log.error("Поллинг упал, перезапуск через 5с: %s", e)
            await asyncio.sleep(5)


def main():
    threading.Thread(target=_keep_alive_server, daemon=True).start()
    asyncio.run(_run())


# ================================================================
# ============ ЧАСТЬ 14 ЗАКОНЧЕНА — ФАЙЛ ПОЛНЫЙ ===================
# ================================================================
if __name__ == "__main__":
    main()
