"""
𐌽ꤕ𐌗ተ — анонимный Telegram-бот (aiogram v3, SQLite / PostgreSQL).
"""
from __future__ import annotations
import os, sqlite3, logging, random, re, string, urllib.parse, urllib.request
import json, html, asyncio, threading, contextvars, time as _time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramConflictError
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated, PreCheckoutQuery, ErrorEvent,
    ReplyKeyboardRemove, ReplyParameters, BufferedInputFile, BotCommand,
    KeyboardButton as _AiKB, ReplyKeyboardMarkup as _AiRKM,
    InlineKeyboardButton as _AiIKB, InlineKeyboardMarkup as _AiIKM,
    LabeledPrice as _AiLP,
)
TelegramError = TelegramAPIError

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("anon_bot")
boot = logging.getLogger("anon_bot.boot")

load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN", "") or "").strip()
ADMIN_IDS = {int(x) for x in (os.getenv("ADMIN_IDS", "") or "").split(",") if x.strip().isdigit()}
if not BOT_TOKEN or ":" not in BOT_TOKEN:
    boot.critical("❌ BOT_TOKEN не задан или неверный формат"); raise SystemExit(1)
if not ADMIN_IDS:
    boot.warning("⚠️ ADMIN_IDS пустой — админка недоступна")
boot.info("✅ bot_id=%s, adminов=%d", BOT_TOKEN.split(":", 1)[0], len(ADMIN_IDS))
SUPER_ADMIN_ID = min(ADMIN_IDS) if ADMIN_IDS else 0

_lang_var = contextvars.ContextVar("cur_lang", default="ru")
def cur_lang(): return _lang_var.get()
def set_cur_lang(v): _lang_var.set(v)

def KeyboardButton(text, **kw): return _AiKB(text=text, **kw)
class ReplyKeyboardMarkup(_AiRKM):
    def __init__(self, keyboard, resize_keyboard=False, one_time_keyboard=False, **kw):
        super().__init__(keyboard=keyboard, resize_keyboard=resize_keyboard,
                         one_time_keyboard=one_time_keyboard, **kw)
def InlineKeyboardButton(text, **kw): return _AiIKB(text=text, **kw)
def InlineKeyboardMarkup(inline_keyboard, **kw): return _AiIKM(inline_keyboard=inline_keyboard, **kw)
def LabeledPrice(label=None, amount=None, **kw):
    if label is not None: kw.setdefault("label", label)
    if amount is not None: kw.setdefault("amount", amount)
    return _AiLP(**kw)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties())
dp = Dispatcher()
_HTML_TAG_RE = re.compile(r'<(b|i|u|s|code|pre|a|blockquote|tg-emoji|span|strong|em)[\s>/]', re.I)
def _needs_html(t): return isinstance(t, str) and bool(_HTML_TAG_RE.search(t))

class _BotProxy:
    def __init__(self, real_bot): self._bot = real_bot
    def __getattr__(self, name): return getattr(self._bot, name)
    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        if reply_to_message_id is not None:
            kw["reply_parameters"] = ReplyParameters(message_id=reply_to_message_id)
        if kw.get("parse_mode") is None and _needs_html(text): kw["parse_mode"] = "HTML"
        return await self._bot.send_message(chat_id, text, **kw)
    async def send_document(self, chat_id, document=None, **kw):
        if hasattr(document, "read"):
            raw = document.read()
            if isinstance(raw, str): raw = raw.encode("utf-8")
            fname = os.path.basename(getattr(document, "name", "") or "file.txt")
            document = BufferedInputFile(raw, filename=fname)
        return await self._bot.send_document(chat_id, document, **kw)

BOTP = _BotProxy(bot)
UD = defaultdict(dict)
def ud(uid): return UD[uid]

class _Msg:
    def __init__(self, m): self._m = m
    def __getattr__(self, n): return getattr(self._m, n)
    @property
    def chat_id(self): return self._m.chat.id
    async def reply_text(self, text, reply_markup=None, parse_mode=None, reply_to_message_id=None, **kw):
        if reply_to_message_id is not None:
            kw["reply_parameters"] = ReplyParameters(message_id=reply_to_message_id)
        if parse_mode is None and _needs_html(text): parse_mode = "HTML"
        return await self._m.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, **kw)
    async def delete(self): return await self._m.delete()

class _CB:
    def __init__(self, cq):
        self._cq = cq; self.data = cq.data; self.from_user = cq.from_user
        self.message = _Msg(cq.message) if cq.message else None
    async def answer(self, text=None, show_alert=False, **kw):
        return await self._cq.answer(text=text, show_alert=show_alert, **kw)
    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        if parse_mode is None and _needs_html(text): parse_mode = "HTML"
        return await self._cq.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode, **kw)

class UpdateShim:
    def __init__(self, message=None, callback_query=None, pre_checkout_query=None,
                 my_chat_member=None, effective_user=None, effective_chat=None):
        self.message = _Msg(message) if message is not None else None
        self.callback_query = callback_query; self.pre_checkout_query = pre_checkout_query
        self.my_chat_member = my_chat_member
        self.effective_user = effective_user; self.effective_chat = effective_chat
Update = UpdateShim
class ContextTypes: DEFAULT_TYPE = object
class Ctx:
    def __init__(self, uid, args=None, error=None):
        self.bot = BOTP; self._uid = uid; self.user_data = UD[uid]
        self.args = args or []; self.error = error

DB_PATH = (os.getenv("DB_PATH", "").strip()
           or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db"))
DAILY_LIMIT = 20; BAN_DAYS = 7; ROULETTE_BAN_DAYS = 30
ANON_BAN_FOREVER = "9999-12-31T23:59:59"; ROULETTE_TICK_SECONDS = 3
SEARCH_TIMEOUT_MIN = 30; SEARCH_REMIND_MIN = 5
LINK_CHANGE_COOLDOWN_DAYS = 3; LINK_OLD_TTL_HOURS = 24
VIP_DISCOUNT_PERCENT = 20; VIP_DAILY_BONUS = 5; WELCOME_COOLDOWN_MIN = 10
REF_REWARD_NORMAL = 50; REF_REWARD_VIP = 100; REF_INVITED_BONUS = 100
REF_INVITED_BONUS_VIP = 200; REF_VIP_THRESHOLD = 5; REF_VIP_DAYS = 7
REF_MODER_THRESHOLD = 10; REF_MODER_DAYS = 7
LINK_REWARD_EVERY = 10; LINK_REWARD_COINS = 20
STARS_REFUND_PERCENT = 50; CREATOR_USERNAME = "@ToxIc_0707"
INACTIVE_DAYS = 14; JANITOR_WAKE_HOURS = 6; JANITOR_PERIOD_DAYS = 14
NEXT_MIN_PROFILES = 100; NEXT_REPEAT_LIMIT = 3
NEXT_REPEAT_WINDOW_DAYS = 7; NEXT_NOTIF_TTL_DAYS = 14
VIP_PACKAGES = [
    {"months": 1, "stars": 100, "label": "1 месяц"},
    {"months": 2, "stars": 180, "label": "2 месяца"},
    {"months": 3, "stars": 250, "label": "3 месяца"},
]
REVEAL_FREE_PER_MONTH = 3; REVEAL_MAX_PACK = 5
REVEAL_PACKAGES = [
    {"count": 1, "stars": 5, "discount": 0},
    {"count": 2, "stars": 8, "discount": 20},
    {"count": 3, "stars": 11, "discount": 27},
    {"count": 4, "stars": 14, "discount": 30},
    {"count": 5, "stars": 16, "discount": 36},
]
REVEAL_AUTO_MSG = "👋 Привет! Я {name}, из бота 𝐍𝐞𝐱𝐭.. — хочу познакомиться 😊"
BCAST_SKIP_VIP_IN_NEXT = True

def _safe(func, *args, default=None):
    try: return func(*args)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError): return default

DATABASE_URL = (os.getenv("DATABASE_URL", "").strip()
    or os.getenv("POSTGRES_URL", "").strip() or os.getenv("NEON_DATABASE_URL", "").strip())
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    _pg_lock = threading.RLock()
    class _Row(dict):
        def __init__(self, cols, vals):
            super().__init__(zip(cols, vals)); self._vals = list(vals)
        def __getitem__(self, k):
            if isinstance(k, int): return self._vals[k]
            return dict.__getitem__(self, k)
    class _PgCursor:
        def __init__(self, raw):
            self._raw = raw
            self._cols = [d[0] for d in raw.description] if raw.description else []
            try: self._rows = raw.fetchall() if raw.description else []
            except Exception: self._rows = []
            self._pos = 0; self._lastrowid = None
            if self._rows and "id" in self._cols:
                self._lastrowid = self._rows[0][self._cols.index("id")]
        def fetchone(self):
            if self._pos >= len(self._rows): return None
            r = self._rows[self._pos]; self._pos += 1
            return _Row(self._cols, r)
        def fetchall(self):
            rows = [_Row(self._cols, r) for r in self._rows[self._pos:]]
            self._pos = len(self._rows); return rows
        @property
        def lastrowid(self): return self._lastrowid
    def _translate_schema(script):
        s = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        return re.sub(r"\bINTEGER\b", "BIGINT", s)
    def _translate_sql_for_pg(sql):
        q = sql
        if re.search(r'\bINSERT\s+OR\s+IGNORE\b', q, re.I):
            q = re.sub(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', 'INSERT INTO', q, flags=re.I)
            if 'on conflict' not in q.lower(): q = q.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        if re.search(r'\bINSERT\s+OR\s+REPLACE\b', q, re.I):
            q = re.sub(r'\bINSERT\s+OR\s+REPLACE\s+INTO\b', 'INSERT INTO', q, flags=re.I)
        q = re.sub(r"strftime\('%s',\s*([^)]+)\)", r"EXTRACT(EPOCH FROM \1)", q)
        return q
    class _PgConnection:
        def __init__(self, url): self.url = url; self._conn = None; self._connect()
        def _connect(self):
            last_err = None
            for attempt in range(1, 6):
                try:
                    self._conn = psycopg2.connect(self.url, connect_timeout=15,
                        keepalives=1, keepalives_idle=30, keepalives_interval=10,
                        keepalives_count=5)
                    self._conn.autocommit = True
                    if attempt > 1: boot.info("PG подключился с попытки %d", attempt)
                    return
                except psycopg2.OperationalError as e:
                    last_err = e
                    if attempt < 5: boot.warning("PG connect %d/5: %s", attempt, e)
                    _time.sleep(2 ** attempt)
            boot.critical("❌ Не удалось подключиться к PostgreSQL: %s", last_err)
            raise SystemExit(1)
        def execute(self, sql, params=()):
            q = _translate_sql_for_pg(sql.replace("?", "%s"))
            if sql.lstrip()[:6].upper() == "INSERT" and "returning" not in q.lower():
                q = q.rstrip().rstrip(";") + " RETURNING *"
            with _pg_lock:
                for attempt in (1, 2):
                    try:
                        cur = self._conn.cursor(); cur.execute(q, params); return _PgCursor(cur)
                    except (psycopg2.OperationalError, psycopg2.InterfaceError):
                        if attempt == 2: raise
                        self._connect()
        def executescript(self, script):
            with _pg_lock:
                cur = self._conn.cursor(); cur.execute(_translate_schema(script))
                return _PgCursor(cur)
        def commit(self): pass
        def rollback(self):
            try: self._conn.rollback()
            except Exception: pass
        def cursor(self): return self
    conn = _PgConnection(DATABASE_URL)
    boot.info("🗄 БД: PostgreSQL")
else:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000"); conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-16000")
    except Exception as e: boot.warning("SQLite pragma: %s", e)
    boot.info("🗄 БД: SQLite (%s)", DB_PATH)
def db(): return conn
def init_db():
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, gender TEXT,
        search_pref TEXT, custom_link TEXT UNIQUE, old_link TEXT, old_link_until TEXT,
        link_changed_at TEXT, coins INTEGER NOT NULL DEFAULT 0, vip_until TEXT,
        is_moder INTEGER NOT NULL DEFAULT 0, is_banned INTEGER NOT NULL DEFAULT 0,
        last_bonus TEXT, lang TEXT NOT NULL DEFAULT 'ru', moder_until TEXT,
        link_sent_total INTEGER NOT NULL DEFAULT 0, link_answered_total INTEGER NOT NULL DEFAULT 0,
        link_sent_rewarded INTEGER NOT NULL DEFAULT 0, link_answered_rewarded INTEGER NOT NULL DEFAULT 0,
        ref_vip_claims INTEGER NOT NULL DEFAULT 0, ref_moder_claims INTEGER NOT NULL DEFAULT 0,
        last_active TEXT, nudged_at TEXT, admin_unlocked INTEGER NOT NULL DEFAULT 0,
        age TEXT, ref_code TEXT, last_greet TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS anon_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL,
        msg_type TEXT NOT NULL, content_type TEXT NOT NULL, text TEXT, voice_file_id TEXT,
        answer_text TEXT, answer_voice_file_id TEXT, answered INTEGER NOT NULL DEFAULT 0,
        deleted INTEGER NOT NULL DEFAULT 0, parent_id INTEGER, owner_chat_message_id INTEGER,
        sender_chat_message_id INTEGER, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL,
        reported_id INTEGER NOT NULL, context TEXT NOT NULL, reason TEXT, ref_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
        banned_id INTEGER NOT NULL, until TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS roulette_queue (
        user_id INTEGER PRIMARY KEY, gender TEXT NOT NULL, pref TEXT NOT NULL,
        is_vip INTEGER NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'normal',
        joined_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS roulette_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1, ended_by INTEGER,
        mode TEXT NOT NULL DEFAULT 'normal', started_at TEXT NOT NULL, ended_at TEXT
    );
    CREATE TABLE IF NOT EXISTS shop_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
        price INTEGER NOT NULL, is_vip INTEGER NOT NULL DEFAULT 0, duration_days INTEGER,
        reward_type TEXT NOT NULL DEFAULT 'manual', reward_amount INTEGER,
        title_uz TEXT, title_en TEXT, active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL, price_paid INTEGER NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS mandatory_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_username TEXT NOT NULL,
        title TEXT, added_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS moder_apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, item_id INTEGER,
        price_paid INTEGER NOT NULL DEFAULT 0, gender TEXT, age TEXT, tg_time TEXT,
        availability TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS star_packages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, title_uz TEXT,
        title_en TEXT, coins INTEGER NOT NULL, price_stars INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS star_purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, package_id INTEGER,
        coins INTEGER NOT NULL, stars INTEGER NOT NULL, charge_id TEXT,
        refunded INTEGER NOT NULL DEFAULT 0, refunded_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL UNIQUE, coins_awarded INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS link_flow (
        user_id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL, msg_type TEXT,
        state TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS nearby_profiles (
        user_id INTEGER PRIMARY KEY, name TEXT, age INTEGER, gender TEXT,
        looking_for TEXT, bio TEXT, photo_id TEXT, active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS nearby_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(from_id, to_id)
    );
    CREATE TABLE IF NOT EXISTS nearby_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(user1_id, user2_id)
    );
    CREATE TABLE IF NOT EXISTS nearby_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL,
        content_type TEXT NOT NULL, text TEXT, voice_file_id TEXT, parent_id INTEGER,
        owner_chat_message_id INTEGER, sender_chat_message_id INTEGER,
        answered INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS nearby_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, like_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(like_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS nearby_shown (
        id INTEGER PRIMARY KEY AUTOINCREMENT, viewer_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL, shown_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS nearby_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, type TEXT NOT NULL,
        target_id INTEGER, like_id INTEGER, expires_at TEXT NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sex_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        owner_id INTEGER NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sex_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, role TEXT NOT NULL, number INTEGER NOT NULL,
        joined_at TEXT NOT NULL, UNIQUE(room_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS sex_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL,
        sender_number INTEGER NOT NULL, content_type TEXT NOT NULL, text TEXT,
        voice_file_id TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sex_exit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL, UNIQUE(room_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS anon_watchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, mod_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, UNIQUE(mod_id, target_id)
    );
    CREATE TABLE IF NOT EXISTS vip_purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        months INTEGER NOT NULL, stars INTEGER NOT NULL, charge_id TEXT,
        refunded INTEGER NOT NULL DEFAULT 0, refunded_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reveal_purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        count INTEGER NOT NULL, stars INTEGER NOT NULL, charge_id TEXT,
        refunded INTEGER NOT NULL DEFAULT 0, refunded_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reveal_free_used (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        period TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id, period)
    );
    """)
    conn.commit()
    migrate()
    ensure_indexes()


def migrate():
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
            conn.execute(sql); conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    conn.commit()


def ensure_indexes():
    """Все индексы — безопасны для SQLite и PostgreSQL."""
    indexes = [
        # ---- Рулетка ----
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u1 ON roulette_sessions(active, user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u2 ON roulette_sessions(active, user2_id)",

        # ---- Анонимки ----
        "CREATE INDEX IF NOT EXISTS idx_anon_to ON anon_messages(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_from ON anon_messages(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_parent ON anon_messages(parent_id)",

        # ---- Жалобы / баны ----
        "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
        "CREATE INDEX IF NOT EXISTS idx_bans_pair ON bans(owner_id, banned_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_banned ON bans(banned_id)",

        # ---- Рефералы ----
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",

        # ---- Покупки ----
        "CREATE INDEX IF NOT EXISTS idx_starpur_user ON star_purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_vippur_user ON vip_purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_revpur_user ON reveal_purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_revfree_user ON reveal_free_used(user_id)",

        # ---- Пользователи ----
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_refcode ON users(ref_code)",
        "CREATE INDEX IF NOT EXISTS idx_users_lastactive ON users(last_active)",
        "CREATE INDEX IF NOT EXISTS idx_users_oldlink ON users(old_link)",

        # ---- Модерация ----
        "CREATE INDEX IF NOT EXISTS idx_moderapps_status ON moder_apps(status)",

        # ---- 𝐍𝐞𝐱𝐭.. лайки / мэтчи ----
        "CREATE INDEX IF NOT EXISTS idx_nearby_likes_from ON nearby_likes(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_likes_to ON nearby_likes(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_match_u1 ON nearby_matches(user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_nearby_match_u2 ON nearby_matches(user2_id)",

        # ---- 𝐍𝐞𝐱𝐭.. ЛС ----
        "CREATE INDEX IF NOT EXISTS idx_nbmsg_to ON nearby_messages(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbmsg_from ON nearby_messages(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbmsg_parent ON nearby_messages(parent_id)",

        # ---- 𝐍𝐞𝐱𝐭.. новое ----
        "CREATE INDEX IF NOT EXISTS idx_nban_like ON nearby_answers(like_id)",
        "CREATE INDEX IF NOT EXISTS idx_nban_user ON nearby_answers(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbshown_viewer ON nearby_shown(viewer_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbshown_target ON nearby_shown(target_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbshown_at ON nearby_shown(shown_at)",
        "CREATE INDEX IF NOT EXISTS idx_nbnotif_user ON nearby_notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_nbnotif_expires ON nearby_notifications(expires_at)",

        # ⭐ НОВЫЙ ИНДЕКС: ускоряет выборку анкет по полу для Next..
        "CREATE INDEX IF NOT EXISTS idx_nbprof_gender_active ON nearby_profiles(active, gender)",

        # ---- /sex ----
        "CREATE INDEX IF NOT EXISTS idx_sex_members_room ON sex_members(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_sex_messages_room ON sex_messages(room_id)",

        # ---- /anon ----
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
def now_iso(): return datetime.utcnow().isoformat()
def now_dt(): return datetime.utcnow()


# ============================ НАСТРОЙКИ ============================
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


def cfg_vip_days():        return get_setting_int("ref_vip_days", REF_VIP_DAYS)
def cfg_vip_threshold():   return max(1, get_setting_int("ref_vip_threshold", REF_VIP_THRESHOLD))
def cfg_moder_days():      return get_setting_int("ref_moder_days", REF_MODER_DAYS)
def cfg_moder_threshold(): return max(1, get_setting_int("ref_moder_threshold", REF_MODER_THRESHOLD))


# ============================ ПОЛЬЗОВАТЕЛИ ============================
UserRow = sqlite3.Row | dict | None


def get_user(tg_id):
    return conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def ensure_user(tg_id, username, first_name=None):
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


def touch_user(uid):
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


def resolve_user_ref(text):
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
def is_admin(tg_id): return tg_id in ADMIN_IDS
def is_super_admin(tg_id): return tg_id == SUPER_ADMIN_ID


def is_moder(user_row):
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


def is_staff(tg_id):
    if is_admin(tg_id):
        return True
    return is_moder(get_user(tg_id))


def is_banned(user_row):
    return bool(user_row) and bool(user_row["is_banned"])


def is_vip(user_row):
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


def is_unlimited(user_row):
    if not user_row:
        return False
    try:
        return is_admin(user_row["tg_id"]) or is_moder(user_row)
    except (KeyError, TypeError):
        return False


def user_age_int(user_row):
    try:
        a = user_row["age"]
    except (KeyError, IndexError, TypeError):
        return None
    if a is None:
        return None
    s = str(a).strip()
    return int(s) if s.isdigit() else None


# ============================ ЦЕНА ============================
def effective_price(price, user_row):
    if is_unlimited(user_row):
        return 0
    if is_vip(user_row):
        return max(0, round(price * (100 - VIP_DISCOUNT_PERCENT) / 100))
    return price


# ============================ УТИЛИТЫ ============================
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


def user_mention(user_row):
    if not user_row:
        return "—"
    name = user_row["first_name"] or "пользователь"
    if user_row["username"]:
        return f"{name} (@{user_row['username']})"
    return (f'<a href="tg://user?id={user_row["tg_id"]}">'
            f'{html.escape(name)}</a> (ID: {user_row["tg_id"]})')


def fmt_duration(seconds):
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


def has_forbidden_contacts(text):
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
    LANGS = ("ru", "uz", "en")
LANG_BUTTONS = {"Русский": "ru", "O'zbekcha": "uz", "English": "en"}

BTN = {
    # ==== Главное меню ====
    "🔗 Моя ссылка": ("🔗 Havolam", "🔗 My link"),
    "🎯 𝐍𝐞𝐱𝐭..": ("🎯 𝐍𝐞𝐱𝐭..", "🎯 𝐍𝐞𝐱𝐭.."),
    "🎲 Чат-рулетка": ("🎲 Chat-ruletka", "🎲 Chat roulette"),
    "👤 Профиль": ("👤 Profil", "👤 Profile"),
    "🛒 Магазин": ("🛒 Do'kon", "🛒 Shop"),
    "👥 Пригласить": ("👥 Taklif qilish", "👥 Invite"),
    "ℹ️ Помощь": ("ℹ️ Yordam", "ℹ️ Help"),
    "🌐 Язык": ("🌐 Til", "🌐 Language"),
    "💎 Купить коины": ("💎 Coin sotib olish", "💎 Buy coins"),
    "🛠 Админка": ("🛠 Admin panel", "🛠 Admin"),
    "🛡 Модерка": ("🛡 Moderator", "🛡 Moderation"),
    "⭐ Premium": ("⭐ Premium", "⭐ Premium"),
    # ==== Общие ====
    "✅ Да": ("✅ Ha", "✅ Yes"),
    "❌ Отмена": ("❌ Bekor qilish", "❌ Cancel"),
    "💎 Коины": ("💎 Coinlar", "💎 Coins"),
    "⏳ VIP": ("⏳ VIP", "⏳ VIP"),
    "🛡 Модер": ("🛡 Moder", "🛡 Moder"),
    "📦 Вручную": ("📦 Qo'lda", "📦 Manual"),
    # ==== Админка ====
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
    "✉️ Рассылка": ("✉️ Xabar tarqatish", "✉️ Broadcast"),
    "📢 Рассылка": ("📢 Xabar tarqatish", "📢 Broadcast"),
    "🛡 Модеры": ("🛡 Moderatorlar", "🛡 Moderators"),
    "🔨 Бан / Разбан": ("🔨 Ban / Unban", "🔨 Ban / Unban"),
    "⭐ Коины за Stars": ("⭐ Stars uchun coin", "⭐ Coins for Stars"),
    "⭐ Возврат Stars": ("⭐ Stars qaytarish", "⭐ Refund Stars"),
    "💎 Цена раскрытия": ("💎 Ochish narxi", "💎 Reveal price"),
    "➕ Добавить пакет коинов": ("➕ Coin paket qo'shish", "➕ Add coin package"),
    "🗑 Удалить пакет коинов": ("🗑 Coin paketni o'chirish", "🗑 Delete coin package"),
    "🛡 Модерка на неделю": ("🛡 Bir haftalik moder", "🛡 Moderator for a week"),
    "➕ Выдать модера": ("➕ Moder berish", "➕ Grant moder"),
    "➖ Забрать модера": ("➖ Moderni olish", "➖ Revoke moder"),
    "✏️ Изменить": ("✏️ O'zgartirish", "✏️ Edit"),
    # ==== Жалобы: действия ====
    "🔨 Бан": ("🔨 Ban", "🔨 Ban"),
    "✅ Разбан": ("✅ Unban", "✅ Unban"),
    "❌ Отклонить": ("❌ Rad etish", "❌ Reject"),
    # ==== Реф-настройки ====
    "👑 VIP: дней": ("👑 VIP: kun", "👑 VIP: days"),
    "👥 VIP: друзей": ("👥 VIP: do'st", "👥 VIP: friends"),
    "🛡 Модер: дней": ("🛡 Moder: kun", "🛡 Moder: days"),
    "👥 Модер: друзей": ("👥 Moder: do'st", "👥 Moder: friends"),
    "📷 Фото": ("📷 Foto", "📷 Photo"),
    "🚫 Убрать фото": ("🚫 Fotosiz", "🚫 No photo"),
    # ==== Общие ====
    "⬅️ Назад": ("⬅️ Orqaga", "⬅️ Back"),
    "🏠 Меню": ("🏠 Menyu", "🏠 Menu"),
    # ==== Пол ====
    "👨 Мужской": ("👨 Erkak", "👨 Male"),
    "👩 Женский": ("👩 Ayol", "👩 Female"),
    "👨 Парня": ("👨 Yigit", "👨 A guy"),
    "👩 Девушку": ("👩 Qiz", "👩 A girl"),
    "🤷 Любого": ("🤷 Farqi yo'q", "🤷 Anyone"),
    # ==== Профиль ====
    "✏️ Сменить пол": ("✏️ Jinsni o'zgartirish", "✏️ Change gender"),
    "✏️ Изменить возраст": ("✏️ Yoshni o'zgartirish", "✏️ Change age"),
    "🎁 Подарить коины": ("🎁 Coin sovg'a qilish", "🎁 Gift coins"),
    # ==== Ссылка ====
    "🔗 Показать ссылку": ("🔗 Havolani ko'rsatish", "🔗 Show link"),
    "✏️ Сменить ссылку": ("✏️ Havolani o'zgartirish", "✏️ Change link"),
    # ==== Анонимка ====
    "❓ Вопрос": ("❓ Savol", "❓ Question"),
    "💌 Валентинка": ("💌 Valentinka", "💌 Valentine"),
    # ==== Жалобы причины ====
    "🤬 Мат": ("🤬 So'kinish", "🤬 Swearing"),
    "💰 Мошенничество": ("💰 Firibgarlik", "💰 Fraud"),
    "😡 Оскорбление": ("😡 Haqorat", "😡 Insult"),
    "👎 Не нравится": ("👎 Yoqmadi", "👎 Dislike"),
    "🚩 Пожаловаться": ("🚩 Shikoyat qilish", "🚩 Report"),
    # ==== Рулетка ====
    "⛔ Отменить поиск": ("⛔ Qidiruvni bekor qilish", "⛔ Stop search"),
    "➡️ Далее": ("➡️ Keyingi", "➡️ Next"),
    "⏹️ Стоп": ("⏹️ To'xtatish", "⏹️ Stop"),
    "🔍 Новый поиск": ("🔍 Yangi qidiruv", "🔍 New search"),
    # ==== Рассылка ====
    "👥 Всем": ("👥 Hammaga", "👥 Everyone"),
    "👨 Мужчинам": ("👨 Erkaklarga", "👨 To men"),
    "👩 Женщинам": ("👩 Ayollarga", "👩 To women"),
    # ==== Магазин ====
    "➕ Добавить товар": ("➕ Mahsulot qo'shish", "➕ Add item"),
    "🗑 Удалить товар": ("🗑 Mahsulotni o'chirish", "🗑 Delete item"),
    "📝 Название": ("📝 Nomi", "📝 Name"),
    "💰 Цена": ("💰 Narxi", "💰 Price"),
    "⏳ Срок VIP": ("⏳ VIP muddati", "⏳ VIP duration"),
    "💎 Сумма коинов": ("💎 Coin miqdori", "💎 Coin amount"),
    # ==== Рефералы ====
    "🏆 Топ пригласивших": ("🏆 Top taklif qilganlar", "🏆 Top inviters"),
    # ==== 𝐍𝐞𝐱𝐭.. меню ====
    "🔥 Смотреть анкеты": ("🔥 Anketalarni ko'rish", "🔥 Browse profiles"),
    "📝 Моя анкета": ("📝 Mening anketam", "📝 My profile"),
    # ==== 𝐍𝐞𝐱𝐭.. карточка ====
    "❤️ Лайк": ("❤️ Layk", "❤️ Like"),
    "👎 Дизлайк": ("👎 Dizlayk", "👎 Dislike"),
    "💌 Написать": ("💌 Yozish", "💌 Write"),
    "🚩 Жалоба": ("🚩 Shikoyat", "🚩 Report"),
    "💤 Выйти": ("💤 Chiqish", "💤 Exit"),
    # ==== 𝐍𝐞𝐱𝐭.. уведомления ====
    "💕 Ответить": ("💕 Javob berish", "💕 Reply"),
    "💤 Игнорировать": ("💤 E'tiborsiz", "💤 Ignore"),
    "👁 Узнать": ("👁 Aniqlash", "👁 Reveal"),
    "👤 Перейти в профиль": ("👤 Profilga o'tish", "👤 Open profile"),
    # ==== 𝐍𝐞𝐱𝐭.. моя анкета ====
    "📝 Имя": ("📝 Ism", "📝 Name"),
    "🎂 Возраст": ("🎂 Yosh", "🎂 Age"),
    "📄 О себе": ("📄 O'zim haqimda", "📄 About me"),
    "👁 Предпросмотр": ("👁 Ko'rib chiqish", "👁 Preview"),
    "🎯 Кого ищу": ("🎯 Kimni qidiraman", "🎯 Looking for"),
    "⚧ Пол": ("⚧ Jins", "⚧ Gender"),
    # ==== Premium ====
    "📅 1 месяц · 100 ⭐": ("📅 1 oy · 100 ⭐", "📅 1 month · 100 ⭐"),
    "📅 2 месяца · 180 ⭐": ("📅 2 oy · 180 ⭐", "📅 2 months · 180 ⭐"),
    "📅 3 месяца · 250 ⭐": ("📅 3 oy · 250 ⭐", "📅 3 months · 250 ⭐"),
    "👁 Купить «Узнать»": ("👁 «Aniqlash» sotib olish", "👁 Buy «Reveal»"),
    # ==== Inline ====
    "↩️ Ответить": ("↩️ Javob berish", "↩️ Reply"),
    # ==== Голые эмодзи ====
    "❤️": ("❤️", "❤️"), "👎": ("👎", "👎"), "💌": ("💌", "💌"),
    "⛔": ("⛔", "⛔"), "💤": ("💤", "💤"),
    # ==== /sex ====
    "💬 Комната": ("💬 Xona", "💬 Room"),
    "👥 Участники": ("👥 Ishtirokchilar", "👥 Members"),
    "🚪 Запросить выход": ("🚪 Chiqishni so'rash", "🚪 Request exit"),
    "🛡 Одобрить выход": ("🛡 Chiqishni tasdiqlash", "🛡 Approve exit"),
    "🗑 Удалить комнату": ("🗑 Xonani o'chirish", "🗑 Delete room"),
    "✏️ Переименовать": ("✏️ Nomini o'zgartirish", "✏️ Rename"),
    "🚪 Выйти": ("🚪 Chiqish", "🚪 Exit"),
}

def _strip_emoji_prefix(s):
    if not isinstance(s, str): return s
    return re.sub(
        r'^[\U0001F000-\U0001FFFF\u2300-\u2BFF'
        r'\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u20E3\u2122\u2139'
        r'\u2190-\u21FF\u2702\u2705\u2708-\u270D\u270F\u2712\u2714\u2716'
        r'\u271D\u2721\u2728\u2733\u2734\u2744\u2747\u274C\u274E\u2753-\u2755'
        r'\u2757\u2763\u2764\u2795-\u2797\u27A1\u27B0\u27BF\u2934\u2935'
        r'\u2B00-\u2BFF\uFE0F\u200D]+[\uFE0F]?\s*',
        '', s)

_ALIAS = {}
for _ru, (_uz, _en) in BTN.items():
    _canonical = _strip_emoji_prefix(_ru) or _ru
    _ALIAS[_ru] = _canonical
    _ALIAS[_uz] = _canonical
    _ALIAS[_en] = _canonical

_ALIAS["🎯 𝐍𝐞𝐱𝐭.."] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["𝐍𝐞𝐱𝐭.."] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["Next.."] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["Next"] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["𝐍𝐞𝐱𝐭 𝐌𝐞𝐞𝐭"] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["Next Meet"] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["Поблизости"] = "🎯 𝐍𝐞𝐱𝐭.."
_ALIAS["📍 Поблизости"] = "🎯 𝐍𝐞𝐱𝐭.."

for _k, _v in {"❤️": "❤️", "❤": "❤️", "👎": "👎", "💌": "💌",
               "⛔": "⛔", "💤": "💤"}.items():
    _ALIAS[_k] = _v

def canon(text):
    if text is None: return None
    t = text.strip()
    hit = _ALIAS.get(t) or _ALIAS.get(text)
    if hit: return hit
    stripped = _strip_emoji_prefix(t)
    if not stripped: return t
    return _ALIAS.get(stripped, stripped)

def styled(text, kind="default"): return text

def tr_btn(ru_label, lang=None, kind="default"):
    lang = lang or cur_lang()
    if lang == "ru":
        base = ru_label
    else:
        pair = BTN.get(ru_label)
        base = ru_label if not pair else (pair[0] if lang == "uz" else pair[1])
    return styled(base, kind) if kind != "default" else base

def tr_kb(markup, lang=None):
    lang = lang or cur_lang()
    if not isinstance(markup, ReplyKeyboardMarkup): return markup
    new_rows = []
    for row in markup.keyboard:
        new_row = []
        for b in row:
            txt = b.text
            if lang == "ru":
                new_row.append(KeyboardButton(txt))
            else:
                pair = BTN.get(txt)
                new_row.append(KeyboardButton(pair[0] if lang == "uz" else pair[1]) if pair else KeyboardButton(txt))
        new_rows.append(new_row)
    return ReplyKeyboardMarkup(new_rows,
        resize_keyboard=markup.resize_keyboard,
        one_time_keyboard=markup.one_time_keyboard)

def get_lang(uid):
    try:
        u = get_user(uid)
        if u and u["lang"] in LANGS: return u["lang"]
    except (KeyError, TypeError): pass
    return "ru"

def set_lang(uid, lang):
    conn.execute("UPDATE users SET lang=? WHERE tg_id=?", (lang, uid))
    conn.commit()

_LEADING_EMOJI_RE = re.compile(
    r'^([\U0001F000-\U0001FFFF\u2190-\u21FF\u2300-\u23FF'
    r'\u2460-\u24FF\u25A0-\u27BF\u2B00-\u2BFF'
    r'\u3030\u303D\u3297\u3299\uFE0F\u200D\u20E3]+)')

def _leading_emoji(s):
    if not isinstance(s, str) or not s: return ""
    m = _LEADING_EMOJI_RE.match(s)
    return m.group(1) if m else ""
    T = {
    "main_menu": {"ru": "🏠 <b>Главное меню</b> 👇", "uz": "🏠 <b>Asosiy menyu</b> 👇", "en": "🏠 <b>Main menu</b> 👇"},
    "pick_on_kb": {"ru": "👇 Выберите вариант на клавиатуре", "uz": "👇 Klaviaturadan variantni tanlang", "en": "👇 Choose an option on the keyboard"},
    "not_understood": {"ru": "❓ Не понял команду. Воспользуйтесь меню 👇", "uz": "❓ Buyruqni tushunmadim. Menyudan foydalaning 👇", "en": "❓ I didn't get that. Use the menu 👇"},
    "search_cancelled": {"ru": "⛔ Поиск отменён. Главное меню 👇", "uz": "⛔ Qidiruv bekor qilindi. Asosiy menyu 👇", "en": "⛔ Search cancelled. Main menu 👇"},
    "banned": {"ru": "🚫 Вы заблокированы и не можете пользоваться ботом.", "uz": "🚫 Siz bloklangansiz va botdan foydalana olmaysiz.", "en": "🚫 You are blocked and cannot use the bot."},
    "done": {"ru": "✅ Готово!", "uz": "✅ Tayyor!", "en": "✅ Done!"},
    "enter_number": {"ru": "🔢 Введите число:", "uz": "🔢 Raqam kiriting:", "en": "🔢 Enter a number:"},
    "enter_days": {"ru": "📅 Введите число дней:", "uz": "📅 Kunlar sonini kiriting:", "en": "📅 Enter number of days:"},
    "choose_on_kb": {"ru": "👇 Выберите", "uz": "👇 Tanlang", "en": "👇 Choose"},
    "cancelled": {"ru": "↩️ Отменено.", "uz": "↩️ Bekor qilindi.", "en": "↩️ Cancelled."},

    # ==== NEXT.. ====
    "next_brand": {"ru": "𝐍𝐞𝐱𝐭..", "uz": "𝐍𝐞𝐱𝐭..", "en": "𝐍𝐞𝐱𝐭.."},
    "next_menu_title": {"ru": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━", "uz": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━", "en": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━"},
    "next_create_title": {
        "ru": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━\n✏️ Создай анкету, чтобы тебя видели другие.\n\n",
        "uz": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━\n✏️ Anketa yarating.\n\n",
        "en": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n━━━━━━━━━━━━━━━━━━━━\n✏️ Create a profile.\n\n"},
    "next_ask_name": {"ru": "📝 Введи <b>имя</b> (2-30):", "uz": "📝 <b>Ismingizni</b> kiriting:", "en": "📝 Enter <b>name</b>:"},
    "next_ask_age": {"ru": "🎂 Сколько тебе <b>лет</b>? (12-99)", "uz": "🎂 <b>Yoshingiz</b>? (12-99)", "en": "🎂 How old? (12-99)"},
    "next_ask_gender": {"ru": "⚧ Твой <b>пол</b>:", "uz": "⚧ <b>Jinsingiz</b>:", "en": "⚧ Your <b>gender</b>:"},
    "next_ask_looking": {"ru": "🎯 <b>Кого ищешь</b>?", "uz": "🎯 <b>Kimni qidirasiz</b>?", "en": "🎯 <b>Who are you looking for</b>?"},
    "next_ask_bio": {"ru": "📄 Расскажи <b>о себе</b> (5-200):", "uz": "📄 <b>O'zingiz haqida</b> (5-200):", "en": "📄 <b>About you</b> (5-200):"},
    "next_ask_photo": {"ru": "📷 Отправь <b>фото</b>:", "uz": "📷 <b>Foto</b> yuboring:", "en": "📷 Send <b>photo</b>:"},
    "next_name_invalid": {"ru": "❌ Имя 2-30 символов:", "uz": "❌ Ism 2-30 belgi:", "en": "❌ Name 2-30 chars:"},
    "next_age_invalid": {"ru": "❌ Возраст 12-99:", "uz": "❌ Yosh 12-99:", "en": "❌ Age 12-99:"},
    "next_bio_invalid": {"ru": "❌ 5-200 символов:", "uz": "❌ 5-200 belgi:", "en": "❌ 5-200 chars:"},
    "next_photo_required": {"ru": "📷 Отправь фото:", "uz": "📷 Foto yuboring:", "en": "📷 Send photo:"},
    "next_saved": {"ru": "✅ <b>Сохранено!</b>", "uz": "✅ <b>Saqlandi!</b>", "en": "✅ <b>Saved!</b>"},
    "next_profile_saved": {"ru": "✅ <b>Анкета создана!</b>", "uz": "✅ <b>Anketa yaratildi!</b>", "en": "✅ <b>Profile created!</b>"},
    "next_preview": {
        "ru": "👁 <b>Анкета</b>\n👤 <b>{name}</b>, {age}\n⚧ {gender}\n🎯 {looking}\n\n📄 {bio}",
        "uz": "👁 <b>Anketa</b>\n👤 <b>{name}</b>, {age}\n⚧ {gender}\n🎯 {looking}\n\n📄 {bio}",
        "en": "👁 <b>Profile</b>\n👤 <b>{name}</b>, {age}\n⚧ {gender}\n🎯 {looking}\n\n📄 {bio}"},
    "next_view_header": {"ru": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n👤 <b>{name}</b>, {age}", "uz": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n👤 <b>{name}</b>, {age}", "en": "🎯 <b>𝐍𝐞𝐱𝐭..</b>\n👤 <b>{name}</b>, {age}"},
    "next_no_profiles": {"ru": "😔 <b>Анкет пока нет</b>", "uz": "😔 <b>Hozircha anketalar yo'q</b>", "en": "😔 <b>No profiles yet</b>"},
    "next_search_stopped": {"ru": "💤 <b>Вышел из поиска</b>", "uz": "💤 <b>Qidiruvdan chiqdingiz</b>", "en": "💤 <b>Left the search</b>"},
    "next_match_title": {"ru": "💕 <b>Взаимно!</b>", "uz": "💕 <b>O'zaro!</b>", "en": "💕 <b>Mutual!</b>"},
    "next_match_contact": {"ru": "👤 <b>{name}</b>\n\n{contact}", "uz": "👤 <b>{name}</b>\n\n{contact}", "en": "👤 <b>{name}</b>\n\n{contact}"},
    "next_msg_prompt": {"ru": "💌 Отправь текст или голосовое:", "uz": "💌 Matn yoki ovozli yuboring:", "en": "💌 Send text or voice:"},
    "next_msg_sent": {"ru": "✅ Отправлено", "uz": "✅ Yuborildi", "en": "✅ Sent"},
    "next_msg_failed": {"ru": "❌ Не отправлено", "uz": "❌ Yuborilmadi", "en": "❌ Failed"},
    "next_reply_prompt": {"ru": "↩️ Отправь ответ:", "uz": "↩️ Javob yuboring:", "en": "↩️ Send reply:"},
    "next_banned_write": {"ru": "⛔ Нельзя писать", "uz": "⛔ Yoza olmaysiz", "en": "⛔ Can't write"},
    "next_report_confirm": {"ru": "🚩 <b>Жалоба отправлена</b>", "uz": "🚩 <b>Shikoyat yuborildi</b>", "en": "🚩 <b>Report sent</b>"},
    "next_banned_user": {"ru": "🚫 Вы забанены", "uz": "🚫 Siz banlangansiz", "en": "🚫 You are banned"},
    "next_only_text_voice": {"ru": "⚠️ Только текст или голосовое", "uz": "⚠️ Faqat matn yoki ovozli", "en": "⚠️ Text or voice only"},

    # ==== ЯЗЫК ====
    "lang_choose": {"ru": "🌐 Выберите язык:", "uz": "🌐 Tilni tanlang:", "en": "🌐 Choose language:"},
    "lang_set": {"ru": "🌐 Язык изменён на Русский ✅\n\nГлавное меню", "uz": "🌐 Til O'zbekchaga o'zgartirildi ✅\n\nAsosiy menyu", "en": "🌐 Language: English ✅\n\nMain menu"},

    # ==== ПРИВЕТСТВИЕ ====
    "welcome": {
        "ru": ("🔥 <b>Привет, {name}!</b> 👋\n━━━━━━━━━━━━━━━━━━━━\n"
               "Добро пожаловать в <b>𐌽ꤕ𐌗ተ</b> 🕶\n\n"
               "<blockquote>🔗 Анонимки по своей ссылке\n"
               "🎲 Чат-рулетка\n🎯 𝐍𝐞𝐱𝐭.. — мэтчи\n"
               "💎 VIP и бонусы</blockquote>\n\n"
               "👇 <b>Выбери пол</b>"),
        "uz": ("🔥 <b>Salom, {name}!</b> 👋\n"
               "Xush kelibsiz <b>𐌽ꤕ𐌗ተ</b> 🕶\n\n"
               "👇 <b>Jinsingizni tanlang</b>"),
        "en": ("🔥 <b>Hi, {name}!</b> 👋\n"
               "Welcome to <b>𐌽ꤕ𐌗ተ</b> 🕶\n\n"
               "👇 <b>Choose your gender</b>"),
    },
    "welcome_back": {
        "ru": "🎉 <b>С возвращением, {name}!</b>\n\n🏠 Главное меню",
        "uz": "🎉 <b>Qaytganingiz bilan, {name}!</b>\n\n🏠 Asosiy menyu",
        "en": "🎉 <b>Welcome back, {name}!</b>\n\n🏠 Main menu",
    },

    # ==== ПОМОЩЬ ====
    "help": {
        "ru": ("ℹ️ <b>ПОМОЩЬ 𐌽ꤕ𐌗ተ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               "<b>🔗 ССЫЛКА</b> — личная ссылка для анонимок\n"
               "<b>🎲 РУЛЕТКА</b> — случайный собеседник\n"
               "<b>🎯 𝐍𝐞𝐱𝐭..</b> — анкеты и мэтчи\n"
               "<b>👤 ПРОФИЛЬ</b> — данные\n"
               "<b>🛒 МАГАЗИН</b> — VIP, коины\n"
               "<b>⭐ PREMIUM</b> — приоритет, скидки, без рекламы\n"
               "<b>👥 ПРИГЛАСИТЬ</b> — до +100 коинов за друга\n"
               "<b>💎 КОИНЫ</b> — покупка за Stars\n"
               "<b>🌐 ЯЗЫК</b> — ru/uz/en"),
        "uz": ("ℹ️ <b>YORDAM 𐌽ꤕ𐌗ተ</b>\n"
               "🔗 Havolam · 🎲 Chat-ruletka · 🎯 𝐍𝐞𝐱𝐭..\n"
               "👤 Profil · 🛒 Do'kon · ⭐ Premium\n"
               "👥 Taklif · 💎 Coin · 🌐 Til"),
        "en": ("ℹ️ <b>HELP 𐌽ꤕ𐌗ተ</b>\n"
               "🔗 My link · 🎲 Roulette · 🎯 𝐍𝐞𝐱𝐭..\n"
               "👤 Profile · 🛒 Shop · ⭐ Premium\n"
               "👥 Invite · 💎 Coins · 🌐 Language"),
    },

    # ==== ПРОФИЛЬ ====
    "profile_full": {
        "ru": ("👤 <b>Профиль</b>\n"
               "<blockquote>🆔 <code>{id}</code>\n"
               "📝 {name}\n⚧ {gender}\n🎂 {age}\n"
               "🎲 Рулетка: {roulette_time}\n"
               "📤 Отправлено: {sent}\n📥 Получено: {received}\n"
               "👥 Друзей: {invited}\n🏆 Топ: {rank}\n"
               "👑 VIP: {vip}\n💎 Коины: {coins}\n"
               "⭐ Звёзд: {stars}\n📅 {reg_date}</blockquote>"),
        "uz": ("👤 <b>Profil</b>\n"
               "<blockquote>🆔 <code>{id}</code>\n📝 {name}\n⚧ {gender}\n🎂 {age}\n"
               "🎲 {roulette_time}\n📤 {sent}\n📥 {received}\n👥 {invited}\n"
               "🏆 {rank}\n👑 {vip}\n💎 {coins}\n⭐ {stars}\n📅 {reg_date}</blockquote>"),
        "en": ("👤 <b>Profile</b>\n"
               "<blockquote>🆔 <code>{id}</code>\n📝 {name}\n⚧ {gender}\n🎂 {age}\n"
               "🎲 {roulette_time}\n📤 {sent}\n📥 {received}\n👥 {invited}\n"
               "🏆 {rank}\n👑 {vip}\n💎 {coins}\n⭐ {stars}\n📅 {reg_date}</blockquote>"),
    },
    "vip_none": {"ru": "—", "uz": "—", "en": "—"},
    "vip_until": {"ru": "до {date}", "uz": "{date} gacha", "en": "until {date}"},
    "vip_forever": {"ru": "навсегда", "uz": "abadiy", "en": "forever"},
    "choose_action": {"ru": "👇 Выберите действие", "uz": "👇 Amalni tanlang", "en": "👇 Choose an action"},
    "choose_new_gender": {"ru": "⚧ Новый пол:", "uz": "⚧ Yangi jins:", "en": "⚧ New gender:"},
    "gender_saved": {"ru": "✅ Пол: <b>{g}</b>", "uz": "✅ Jins: <b>{g}</b>", "en": "✅ Gender: <b>{g}</b>"},
    "gender_set_short": {"ru": "✅ {g}", "uz": "✅ {g}", "en": "✅ {g}"},
    "gender_needed_for_search": {"ru": "👤 Выбери пол:", "uz": "👤 Jinsni tanlang:", "en": "👤 Choose gender:"},

    # ==== ВОЗРАСТ ====
    "age_register_ask": {"ru": "🎂 <b>Сколько вам лет?</b>\nНапишите число.", "uz": "🎂 <b>Yoshingiz?</b>\nRaqam yozing.", "en": "🎂 <b>How old are you?</b>\nType a number."},
    "age_enter_number": {"ru": "🔢 Введите возраст числом:", "uz": "🔢 Yoshni raqam bilan:", "en": "🔢 Enter age as number:"},
    "age_saved": {"ru": "✅ Возраст: <b>{age}</b>", "uz": "✅ Yosh: <b>{age}</b>", "en": "✅ Age: <b>{age}</b>"},

    # ==== ПОДАРОК КОИНОВ ====
    "giftcoins_ask_id": {"ru": "🎁 Введите ID или @username друга:", "uz": "🎁 Do'stning ID yoki @username ini kiriting:", "en": "🎁 Enter friend's ID or @username:"},
    "giftcoins_ask_amount": {"ru": "💰 Сколько коинов? Баланс: <b>{balance}</b>", "uz": "💰 Qancha coin? Balans: <b>{balance}</b>", "en": "💰 How many coins? Balance: <b>{balance}</b>"},
    "giftcoins_amount_number": {"ru": "🔢 Введите положительное число:", "uz": "🔢 Musbat raqam:", "en": "🔢 Positive number:"},
    "giftcoins_not_enough": {"ru": "💸 Недостаточно. Баланс: <b>{balance}</b>", "uz": "💸 Yetarli emas. Balans: <b>{balance}</b>", "en": "💸 Not enough. Balance: <b>{balance}</b>"},
    "giftcoins_sent": {"ru": "✅ Подарено <b>{amount}</b> → <code>{id}</code>", "uz": "✅ <b>{amount}</b> sovg'a → <code>{id}</code>", "en": "✅ Gifted <b>{amount}</b> → <code>{id}</code>"},
    "giftcoins_received": {"ru": "🎁 Вам подарили <b>{amount}</b>!", "uz": "🎁 Sizga <b>{amount}</b> sovg'a!", "en": "🎁 You received <b>{amount}</b>!"},
    "gift_user_not_found": {"ru": "❌ Не найден. Введите ID:", "uz": "❌ Topilmadi. ID kiriting:", "en": "❌ Not found. Enter ID:"},
    "gift_not_self": {"ru": "❌ Нельзя себе. Введите ID:", "uz": "❌ O'zingizga. ID kiriting:", "en": "❌ Can't self. Enter ID:"},
    }
    T.update({
    # ==== ССЫЛКА ====
    "link_section": {"ru": "🔗 <b>Раздел «Моя ссылка»</b>\n\n👉 Выберите действие", "uz": "🔗 <b>«Havolam»</b>\n\n👉 Amalni tanlang", "en": "🔗 <b>«My link»</b>\n\n👉 Choose action"},
    "link_menu": {"ru": "👇 Действие на клавиатуре", "uz": "👇 Klaviaturadan amalni tanlang", "en": "👇 Choose on keyboard"},
    "link_show": {"ru": "🤫 <b>Ваша ссылка</b>\n<blockquote>{link}</blockquote>\nПоделись с друзьями", "uz": "🤫 <b>Havolangiz</b>\n<blockquote>{link}</blockquote>", "en": "🤫 <b>Your link</b>\n<blockquote>{link}</blockquote>"},
    "link_done": {"ru": "✅ <b>Готово!</b>\n<blockquote>{link}</blockquote>", "uz": "✅ <b>Tayyor!</b>\n<blockquote>{link}</blockquote>", "en": "✅ <b>Done!</b>\n<blockquote>{link}</blockquote>"},
    "link_no_link": {"ru": "🔗 Придумайте код (до 10 символов):", "uz": "🔗 Kod kiriting (10 belgigacha):", "en": "🔗 Create code (up to 10):"},
    "link_change": {"ru": "✏️ Новый код (до 10). Старая ссылка живёт ещё 24 ч.", "uz": "✏️ Yangi kod (10). Eski 24 soat ishlaydi.", "en": "✏️ New code (10). Old works 24h."},
    "link_invalid": {"ru": "❌ До 10 символов (латиница, цифры, «-», «_»):", "uz": "❌ 10 belgigacha:", "en": "❌ Up to 10 chars:"},
    "link_taken": {"ru": "❌ Занят, попробуйте другой:", "uz": "❌ Band:", "en": "❌ Taken:"},
    "link_limit": {"ru": "⏳ Через {days} дн. Или купи Premium", "uz": "⏳ {days} kundan keyin. Yoki Premium", "en": "⏳ In {days} days. Or buy Premium"},
    "btn_share": {"ru": "🔗 Поделиться", "uz": "🔗 Ulashish", "en": "🔗 Share"},
    "share_text": {"ru": "Напиши мне анонимно", "uz": "Menga anonim yozing", "en": "Send me anonymously"},

    # ==== АНОНИМКА ====
    "anon_what_send": {"ru": "❓ Что отправить?", "uz": "❓ Nima yuborish?", "en": "❓ What to send?"},
    "anon_write_prompt": {"ru": "✍️ Напишите {label} (текст или голос):", "uz": "✍️ {label}ni yozing:", "en": "✍️ Write {label}:"},
    "anon_label_question": {"ru": "вопрос", "uz": "savol", "en": "question"},
    "anon_label_valentine": {"ru": "валентинку", "uz": "valentinka", "en": "valentine"},
    "anon_sent": {"ru": "✅ Отправлено", "uz": "✅ Yuborildi", "en": "✅ Sent"},
    "anon_failed": {"ru": "❌ Не доставлено", "uz": "❌ Yetkazilmadi", "en": "❌ Not delivered"},
    "anon_reply_prompt": {"ru": "💬 Напиши ответ:", "uz": "💬 Javob yozing:", "en": "💬 Write reply:"},
    "anon_reply_sent": {"ru": "✅ Отправлено", "uz": "✅ Yuborildi", "en": "✅ Sent"},
    "anon_reply_failed": {"ru": "❌ Не доставлено", "uz": "❌ Yetkazilmadi", "en": "❌ Not delivered"},
    "anon_not_found": {"ru": "❌ Не найдено", "uz": "❌ Topilmadi", "en": "❌ Not found"},
    "anon_limit": {"ru": "⚠️ Лимит {n}/сутки. Premium снимает", "uz": "⚠️ {n}/kun. Premium olib tashlaydi", "en": "⚠️ Limit {n}/day. Premium removes"},
    "anon_vip_media": {"ru": "📷 Только Premium. Отправь текст или голос.", "uz": "📷 Faqat Premium.", "en": "📷 Premium only."},
    "anon_formats": {"ru": "📝 Текст, голос{vip}.", "uz": "📝 Matn, ovozli{vip}.", "en": "📝 Text, voice{vip}."},
    "anon_formats_vip": {"ru": ", фото, стикеры, гиф, видео", "uz": ", foto, stiker, gif, video", "en": ", photos, stickers, gifs, videos"},
    "anon_invalid_link": {"ru": "❌ Ссылка недействительна", "uz": "❌ Havola yaroqsiz", "en": "❌ Link invalid"},
    "anon_own_link": {"ru": "❌ Это ваша ссылка", "uz": "❌ Bu sizning havolangiz", "en": "❌ Your own link"},
    "anon_banned": {"ru": "⛔ Временно нельзя писать", "uz": "⛔ Vaqtincha yoza olmaysiz", "en": "⛔ Temporarily can't write"},
    "anon_deleted_notice": {"ru": "🗑 Собеседник удалил сообщение", "uz": "🗑 Suhbatdosh o'chirdi", "en": "🗑 Sender deleted message"},
    "anon_hdr_question": {"ru": "📩 <b>Анонимный вопрос</b>", "uz": "📩 <b>Anonim savol</b>", "en": "📩 <b>Anonymous question</b>"},
    "anon_hdr_valentine": {"ru": "💌 <b>Анонимная валентинка</b>", "uz": "💌 <b>Anonim valentinka</b>", "en": "💌 <b>Anonymous valentine</b>"},
    "anon_hdr_reply": {"ru": "💬 <b>Вам ответили</b>", "uz": "💬 <b>Javob berishdi</b>", "en": "💬 <b>Reply received</b>"},
    "anon_hdr_new": {"ru": "📩 <b>Новое сообщение</b>", "uz": "📩 <b>Yangi xabar</b>", "en": "📩 <b>New message</b>"},
    "anon_quote_reply": {"ru": "<i>в ответ на:</i>", "uz": "<i>javoban:</i>", "en": "<i>in reply to:</i>"},
    "preview_voice": {"ru": "голосовое", "uz": "ovozli", "en": "voice"},
    "preview_media": {"ru": "медиа", "uz": "media", "en": "media"},
    "btn_reply": {"ru": "💬 Ответить", "uz": "💬 Javob", "en": "💬 Reply"},
    "btn_report": {"ru": "🚩 Жалоба", "uz": "🚩 Shikoyat", "en": "🚩 Report"},
    "btn_reveal": {"ru": "👁 Узнать · 1", "uz": "👁 · 1", "en": "👁 Reveal · 1"},
    "btn_delete": {"ru": "🗑 Удалить", "uz": "🗑 O'chirish", "en": "🗑 Delete"},
    "del_both": {"ru": "🗑 Удалено у обоих", "uz": "🗑 Ikkalasida o'chirildi", "en": "🗑 Deleted for both"},
    "del_only_me": {"ru": "🗑 Удалено только у тебя", "uz": "🗑 Faqat sizda", "en": "🗑 Only for you"},
    "del_stale": {"ru": "⚠️ Устарело — только у тебя", "uz": "⚠️ Eskirgan — faqat sizda", "en": "⚠️ Stale — only for you"},

    # ==== ЖАЛОБА ====
    "report_choose": {"ru": "🚩 Причина:", "uz": "🚩 Sabab:", "en": "🚩 Reason:"},
    "report_sent": {"ru": "✅ Жалоба отправлена", "uz": "✅ Shikoyat yuborildi", "en": "✅ Report sent"},
    "report_cancelled": {"ru": "↩️ Отменено", "uz": "↩️ Bekor", "en": "↩️ Cancelled"},
    "report_confirmed_user": {"ru": "✅ Подтверждена. Пользователь не сможет писать {days} дн.", "uz": "✅ Tasdiqlandi. {days} kun yoza olmaydi.", "en": "✅ Confirmed. User can't write for {days} days."},
    "report_confirmed_forever": {"ru": "✅ Подтверждена. Пользователь <b>никогда</b> не напишет.", "uz": "✅ Tasdiqlandi. <b>Hech qachon</b>.", "en": "✅ Confirmed. User can <b>never</b> write."},
    "report_rejected_user": {"ru": "❌ Жалоба отклонена", "uz": "❌ Rad etildi", "en": "❌ Rejected"},
    "report_already_handled": {"ru": "ℹ️ Уже обработана", "uz": "ℹ️ Ko'rilgan", "en": "ℹ️ Already handled"},
    "report_confirmed_staff": {"ru": "✅ Подтверждена, бан", "uz": "✅ Tasdiqlandi, ban", "en": "✅ Confirmed, banned"},
    "report_rejected_staff": {"ru": "❌ Отклонена", "uz": "❌ Rad etildi", "en": "❌ Rejected"},
    "report_banned_msg": {"ru": "✅ <b>{name}</b> забанен #{rid}", "uz": "✅ <b>{name}</b> ban #{rid}", "en": "✅ <b>{name}</b> banned #{rid}"},
    "report_unbanned_msg": {"ru": "✅ <b>{name}</b> разбанен #{rid}", "uz": "✅ <b>{name}</b> unban #{rid}", "en": "✅ <b>{name}</b> unbanned #{rid}"},
    "report_rejected_msg": {"ru": "❌ Жалоба #{rid} отклонена", "uz": "❌ Shikoyat #{rid}", "en": "❌ Report #{rid} rejected"},
    "you_were_banned": {"ru": "⚠️ На вас жалоба — {days} дн. нельзя писать этому юзеру", "uz": "⚠️ Sizga shikoyat — {days} kun", "en": "⚠️ You were reported — {days} days"},
    "you_were_banned_forever": {"ru": "🚫 Вы <b>навсегда</b> заблокированы", "uz": "🚫 <b>Abadiy</b> bloklandingiz", "en": "🚫 <b>Permanently</b> blocked"},
    "you_were_unbanned": {"ru": "✅ Вас разбанили", "uz": "✅ Unban", "en": "✅ You were unbanned"},
    "no_contacts": {"ru": "⛔ Ссылки, @, номера, ID и соцсети запрещены", "uz": "⛔ Havola, @, raqam, ID taqiqlangan", "en": "⛔ Links, @, numbers, IDs banned"},
    "cant_ban_staff": {"ru": "🛡 Нельзя забанить админа/модера. Жалоба отклонена", "uz": "🛡 Admin/moderni bloklab bo'lmaydi", "en": "🛡 Can't ban admin/mod"},
    "staff_only": {"ru": "🛡 Только для модерации", "uz": "🛡 Faqat moderatorlar", "en": "🛡 Moderation only"},
    "admin_only": {"ru": "🔒 Только для админа", "uz": "🔒 Faqat admin", "en": "🔒 Admin only"},
    "super_admin_only": {"ru": "🔒 Только для главного админа", "uz": "🔒 Bosh admin", "en": "🔒 Super admin only"},

    # ==== ПОДПИСКА ====
    "sub_to_delete_short": {"ru": "🔒 <b>Подпишись чтобы удалить</b>\nНажми кнопку → подпишись → «Проверить»", "uz": "🔒 <b>Obuna bo'ling</b>", "en": "🔒 <b>Subscribe</b>"},
    "btn_check_sub": {"ru": "🔍 Проверить", "uz": "🔍 Tekshirish", "en": "🔍 Check"},
    "subgate_start": {"ru": "🔒 <b>Подпишись чтобы пользоваться</b>\n━━━━━━━━━━━━━━━━━━━━\nНажми кнопку → подпишись → «Проверить»", "uz": "🔒 <b>Obuna bo'ling</b>", "en": "🔒 <b>Subscribe to use</b>"},
    "sub_not_found": {"ru": "❗ Подписка не найдена", "uz": "❗ Obuna topilmadi", "en": "❗ Subscription not found"},

    # ==== РУЛЕТКА ====
    "roulette_who": {"ru": "🎲 Кого искать?", "uz": "🎲 Kimni topmoqchisiz?", "en": "🎲 Who to find?"},
    "roulette_searching": {"ru": "⏳ Поиск собеседника…", "uz": "⏳ Suhbatdosh qidirilmoqda…", "en": "⏳ Searching…"},
    "roulette_finding_partner": {"ru": "⏳ Поиск…", "uz": "⏳ Qidiruv…", "en": "⏳ Searching…"},
    "roulette_already_chat": {"ru": "⚠️ Вы уже в чате", "uz": "⚠️ Siz chatsiz", "en": "⚠️ Already in chat"},
    "roulette_stop": {"ru": "⏹️ Поиск отменён", "uz": "⏹️ Bekor qilindi", "en": "⏹️ Search cancelled"},
    "roulette_left": {"ru": "🚪 Собеседник покинул чат", "uz": "🚪 Suhbatdosh chiqdi", "en": "🚪 Partner left"},
    "session_not_found": {"ru": "❓ Сессия не найдена", "uz": "❓ Sessiya yo'q", "en": "❓ Session not found"},
    "search_still": {"ru": "⏳ Всё ещё ищем…\nУже <b>{min}</b> мин.", "uz": "⏳ Hali qidirilmoqda…\n<b>{min}</b> daqiqa.", "en": "⏳ Still looking…\n<b>{min}</b> min."},
    "search_timeout": {"ru": "⏹️ <b>Поиск остановлен</b> — за {min} мин не нашли", "uz": "⏹️ <b>To'xtatildi</b> — {min} daqiqada topilmadi", "en": "⏹️ <b>Stopped</b> — no match in {min} min"},
    "roulette_found": {
        "ru": "🎲🟢 <b>СОБЕСЕДНИК НАЙДЕН</b> 🟢🎲\n<i>Пиши первым!</i>\n<blockquote>🤫 Анонимно · фото, голосовые, стикеры\n«Далее» — другой · «Стоп» — выйти</blockquote>",
        "uz": "🎲🟢 <b>SUHBATDOSH TOPILDI</b> 🟢🎲\n<i>Birinchi yozing!</i>",
        "en": "🎲🟢 <b>PARTNER FOUND</b> 🟢🎲\n<i>Write first!</i>",
    },

    # ==== МАГАЗИН ====
    "shop_title": {"ru": "🛒 <b>Магазин</b>\nВыберите товар", "uz": "🛒 <b>Do'kon</b>", "en": "🛒 <b>Shop</b>"},
    "shop_empty": {"ru": "📭 Магазин пуст", "uz": "📭 Do'kon bo'sh", "en": "📭 Shop is empty"},
    "shop_pick_item": {"ru": "🛒 Выберите товар", "uz": "🛒 Tanlang", "en": "🛒 Choose item"},
    "shop_vip_note": {"ru": "👑 Цены с Premium-скидкой −20%", "uz": "👑 Premium chegirma −20%", "en": "👑 Premium discount −20%"},
    "item_unavailable": {"ru": "❌ Товар недоступен", "uz": "❌ Mavjud emas", "en": "❌ Item unavailable"},
    "not_enough_coins": {"ru": "💸 Недостаточно коинов", "uz": "💸 Coinlar yetarli emas", "en": "💸 Not enough coins"},
    "shop_buy_confirm": {"ru": "🛒 Купить «<b>{title}</b>» за {price}?", "uz": "🛒 «<b>{title}</b>» {price} ga?", "en": "🛒 Buy «<b>{title}</b>» for {price}?"},
    "price_plain": {"ru": "<b>{price}</b>", "uz": "<b>{price}</b>", "en": "<b>{price}</b>"},
    "price_vip": {"ru": "<b>{price}</b> (обычно {orig})", "uz": "<b>{price}</b> (odatda {orig})", "en": "<b>{price}</b> (usually {orig})"},
    "purchase_coins": {"ru": "✅ Начислено <b>{amt}</b>", "uz": "✅ <b>{amt}</b> qo'shildi", "en": "✅ <b>{amt}</b> added"},
    "purchase_vip": {"ru": "✅ Premium на <b>{days}</b> дн.", "uz": "✅ Premium <b>{days}</b> kun", "en": "✅ Premium for <b>{days}</b> days"},
    "purchase_manual": {"ru": "✅ Покупка! Админ свяжется", "uz": "✅ Xarid! Admin bog'lanadi", "en": "✅ Purchase! Admin will contact"},

    # ==== STARS ====
    "stars_unavailable": {"ru": "⭐ Покупка коинов недоступна", "uz": "⭐ Coin sotib olish yo'q", "en": "⭐ Buying coins unavailable"},
    "stars_pick_pkg": {"ru": "💎 Выбери пакет", "uz": "💎 Paketni tanlang", "en": "💎 Choose package"},
    "pkg_unavailable": {"ru": "❌ Пакет недоступен", "uz": "❌ Paket yo'q", "en": "❌ Package unavailable"},
    "stars_buy_confirm": {"ru": "⭐ «<b>{title}</b>» ({coins}💰) за <b>{stars} ⭐</b>?", "uz": "⭐ «<b>{title}</b>» <b>{stars} ⭐</b>?", "en": "⭐ Buy «<b>{title}</b>» for <b>{stars} ⭐</b>?"},
    "stars_invoice_sent": {"ru": "💳 Счёт выставлен", "uz": "💳 Hisob-faktura", "en": "💳 Invoice sent"},
    "stars_pkg_desc": {"ru": "{coins} коинов", "uz": "{coins} coin", "en": "{coins} coins"},
    "stars_paid": {"ru": "🔥 Начислено <b>{coins}</b>", "uz": "🔥 <b>{coins}</b> qo'shildi", "en": "🔥 <b>{coins}</b> added"},
    "stars_title": {"ru": "⭐ <b>Коины за Stars</b>\nВыбери пакет", "uz": "⭐ <b>Stars uchun coin</b>", "en": "⭐ <b>Buy coins with Stars</b>"},

    # ==== РАСКРЫТИЕ ====
    "msg_not_found": {"ru": "❌ Не найдено", "uz": "❌ Topilmadi", "en": "❌ Not found"},
    "reveal_profile_link": {"ru": "профиль", "uz": "profil", "en": "profile"},
    "btn_reveal_yes": {"ru": "✅ Раскрыть · 1", "uz": "✅ · 1", "en": "✅ Reveal · 1"},
    "btn_cancel_accent": {"ru": "❌ Отмена", "uz": "❌ Bekor", "en": "❌ Cancel"},
    "reveal_title": {"ru": "👁 Раскрыть отправителя", "uz": "👁 Yuboruvchini aniqlash", "en": "👁 Reveal sender"},
    "reveal_desc": {"ru": "Узнай кто отправил", "uz": "Kim yuborganini biling", "en": "Find out who sent"},
    "reveal_result": {"ru": "👁 <b>Раскрыт!</b>\n📝 <b>{name}</b>\n👤 {uname}\n🆔 <code>{tid}</code>", "uz": "👁 <b>Aniqlandi!</b>\n📝 <b>{name}</b>\n👤 {uname}\n🆔 <code>{tid}</code>", "en": "👁 <b>Revealed!</b>\n📝 <b>{name}</b>\n👤 {uname}\n🆔 <code>{tid}</code>"},
    "reveal_confirm": {"ru": "👁 Раскрыть за <b>1 ⭐</b>?", "uz": "👁 <b>1 ⭐</b> ga?", "en": "👁 Reveal for <b>1 ⭐</b>?"},
    "reveal_paying": {"ru": "💳 Оплатите инвойс", "uz": "💳 To'lang", "en": "💳 Pay the invoice"},
    "reveal_only_recipient": {"ru": "🔒 Только получатель", "uz": "🔒 Faqat qabul qiluvchi", "en": "🔒 Only recipient"},

    # ==== РЕФЕРАЛЫ ====
    "referral_screen": {
        "ru": ("👥 <b>Приглашай друзей!</b>\n"
               "🎁 За друга: <b>{reward}</b>{bonus}\n"
               "📊 Приглашено: <b>{total}</b>\n💰 Заработано: <b>{earned}</b>\n\n"
               "🔗 <blockquote>{link}</blockquote>\n"
               "⚠️ Если друг заблокирует бота — коины спишутся"),
        "uz": ("👥 <b>Do'stlarni taklif qiling!</b>\n"
               "🎁 Har do'st: <b>{reward}</b>{bonus}\n"
               "📊 <b>{total}</b>\n💰 <b>{earned}</b>\n\n"
               "🔗 <blockquote>{link}</blockquote>"),
        "en": ("👥 <b>Invite friends!</b>\n"
               "🎁 Per friend: <b>{reward}</b>{bonus}\n"
               "📊 Invited: <b>{total}</b>\n💰 Earned: <b>{earned}</b>\n\n"
               "🔗 <blockquote>{link}</blockquote>"),
    },
    "referral_bonus_vip": {"ru": " (Premium)", "uz": " (Premium)", "en": " (Premium)"},
    "referral_bonus_normal": {"ru": " (у Premium — 100)", "uz": " (Premium — 100)", "en": " (Premium gets 100)"},
    "ref_rewards_title": {
        "ru": "🏆 <b>Награды</b>\n👑 Premium — за {vip_n} друзей ({vip_d} дн.)\n🛡 Модер — за {mod_n} ({mod_d} дн.)",
        "uz": "🏆 <b>Mukofotlar</b>\n👑 {vip_n} do'st ({vip_d} kun)\n🛡 {mod_n} ({mod_d} kun)",
        "en": "🏆 <b>Rewards</b>\n👑 {vip_n} friends ({vip_d}d)\n🛡 {mod_n} ({mod_d}d)",
    },
    "ref_claim_coins_btn": {"ru": "🎁 {n} за друга · Premium {v}", "uz": "🎁 {n} · Premium {v}", "en": "🎁 {n} · Premium {v}"},
    "btn_share_ref": {"ru": "🔗 Поделиться ссылкой", "uz": "🔗 Ulashish", "en": "🔗 Share link"},
    "ref_share_text": {"ru": "Залетай в анонимный бот! 🎁", "uz": "Anonim botga kir! 🎁", "en": "Join the anonymous bot! 🎁"},
    "ref_claim_vip_btn": {"ru": "👑 Premium бесплатно", "uz": "👑 Bepul Premium", "en": "👑 Free Premium"},
    "ref_claim_moder_btn": {"ru": "🛡 Модерка на неделю", "uz": "🛡 Bir haftalik moder", "en": "🛡 Mod for a week"},
    "ref_need_more": {"ru": "❌ Нужно ещё: {n}\nУ тебя: {have}/{need}\n⚠️ Считаются только создавшие свою ссылку", "uz": "❌ Yana: {n}\nSizda: {have}/{need}", "en": "❌ Need more: {n}\nYou have: {have}/{need}"},
    "ref_vip_granted": {"ru": "🎉 <b>Premium на {days} дней!</b>", "uz": "🎉 <b>Premium {days} kun!</b>", "en": "🎉 <b>Premium for {days} days!</b>"},
    "ref_moder_granted": {"ru": "🎉 <b>Модерка на {days} дней</b> за {need} друзей!", "uz": "🎉 <b>Moder {days} kun</b> — {need} do'st!", "en": "🎉 <b>Moder for {days} days</b> — {need} friends!"},
    "ref_info_alert": {"ru": "ℹ️ За друга: {n} (Premium — {v})", "uz": "ℹ️ Do'st: {n} (Premium — {v})", "en": "ℹ️ Per friend: {n} (Premium — {v})"},
    "link_reward": {"ru": "🎁 Бонус за активность: +{coins}\nВсего: {n}", "uz": "🎁 Bonus: +{coins}\nJami: {n}", "en": "🎁 Activity bonus: +{coins}\nTotal: {n}"},
    "ref_menu_hint": {"ru": "👥 Меню «Пригласить»", "uz": "👥 «Taklif» menyusi", "en": "👥 Invite menu"},
    "ref_friend_joined": {"ru": "🎉 По вашей ссылке друг! +{reward}", "uz": "🎉 Do'st keldi! +{reward}", "en": "🎉 Friend joined! +{reward}"},
    "ref_welcome_bonus": {"ru": "🎁 <b>Добро пожаловать!</b> Подарок <b>+{n}</b>", "uz": "🎁 <b>Xush kelibsiz!</b> <b>+{n}</b>", "en": "🎁 <b>Welcome!</b> Gift <b>+{n}</b>"},
    "ref_progress_title": {"ru": "📊 <b>Прогресс:</b>", "uz": "📊 <b>Progress:</b>", "en": "📊 <b>Progress:</b>"},
    "ref_friends_word": {"ru": "друзей", "uz": "do'st", "en": "friends"},
    "top_empty": {"ru": "🏆 Пока никого. Будь первым!", "uz": "🏆 Hozircha yo'q.", "en": "🏆 Empty. Be first!"},
    "top_title": {"ru": "🏆 <b>Топ пригласивших</b>", "uz": "🏆 <b>Top</b>", "en": "🏆 <b>Top inviters</b>"},
    "ref_coins_refunded": {"ru": "⚠️ Друг заблокировал — <b>{n}</b> списаны", "uz": "⚠️ Blokladi — <b>{n}</b> qaytarildi", "en": "⚠️ Friend blocked — <b>{n}</b> deducted"},

    # ==== МОДЕРАЦИЯ ====
    "vip_daily_bonus": {"ru": "🎁 Daily бонус: +{n}", "uz": "🎁 Kunlik bonus: +{n}", "en": "🎁 Daily bonus: +{n}"},
    "moder_form_gender": {"ru": "🛡 <b>Анкета модера.</b>\n⚧ Пол?", "uz": "🛡 <b>Moder anketasi.</b>\n⚧ Jins?", "en": "🛡 <b>Moder app.</b>\n⚧ Gender?"},
    "moder_form_age": {"ru": "🎂 Возраст?", "uz": "🎂 Yosh?", "en": "🎂 Age?"},
    "moder_form_tg": {"ru": "⏱ Сколько в TG в день?", "uz": "⏱ Kuniga TG da?", "en": "⏱ TG time/day?"},
    "moder_form_avail": {"ru": "🕐 Когда онлайн?", "uz": "🕐 Qachon online?", "en": "🕐 When online?"},
    "moder_form_cancelled": {"ru": "↩️ Отменено. Коины ({price}) возвращены", "uz": "↩️ Bekor. Coinlar ({price})", "en": "↩️ Cancelled. Coins ({price}) refunded"},
    "moder_form_sent": {"ru": "📨 Отправлено администратору", "uz": "📨 Adminга yuborildi", "en": "📨 Sent to admin"},
    "moder_granted_user": {"ru": "🛡 Вам выдан модер!", "uz": "🛡 Moder berildi!", "en": "🛡 Moderator granted!"},
    "moder_granted_shop": {"ru": "🛡 <b>Вы Модер!</b> 👑\nБонус: @ToxIc_0707", "uz": "🛡 <b>Moder!</b> 👑", "en": "🛡 <b>You're a Moder!</b> 👑"},
    "moder_rejected_user": {"ru": "❌ Заявка отклонена. Коины ({coins}) возвращены", "uz": "❌ Rad. Coinlar ({coins})", "en": "❌ Rejected. Coins ({coins}) refunded"},
    "moder_taken_user": {"ru": "🛡 Роль снята", "uz": "🛡 Olib tashlandi", "en": "🛡 Role removed"},
    "moder_app_already": {"ru": "ℹ️ Уже обработана", "uz": "ℹ️ Ko'rilgan", "en": "ℹ️ Already handled"},
    "moder_granted_staff": {"ru": "✅ Выдано", "uz": "✅ Berildi", "en": "✅ Granted"},
    "moder_rejected_staff": {"ru": "❌ Отказано, возврат", "uz": "❌ Rad, qaytarish", "en": "❌ Rejected, refunded"},
    "mod_message": {"ru": "📨 <b>От модера {name}:</b>\n{text}", "uz": "📨 <b>{name}:</b>\n{text}", "en": "📨 <b>From mod {name}:</b>\n{text}"},
    "admin_vip_menu": {"ru": "👑 <b>Premium по ID</b>", "uz": "👑 <b>ID bo'yicha Premium</b>", "en": "👑 <b>Premium by ID</b>"},
    "vip_ask_id": {"ru": "🆔 Введите tg_id или @username:", "uz": "🆔 tg_id yoki @username:", "en": "🆔 Enter tg_id or @username:"},
    "vip_ask_days": {"ru": "📅 На сколько дней?", "uz": "📅 Necha kun?", "en": "📅 How many days?"},
    "vip_id_number": {"ru": "🔢 ID числом:", "uz": "🔢 Raqam:", "en": "🔢 Number:"},
    "vip_days_number": {"ru": "🔢 Положительное число дней:", "uz": "🔢 Musbat kun:", "en": "🔢 Positive days:"},
    "vip_user_not_found": {"ru": "❌ Не найден. Введите ID или @:", "uz": "❌ Topilmadi. ID yoki @:", "en": "❌ Not found. Enter ID or @:"},
    "vip_granted_admin": {"ru": "✅ Premium <code>{id}</code> на {days} дн.", "uz": "✅ <code>{id}</code> {days} kun.", "en": "✅ Premium <code>{id}</code> for {days}d."},
    "vip_taken_admin": {"ru": "✅ Premium снят <code>{id}</code>", "uz": "✅ <code>{id}</code> olib tashlandi", "en": "✅ Premium removed <code>{id}</code>"},
    "vip_granted_user": {"ru": "👑 <b>Вам Premium на {days} дней!</b>", "uz": "👑 <b>{days} kun Premium!</b>", "en": "👑 <b>You got Premium for {days} days!</b>"},
    "vip_taken_user": {"ru": "👑 Premium снят", "uz": "👑 Premium olib tashlandi", "en": "👑 Premium removed"},
    "vip_bulk_menu_title": {"ru": "🎯 <b>Массовый Premium — {target}</b>", "uz": "🎯 <b>{target}</b>", "en": "🎯 <b>Bulk Premium — {target}</b>"},
    "vip_bulk_revoke_done": {"ru": "✅ Снят у <b>{target}</b> ({count})", "uz": "✅ <b>{target}</b> ({count})", "en": "✅ Revoked <b>{target}</b> ({count})"},
    "vip_bulk_ask_days": {"ru": "📅 Дней для <b>{target}</b>?", "uz": "📅 <b>{target}</b> kun?", "en": "📅 Days for <b>{target}</b>?"},
    "vip_bulk_done": {"ru": "✅ <b>{target}</b> на <b>{days}</b> дн. ({count})", "uz": "✅ <b>{target}</b> <b>{days}</b> ({count})", "en": "✅ <b>{target}</b> for <b>{days}</b>d ({count})"},
    "inactive_nudge": {"ru": "💤 Давно тебя не было!\nНажми /start", "uz": "💤 Sizni ko'rmadik!\n/start bosing", "en": "💤 Long time no see!\nTap /start"},
    "moder_help": {
        "ru": "ℹ️ <b>Помощь модера</b>\n🔨 Бан / Разбан\n📊 Статистика\n📤 Экспорт\n📢 Каналы\n\n<b>Скрытые:</b> /tg /next /anon /sex",
        "uz": "ℹ️ <b>Moder yordam</b>\n🔨 Ban\n📊 Statistika\n📤 Eksport\n📢 Kanallar\n\n<b>Maxfiy:</b> /tg /next /anon /sex",
        "en": "ℹ️ <b>Moderator help</b>\n🔨 Ban / Unban\n📊 Stats\n📤 Export\n📢 Channels\n\n<b>Hidden:</b> /tg /next /anon /sex",
    },

    # ==== /sex ====
    "sex_only_moder": {"ru": "🛡 Только для модеров", "uz": "🛡 Faqat moderatorlar", "en": "🛡 Moderators only"},
    "sex_room_exists": {"ru": "💬 Комната: <b>{title}</b>", "uz": "💬 Xona: <b>{title}</b>", "en": "💬 Room: <b>{title}</b>"},
    "sex_create_prompt": {"ru": "💬 <b>Создание комнаты</b>\nНазвание:", "uz": "💬 <b>Xona yaratish</b>\nNomi:", "en": "💬 <b>Create room</b>\nName:"},
    "sex_room_created": {"ru": "✅ <b>{title}</b> создана!\nВсе девушки добавлены", "uz": "✅ <b>{title}</b>!", "en": "✅ <b>{title}</b> created!"},
    "sex_room_joined": {"ru": "💬 Ты в <b>{title}</b>", "uz": "💬 <b>{title}</b> da", "en": "💬 In <b>{title}</b>"},
    "sex_room_deleted": {"ru": "🗑 Удалена", "uz": "🗑 O'chirildi", "en": "🗑 Deleted"},
    "sex_room_renamed": {"ru": "✏️ Переименована: <b>{title}</b>", "uz": "✏️ <b>{title}</b>", "en": "✏️ Renamed: <b>{title}</b>"},
    "sex_exit_requested": {"ru": "⏳ Запрос отправлен", "uz": "⏳ So'rov yuborildi", "en": "⏳ Request sent"},
    "sex_exit_approved": {"ru": "✅ Вышли", "uz": "✅ Chiqdingiz", "en": "✅ Left"},
    "sex_renamed_prompt": {"ru": "✏️ Новое название:", "uz": "✏️ Yangi nom:", "en": "✏️ New name:"},
    "sex_only_owner_can_delete": {"ru": "🔒 Только создатель", "uz": "🔒 Faqat yaratuvchi", "en": "🔒 Owner only"},
    "sex_only_owner_can_rename": {"ru": "🔒 Только создатель", "uz": "🔒 Faqat yaratuvchi", "en": "🔒 Owner only"},
    "sex_no_room": {"ru": "💬 Нет комнаты. /sex чтобы создать", "uz": "💬 Xona yo'q. /sex", "en": "💬 No room. /sex to create"},
    "sex_member_joined_you": {"ru": "👤 <b>{name}</b> присоединился (#{num})", "uz": "👤 <b>{name}</b> (#{num})", "en": "👤 <b>{name}</b> joined (#{num})"},
    "sex_msg_from": {"ru": "<b>💬 {num}:</b>", "uz": "<b>💬 {num}:</b>", "en": "<b>💬 {num}:</b>"},

    # ==== /anon ====
    "anon_watch_prompt": {"ru": "👁 <b>Наблюдение</b>\nВведите ID пользователя:", "uz": "👁 <b>Kuzatish</b>\nFoydalanuvchi ID:", "en": "👁 <b>Watch</b>\nEnter user ID:"},
    "anon_watch_empty": {"ru": "❌ Нет переписки", "uz": "❌ Yozishma yo'q", "en": "❌ No chats"},
    "anon_watch_file_caption": {"ru": "👁 <b>Наблюдение за {uid}</b>\nСвежие → в ЛС", "uz": "👁 <b>{uid} kuzatilmoqda</b>", "en": "👁 <b>Watching {uid}</b>"},
    "anon_watch_leave": {"ru": "🚪 Вышли", "uz": "🚪 Chiqdingiz", "en": "🚪 Left"},
    "anon_watch_new_msg": {"ru": "👁 <b>Новая анонимка для {uid}</b>\n👤 <b>{sname}</b> (<code>{sfid}</code>)\n🕐 {when}", "uz": "👁 <b>{uid} uchun</b>\n👤 <b>{sname}</b>", "en": "👁 <b>New for {uid}</b>\n👤 <b>{sname}</b>\n🕐 {when}"},

    # ==== PREMIUM ====
    "premium_title": {
        "ru": "⭐ <b>Premium</b>\n━━━━━━━━━━━━━━━━━━━━\n• 🚀 Приоритет в 𝐍𝐞𝐱𝐭..\n• 🚫 Без рекламы\n• 👁 3 «Узнать»/мес\n• 💎 −20% в магазине\n• 🎲 Приоритет в рулетке\n• 🔗 Смена ссылки без ограничений\n\n👇 Выбери:",
        "uz": "⭐ <b>Premium</b>\n━━━━━━━━━━━━━━━━━━━━\n• 🚀 𝐍𝐞𝐱𝐭.. ustuvorlik\n• 🚫 Reklamasiz\n• 👁 3 «Aniqlash»/oy\n• 💎 Do'konda −20%\n• 🎲 Ruletkada ustuvorlik\n• 🔗 Havola cheklovsiz\n\n👇 Tanlang:",
        "en": "⭐ <b>Premium</b>\n━━━━━━━━━━━━━━━━━━━━\n• 🚀 Priority in 𝐍𝐞𝐱𝐭..\n• 🚫 No ads\n• 👁 3 «Reveal»/month\n• 💎 −20% shop\n• 🎲 Priority roulette\n• 🔗 Unlimited link change\n\n👇 Choose:",
    },
    "premium_active": {"ru": "✅ <b>Premium активен</b>\nдо {date}\n\n👇 Купить ещё:", "uz": "✅ <b>Premium faol</b>\n{date} gacha", "en": "✅ <b>Premium active</b>\nuntil {date}"},
    "premium_invoice_sent": {"ru": "💳 Счёт выставлен", "uz": "💳 Hisob-faktura", "en": "💳 Invoice sent"},
    "premium_paid": {"ru": "⭐ <b>Premium активирован!</b>\n+{months} мес.", "uz": "⭐ <b>Premium!</b>\n+{months} oy", "en": "⭐ <b>Premium activated!</b>\n+{months} months"},
    "premium_pkg_desc": {"ru": "Premium на {months} мес. ({days} дн.)", "uz": "Premium {months} oy", "en": "Premium for {months} months"},

    # ==== REVEAL NEXT ====
    "reveal_next_btn_free": {"ru": "👁 Узнать · {n} БОНУС", "uz": "👁 · {n} BONUS", "en": "👁 Reveal · {n} FREE"},
    "reveal_next_btn_paid": {"ru": "👁 Узнать · {n} ⭐", "uz": "👁 · {n} ⭐", "en": "👁 Reveal · {n} ⭐"},
    "reveal_no_attempts": {"ru": "💎 Бесплатные кончились.\nКупить ещё?", "uz": "💎 Tugadi. Sotib olasizmi?", "en": "💎 Free attempts over. Buy more?"},
    "reveal_pack_title": {"ru": "👁 <b>Купить «Узнать»</b>\nСкидка растёт:", "uz": "👁 <b>«Aniqlash» sotib olish</b>", "en": "👁 <b>Buy «Reveal»</b>"},
    "reveal_pack_line": {"ru": "{n} шт — <b>{stars} ⭐</b> ({disc}%)", "uz": "{n} — <b>{stars} ⭐</b>", "en": "{n} pcs — <b>{stars} ⭐</b> ({disc}%)"},
    "reveal_pack_bought": {"ru": "✅ <b>{n} «Узнать»</b>\n−{stars} ⭐", "uz": "✅ <b>{n}</b>\n−{stars} ⭐", "en": "✅ <b>{n} «Reveal»</b>\n−{stars} ⭐"},
    "reveal_result_next": {"ru": "👁 <b>Кто лайкнул:</b>\n👤 <b>{name}</b>, {age}\n💬 {bio}\n\n🔗 <a href=\"tg://user?id={tid}\">{uname_or_link}</a>", "uz": "👁 <b>Kim layk qildi:</b>\n👤 <b>{name}</b>, {age}\n💬 {bio}\n\n🔗 <a href=\"tg://user?id={tid}\">{uname_or_link}</a>", "en": "👁 <b>Who liked you:</b>\n👤 <b>{name}</b>, {age}\n💬 {bio}\n\n🔗 <a href=\"tg://user?id={tid}\">{uname_or_link}</a>"},

    # ==== ЛАЙКИ ====
    "liked_you_title": {"ru": "💕 <b>Вас лайкнули!</b>", "uz": "💕 <b>Layk qilishdi!</b>", "en": "💕 <b>Someone liked you!</b>"},
    "liked_you_info": {"ru": "👤 <b>{name}</b>, {age}\n📄 {bio}", "uz": "👤 <b>{name}</b>, {age}\n📄 {bio}", "en": "👤 <b>{name}</b>, {age}\n📄 {bio}"},
    "liked_you_footer": {"ru": "👇 Ответь взаимно или пропусти:", "uz": "👇 O'zaro javob yoki o'tkazish:", "en": "👇 Reply or skip:"},
    "liked_no_photo": {"ru": "📷 <i>Нет фото</i>", "uz": "📷 <i>Foto yo'q</i>", "en": "📷 <i>No photo</i>"},
    "liked_ignored": {"ru": "💤 <b>Игнорировано</b>", "uz": "💤 <b>E'tiborsiz</b>", "en": "💤 <b>Ignored</b>"},
    "liked_reply_waiting": {"ru": "✅ <b>Ответил взаимно</b>\nЖдём второго…", "uz": "✅ <b>O'zaro</b>\nIkkinchisini kutamiz…", "en": "✅ <b>Replied back</b>\nWaiting for other…"},

    # ==== ВЗАИМНОСТЬ / МЭТЧ ====
    "mutual_title": {"ru": "💕 <b>Вы понравились друг другу!</b>", "uz": "💕 <b>Bir-biringizga!</b>", "en": "💕 <b>You liked each other!</b>"},
    "mutual_footer": {"ru": "👇 Подтверди знакомство:", "uz": "👇 Tasdiqlang:", "en": "👇 Confirm:"},
    "mutual_confirmed_one": {"ru": "✅ <b>Подтвердил</b>\nЖдём второго…", "uz": "✅ <b>Tasdiqlandi</b>\nKutamiz…", "en": "✅ <b>Confirmed</b>\nWaiting…"},
    "match_final_title": {"ru": "🎉 <b>МЭТЧ!</b>", "uz": "🎉 <b>MATCH!</b>", "en": "🎉 <b>MATCH!</b>"},
    "match_final_info": {"ru": "👤 <b>{name}</b>, {age}\n💬 {bio}", "uz": "👤 <b>{name}</b>, {age}\n💬 {bio}", "en": "👤 <b>{name}</b>, {age}\n💬 {bio}"},
    "match_final_footer": {"ru": "Напиши первым! 💬", "uz": "Birinchi yozing! 💬", "en": "Write first! 💬"},
    "auto_hello": {"ru": "👋 Привет! Я <b>{name}</b>, из 𝐍𝐞𝐱𝐭.. — хочу познакомиться 😊", "uz": "👋 Salom! Men <b>{name}</b>, 𝐍𝐞𝐱𝐭.. — tanishmoqchiman 😊", "en": "👋 Hi! I'm <b>{name}</b>, from 𝐍𝐞𝐱𝐭.. — let's chat 😊"},
    "no_profiles_limit": {"ru": "😔 <b>Нет анкет</b>\nПопробуй позже", "uz": "😔 <b>Anketalar yo'q</b>", "en": "😔 <b>No profiles</b>"},
})
    def _harmonize_translations():
    """Синхронизирует эмодзи-префикс в uz/en с ru-вариантом."""
    for _key, _block in T.items():
        if not isinstance(_block, dict): continue
        _ru = _block.get("ru")
        if not isinstance(_ru, str): continue
        _em = _leading_emoji(_ru)
        if not _em: continue
        for _lang in ("uz", "en"):
            _val = _block.get(_lang)
            if not isinstance(_val, str) or not _val: continue
            _cur_em = _leading_emoji(_val)
            if _cur_em != _em:
                _stripped = _val[len(_cur_em):].lstrip() if _cur_em else _val
                _block[_lang] = _em + " " + _stripped

_harmonize_translations()

def t(key, **kw):
    d = T.get(key, {})
    s = d.get(cur_lang()) or d.get("ru") or key
    return s.format(**kw) if kw else s

# ============================ ГЛАВНОЕ МЕНЮ ============================
def main_menu_kb(tg_id):
    rows = [
        [KeyboardButton("🔗 Моя ссылка"), KeyboardButton("🎯 𝐍𝐞𝐱𝐭..")],
        [KeyboardButton("🎲 Чат-рулетка"), KeyboardButton("👤 Профиль")],
        [KeyboardButton("🛒 Магазин"), KeyboardButton("👥 Пригласить")],
        [KeyboardButton("⭐ Premium"), KeyboardButton("ℹ️ Помощь")],
        [KeyboardButton("🌐 Язык")],
    ]
    try:
        if conn.execute("SELECT 1 FROM star_packages WHERE active=1 LIMIT 1").fetchone():
            rows.append([KeyboardButton(tr_btn("💎 Купить коины"))])
    except Exception: pass
    if is_admin(tg_id):
        rows.append([KeyboardButton("🛠 Админка")])
    else:
        if is_moder(get_user(tg_id)):
            rows.append([KeyboardButton("🛡 Модерка")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))

def yes_no_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("✅ Да"), KeyboardButton("❌ Отмена")]], resize_keyboard=True))

def cancel_reply_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))

def back_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))

def gender_kb(with_back=False):
    rows = [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")]]
    if with_back: rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))

def language_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇺🇿 O'zbekcha")],
        [KeyboardButton("🇬🇧 English")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)

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

def share_kb(link, text):
    share_url = ("https://t.me/share/url?url=" + urllib.parse.quote(link, safe="")
                 + "&text=" + urllib.parse.quote(text, safe=""))
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
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("➡️ Далее"), KeyboardButton("⏹️ Стоп")]], resize_keyboard=True))

def left_chat_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Новый поиск")],
        [KeyboardButton("🚩 Пожаловаться"), KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))

# ============================ 𝐍𝐞𝐱𝐭.. ============================
def next_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("🔥 Смотреть анкеты")],
        [KeyboardButton("📝 Моя анкета")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))

def next_reaction_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("❤️ Лайк"), KeyboardButton("👎 Дизлайк")],
        [KeyboardButton("💌 Написать"), KeyboardButton("🚩 Жалоба")],
        [KeyboardButton("💤 Выйти")],
    ], resize_keyboard=True))

def next_cancel_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))

def next_edit_back_kb():
    return tr_kb(ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))

def next_gender_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))

def next_looking_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку")],
        [KeyboardButton("🤷 Любого")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True))

def next_edit_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📝 Имя"), KeyboardButton("🎂 Возраст")],
        [KeyboardButton("📄 О себе"), KeyboardButton("📷 Фото")],
        [KeyboardButton("🎯 Кого ищу"), KeyboardButton("⚧ Пол")],
        [KeyboardButton("👁 Предпросмотр")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))

def next_like_inline_kb(like_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr_btn("💕 Ответить"), callback_data=f"nlike_yes:{like_id}")],
        [InlineKeyboardButton(tr_btn("💤 Игнорировать"), callback_data=f"nlike_no:{like_id}")],
    ])

def next_mutual_inline_kb(like_id, reveal_label=None):
    rows = [[InlineKeyboardButton(tr_btn("💕 Ответить"), callback_data=f"nmutual_yes:{like_id}")]]
    if reveal_label:
        rows.append([InlineKeyboardButton(reveal_label, callback_data=f"nreveal:{like_id}")])
    rows.append([InlineKeyboardButton(tr_btn("💤 Игнорировать"), callback_data=f"nmutual_no:{like_id}")])
    return InlineKeyboardMarkup(rows)

def next_final_match_kb(partner_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(tr_btn("👤 Перейти в профиль"), url=f"tg://user?id={partner_id}")]])

def next_reveal_inline_kb(target_id, reveal_label):
    return InlineKeyboardMarkup([[InlineKeyboardButton(reveal_label, callback_data=f"nreveal_card:{target_id}")]])

def next_reply_inline_kb(mid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr_btn("↩️ Ответить"), callback_data=f"nreply:{mid}")],
        [InlineKeyboardButton(tr_btn("🚩 Жалоба"), callback_data=f"nreport:{mid}")],
    ])

# ============================ PREMIUM ============================
def premium_menu_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("📅 1 месяц · 100 ⭐")],
        [KeyboardButton("📅 2 месяца · 180 ⭐")],
        [KeyboardButton("📅 3 месяца · 250 ⭐")],
        [KeyboardButton("👁 Купить «Узнать»")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))

def premium_packages_inline():
    rows = []
    for p in VIP_PACKAGES:
        rows.append([InlineKeyboardButton(f"⭐ {p['label']} — {p['stars']} ⭐", callback_data=f"vipbuy:{p['months']}")])
    return InlineKeyboardMarkup(rows)

def reveal_pack_kb():
    rows = []
    for p in REVEAL_PACKAGES:
        label = (f"{p['count']} шт — {p['stars']} ⭐ (−{p['discount']}%)" if p["discount"] > 0
                 else f"{p['count']} шт — {p['stars']} ⭐")
        rows.append([KeyboardButton(label)])
    rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))

def reveal_pack_inline():
    rows = []
    for p in REVEAL_PACKAGES:
        label = (f"{p['count']} шт — {p['stars']} ⭐ (−{p['discount']}%)" if p["discount"] > 0
                 else f"{p['count']} шт — {p['stars']} ⭐")
        rows.append([InlineKeyboardButton(label, callback_data=f"revbuy:{p['count']}")])
    return InlineKeyboardMarkup(rows)

# ============================ РЕФЕРАЛЫ ============================
def referral_kb(uid=None):
    rows = [[KeyboardButton("🏆 Топ пригласивших")]]
    if uid is not None and is_admin(uid):
        rows.append([KeyboardButton("✏️ Изменить")])
    rows.append([KeyboardButton("⬅️ Назад")])
    return tr_kb(ReplyKeyboardMarkup(rows, resize_keyboard=True))

def ref_settings_kb():
    return tr_kb(ReplyKeyboardMarkup([
        [KeyboardButton("👑 VIP: дней"), KeyboardButton("👥 VIP: друзей")],
        [KeyboardButton("🛡 Модер: дней"), KeyboardButton("👥 Модер: друзей")],
        [KeyboardButton("📷 Фото"), KeyboardButton("🚫 Убрать фото")],
        [KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Меню")],
    ], resize_keyboard=True))

def ref_rewards_kb(uid, link=None):
    rows = []
    if link:
        full = link if link.startswith("http") else ("https://" + link)
        share_url = ("https://t.me/share/url?url=" + urllib.parse.quote(full, safe="")
                     + "&text=" + urllib.parse.quote(t("ref_share_text"), safe=""))
        rows.append([InlineKeyboardButton(t("btn_share_ref"), url=share_url)])
    u = get_user(uid)
    n_coins = REF_REWARD_VIP if (u and is_vip(u)) else REF_REWARD_NORMAL
    rows += [
        [InlineKeyboardButton(t("ref_claim_coins_btn", n=n_coins, v=REF_REWARD_VIP), callback_data="ref_info")],
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
        [KeyboardButton("⭐ Коины за Stars"), KeyboardButton("⭐ Возврат Stars")],
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

def vip_bulk_menu_kb(bulk_filter):
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

def adm_channels_kb(uid=None):
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
        [KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("📢 Обязательные каналы")],
        [KeyboardButton("ℹ️ Помощь")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True))

def moder_decision_kb(app_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Выдать", callback_data=f"modapp:ok:{app_id}"),
        InlineKeyboardButton("Отказ", callback_data=f"modapp:no:{app_id}"),
    ]])

# ============================ ПОДПИСКА ============================
def subscribe_kb(msg_id, channels):
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
def channel_url(raw):
    raw = (raw or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"): return raw
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"): return "https://" + raw
    return "https://t.me/" + raw.lstrip("@")

def is_valid_btn_url(url):
    if not url or any(ch.isspace() for ch in url): return False
    low = url.lower()
    return low.startswith("https://") or low.startswith("http://") or low.startswith("tg://")

def channel_title(ch):
    try: ttl = ch["title"]
    except (KeyError, IndexError, TypeError): ttl = None
    if ttl: return ttl
    raw = (ch["chat_username"] or "").strip()
    name = raw.lstrip("@").rstrip("/").split("/")[-1]
    return "📢 " + (name or "Канал")

def _chat_ref_for_check(raw):
    raw = (raw or "").strip()
    if raw.startswith("@"): return raw
    low = raw.lower()
    if "t.me/" in low:
        tail = raw.split("t.me/", 1)[1].strip("/")
        if tail.startswith("+") or tail.lower().startswith("joinchat"): return None
        tail = tail.split("?")[0].split("/")[0]
        return "@" + tail if tail else None
    if raw and not raw.startswith("http"): return "@" + raw.lstrip("@")
    return None

def _ch_added_by(c):
    try: v = c["added_by"]
    except (KeyError, IndexError, TypeError): return None
    if v is None: return None
    try: return int(v)
    except (ValueError, TypeError): return None

def channels_deletable_by(uid):
    chans = conn.execute("SELECT * FROM mandatory_channels").fetchall()
    if is_admin(uid): return chans
    uid = int(uid)
    return [c for c in chans if _ch_added_by(c) == uid]

async def get_mandatory_channels():
    return conn.execute("SELECT * FROM mandatory_channels").fetchall()

async def user_subscribed_all(context, user_id, channels):
    for ch in channels:
        ref = _chat_ref_for_check(ch["chat_username"])
        if ref is None: continue
        try:
            member = await context.bot.get_chat_member(ref, user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED): return False
        except TelegramError: continue
    return True

# ============================ РЕФ-КОДЫ ============================
REF_CODE_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"

def get_or_create_ref_code(uid):
    u = get_user(uid)
    if u:
        try:
            if u["ref_code"]: return u["ref_code"]
        except (KeyError, IndexError, TypeError): pass
    for _ in range(50):
        code = "".join(random.choice(REF_CODE_CHARS) for _ in range(5))
        if not conn.execute("SELECT 1 FROM users WHERE ref_code=?", (code,)).fetchone():
            conn.execute("UPDATE users SET ref_code=? WHERE tg_id=?", (code, uid))
            conn.commit(); return code
    return str(uid)

def resolve_ref_code(code):
    row = conn.execute("SELECT tg_id FROM users WHERE ref_code=?", (code,)).fetchone()
    if row: return row["tg_id"]
    if code.isdigit():
        old = conn.execute("SELECT tg_id FROM users WHERE tg_id=?", (int(code),)).fetchone()
        if old: return old["tg_id"]
    return None

def qualified_referrals(uid):
    return conn.execute(
        "SELECT COUNT(*) c FROM referrals r JOIN users u ON u.tg_id=r.referred_id "
        "WHERE r.referrer_id=? AND r.active=1 AND u.custom_link IS NOT NULL",
        (uid,)).fetchone()["c"]

def progress_bar(cur, target, slots=10):
    if target <= 0: return ""
    filled = max(0, min(slots, round(slots * cur / target)))
    return "▰" * filled + "▱" * (slots - filled)

# ============================ LINK FLOW ============================
LINK_FLOW_TTL_HOURS = 6

def save_link_flow(user_id, target_id, state, msg_type=None):
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.execute(
            "INSERT INTO link_flow (user_id, target_id, msg_type, state, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, target_id, msg_type, state, now_iso()))
        conn.commit()
    except Exception as e: log.warning("save_link_flow: %s", e)

def load_link_flow(user_id):
    try: row = conn.execute("SELECT * FROM link_flow WHERE user_id=?", (user_id,)).fetchone()
    except Exception: return None
    if not row: return None
    try:
        if now_dt() - datetime.fromisoformat(row["updated_at"]) > timedelta(hours=LINK_FLOW_TTL_HOURS):
            clear_link_flow(user_id); return None
    except Exception: pass
    return row

def clear_link_flow(user_id):
    try:
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (user_id,))
        conn.commit()
    except Exception as e: log.warning("clear_link_flow: %s", e)

# ============================ BOT USERNAME ============================
_BOT_USERNAME = None

async def get_bot_username(context):
    global _BOT_USERNAME
    if _BOT_USERNAME is None:
        _BOT_USERNAME = (await context.bot.get_me()).username
    return _BOT_USERNAME

async def build_start_link(context, code):
    return f"t.me/{await get_bot_username(context)}?start={code}"

# ============================ АВТО-ПЕРЕВОД ============================
def _translate_sync(text, target):
    if not text or not text.strip(): return text
    try:
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
               "&sl=auto&tl=" + urllib.parse.quote(target)
               + "&dt=t&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return out.strip() or text
    except Exception as e:
        log.warning("translate(%s): %s", target, e); return text

async def translate_to_all(text):
    ru = await asyncio.to_thread(_translate_sync, text, "ru")
    uz = await asyncio.to_thread(_translate_sync, text, "uz")
    en = await asyncio.to_thread(_translate_sync, text, "en")
    return ru or text, uz or text, en or text

def item_title(item):
    lang = cur_lang()
    try:
        if lang == "uz" and item["title_uz"]: return item["title_uz"]
        if lang == "en" and item["title_en"]: return item["title_en"]
    except (KeyError, IndexError, TypeError): pass
    return item["title"]

# ============================ NEXT-УТИЛИТЫ ============================
def can_show_profile(viewer_id, target_id):
    try:
        week_ago = (now_dt() - timedelta(days=NEXT_REPEAT_WINDOW_DAYS)).isoformat()
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM nearby_shown WHERE viewer_id=? AND target_id=? AND shown_at>?",
            (viewer_id, target_id, week_ago)).fetchone()["c"]
        return cnt < NEXT_REPEAT_LIMIT
    except Exception: return True

def mark_shown(viewer_id, target_id):
    try:
        conn.execute("INSERT INTO nearby_shown (viewer_id, target_id, shown_at) VALUES (?, ?, ?)",
                     (viewer_id, target_id, now_iso()))
        conn.commit()
    except Exception as e: log.debug("mark_shown: %s", e)

def total_profiles_count():
    try:
        return conn.execute("SELECT COUNT(*) c FROM nearby_profiles WHERE active=1").fetchone()["c"]
    except Exception: return 0

def get_reveal_free_left(uid):
    period = now_dt().strftime("%Y-%m")
    try:
        row = conn.execute("SELECT used FROM reveal_free_used WHERE user_id=? AND period=?",
                           (uid, period)).fetchone()
        used = row["used"] if row else 0
    except Exception: used = 0
    return max(0, REVEAL_FREE_PER_MONTH - used)

def use_reveal_free(uid):
    period = now_dt().strftime("%Y-%m")
    try:
        row = conn.execute("SELECT * FROM reveal_free_used WHERE user_id=? AND period=?",
                           (uid, period)).fetchone()
        if row:
            conn.execute("UPDATE reveal_free_used SET used = used + 1 WHERE id=?", (row["id"],))
        else:
            conn.execute("INSERT INTO reveal_free_used (user_id, period, used) VALUES (?, ?, 1)",
                         (uid, period))
        conn.commit()
    except Exception as e: log.warning("use_reveal_free: %s", e)

def get_reveal_paid_left(uid):
    try:
        bought = conn.execute(
            "SELECT COALESCE(SUM(count),0) s FROM reveal_purchases WHERE user_id=? AND refunded=0",
            (uid,)).fetchone()["s"]
        used = conn.execute(
            "SELECT COUNT(*) c FROM nearby_notifications WHERE user_id=? AND type='reveal_paid'",
            (uid,)).fetchone()["c"]
        return max(0, bought - used)
    except Exception: return 0

def register_notification(uid, chat_id, message_id, ntype, target_id=None, like_id=None):
    try:
        expires = (now_dt() + timedelta(days=NEXT_NOTIF_TTL_DAYS)).isoformat()
        conn.execute(
            "INSERT INTO nearby_notifications "
            "(user_id, chat_id, message_id, type, target_id, like_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, chat_id, message_id, ntype, target_id, like_id, expires, now_iso()))
        conn.commit()
    except Exception as e: log.debug("register_notification: %s", e)

# ============================ ГЛОБАЛЬНЫЕ БУФЕРЫ ============================
BCAST_ALBUMS = {}
SPECTATORS = {}
SESSION_SPECTATORS = defaultdict(set)
_QUEUE_REMIND = {}
# ============================ НАВИГАЦИЯ (aiogram v3) ============================
async def clean_screen(bot, chat_id, message=None, user_data=None):
    """Удаляет сообщение юзера + прошлые сообщения меню."""
    if message is not None:
        try:
            await message.delete()
        except TelegramError:
            pass

    if user_data is None:
        return

    for mid in user_data.pop("extra_msg_ids", []):
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramError:
            pass

    mid = user_data.pop("last_menu_msg_id", None)
    if mid:
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramError:
            pass

    nid = user_data.pop("next_card_id", None)
    if nid:
        try:
            await bot.delete_message(chat_id, nid)
        except TelegramError:
            pass


def track_extra(user_data, msg):
    """Запомнить id «служебного» сообщения для удаления при следующем nav."""
    if user_data is None:
        return
    user_data.setdefault("extra_msg_ids", []).append(msg.message_id)


async def send_menu(bot, chat_id, user_data, text, reply_markup=None, parse_mode=None):
    if parse_mode is None and _needs_html(text):
        parse_mode = "HTML"
    msg = await bot.send_message(chat_id, text,
                                  reply_markup=reply_markup, parse_mode=parse_mode)
    if user_data is not None:
        user_data["last_menu_msg_id"] = msg.message_id
    return msg


async def nav(bot, chat_id, user_data, message, text,
              reply_markup=None, parse_mode=None):
    """Удалить прошлое меню + сообщение юзера → отправить новое."""
    await clean_screen(bot, chat_id, message=message, user_data=user_data)
    return await send_menu(bot, chat_id, user_data, text, reply_markup, parse_mode)


async def go_home(bot, chat_id, user_data, message, uid):
    """Сброс стейта → отправка главного меню."""
    if user_data is not None:
        user_data["state"] = None
    return await nav(bot, chat_id, user_data, message,
                     t("main_menu"), main_menu_kb(uid))


# ============================ УВЕДОМЛЕНИЯ ============================
async def notify_admins(context, text, reply_markup=None, parse_mode=None):
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text,
                                            reply_markup=reply_markup,
                                            parse_mode=parse_mode)
        except TelegramError:
            pass


async def notify_staff(context, text, reply_markup=None, parse_mode=None):
    targets = set(ADMIN_IDS)
    try:
        for r in conn.execute(
            "SELECT tg_id FROM users WHERE is_moder=1 OR (moder_until IS NOT NULL AND moder_until>?)",
            (now_iso(),),
        ).fetchall():
            targets.add(r["tg_id"])
    except Exception as e:
        log.debug("notify_staff query: %s", e)
    for tid in targets:
        try:
            await context.bot.send_message(tid, text,
                                            reply_markup=reply_markup,
                                            parse_mode=parse_mode)
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
        f"📝 Имя: <b>{name}</b>\n"
        f"🆔 ID: <code>{tg_user.id}</code>\n"
        f"👤 Username: {uname}\n"
        f"🕐 Время: {when} (UTC)\n"
        f"👥 Всего: <b>{total}</b>"
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
        f"📝 Имя: <b>{name}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Username: {uname}\n"
        f"🕐 {when} (UTC)"
    )
    if extra:
        text += f"\n{extra}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML")
        except TelegramError:
            pass


# ============================ VIP БОНУС ============================
async def grant_daily_bonus(uid, context):
    u = get_user(uid)
    if not is_vip(u) or is_unlimited(u):
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        if u["last_bonus"] == today:
            return
    except (KeyError, IndexError):
        pass
    conn.execute(
        "UPDATE users SET coins = coins + ?, last_bonus=? WHERE tg_id=?",
        (VIP_DAILY_BONUS, today, uid),
    )
    conn.commit()
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(uid))
        await context.bot.send_message(uid, t("vip_daily_bonus", n=VIP_DAILY_BONUS),
                                        parse_mode="HTML")
        set_cur_lang(_sl)
    except TelegramError as e:
        log.debug("grant_daily_bonus(%s): %s", uid, e)


# ============================ АВТО-МЕНЮ ============================
async def deliver_start_menu(context, uid, greet=True):
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
                                            parse_mode="HTML",
                                            reply_markup=gender_kb())
        elif user_age_int(user) is None:
            UD[uid]["state"] = "set_age_first"
            await context.bot.send_message(uid, t("age_register_ask"),
                                            parse_mode="HTML",
                                            reply_markup=ReplyKeyboardRemove())
        elif greet:
            UD[uid]["state"] = None
            await context.bot.send_message(uid, t("welcome_back", name=name),
                                            parse_mode="HTML",
                                            reply_markup=main_menu_kb(uid))
        else:
            UD[uid]["state"] = None
            await context.bot.send_message(uid, t("main_menu"),
                                            reply_markup=main_menu_kb(uid))
    finally:
        set_cur_lang(_sl)


# ============================ РУЛЕТКА-УТИЛИТЫ ============================
def get_active_session(user_id):
    try:
        return conn.execute(
            "SELECT * FROM roulette_sessions WHERE active=1 AND (user1_id=? OR user2_id=?)",
            (user_id, user_id),
        ).fetchone()
    except Exception:
        return None


def compatible(a, b):
    a_ok = a["pref"] == "any" or a["pref"] == b["gender"]
    b_ok = b["pref"] == "any" or b["pref"] == a["gender"]
    return a_ok and b_ok


def is_banned_pair(u1, u2):
    try:
        row = conn.execute(
            "SELECT 1 FROM bans WHERE until>? AND "
            "((owner_id=? AND banned_id=?) OR (owner_id=? AND banned_id=?))",
            (now_iso(), u1, u2, u2, u1),
        ).fetchone()
        return row is not None
    except Exception:
        return False


# ============================ ССЫЛКА-УТИЛИТЫ ============================
LINK_ALPHABET = string.ascii_letters + string.digits + "_-"


def valid_link_code(code):
    return 1 <= len(code) <= 10 and all(c in LINK_ALPHABET for c in code)


def can_change_link(user_row):
    if is_vip(user_row):
        return True, None
    try:
        if not user_row["link_changed_at"]:
            return True, None
    except (KeyError, IndexError, TypeError):
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
def user_is_disposable(uid):
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
    try:
        if conn.execute("SELECT 1 FROM star_purchases WHERE user_id=? LIMIT 1",
                        (uid,)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM nearby_profiles WHERE user_id=? LIMIT 1",
                        (uid,)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM nearby_matches WHERE user1_id=? OR user2_id=? LIMIT 1",
                        (uid, uid)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM vip_purchases WHERE user_id=? LIMIT 1",
                        (uid,)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM reveal_purchases WHERE user_id=? LIMIT 1",
                        (uid,)).fetchone():
            return False
    except Exception:
        return False
    return True


def purge_user(uid, force=False):
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
        partner_ids = set()
        for r in partner_rows:
            try:
                partner_ids.add(r["user2_id"] if r["user1_id"] == uid else r["user1_id"])
            except (KeyError, IndexError):
                pass

        conn.execute("DELETE FROM users WHERE tg_id=?", (uid,))
        conn.execute("DELETE FROM referrals WHERE referred_id=? OR referrer_id=?",
                     (uid, uid))
        conn.execute("DELETE FROM link_flow WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.execute(
            "UPDATE roulette_sessions SET active=0, ended_at=COALESCE(ended_at, ?) "
            "WHERE active=1 AND (user1_id=? OR user2_id=?)",
            (now_iso(), uid, uid),
        )

        conn.execute("DELETE FROM nearby_profiles WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM nearby_likes WHERE from_id=? OR to_id=?", (uid, uid))
        conn.execute("DELETE FROM nearby_matches WHERE user1_id=? OR user2_id=?",
                     (uid, uid))
        conn.execute("DELETE FROM nearby_messages WHERE from_id=? OR to_id=?",
                     (uid, uid))
        conn.execute("DELETE FROM nearby_answers WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM nearby_shown WHERE viewer_id=? OR target_id=?",
                     (uid, uid))
        conn.execute("DELETE FROM nearby_notifications WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM reveal_free_used WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM reveal_purchases WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM vip_purchases WHERE user_id=?", (uid,))

        conn.execute("DELETE FROM anon_watchers WHERE mod_id=? OR target_id=?",
                     (uid, uid))
        conn.execute("DELETE FROM anon_messages WHERE from_id=? OR to_id=?",
                     (uid, uid))

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
                await BOTP.send_message(pid, t("roulette_left"),
                                         reply_markup=left_chat_kb())
            finally:
                set_cur_lang(_sl)
        except TelegramError as e:
            log.warning("notify purged partner %s: %s", pid, e)


def _is_dead_account(err):
    s = str(err).lower()
    keys = ("blocked", "deactivated", "chat not found", "user not found",
            "bot can't initiate", "bot was blocked", "user is deactivated",
            "peer_id_invalid", "forbidden")
    return any(k in s for k in keys)


def safe_purge_dead(uid):
    if not user_is_disposable(uid):
        return False
    return purge_user(uid, force=False)
    # ============================ MIDDLEWARE (язык) ============================
class _LangMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = None
        try:
            if hasattr(event, "from_user") and event.from_user is not None:
                user = event.from_user
            elif hasattr(event, "message") and event.message is not None:
                user = event.message.from_user
        except Exception:
            pass
        if user is not None and getattr(user, "id", None):
            try:
                set_cur_lang(get_lang(user.id))
            except Exception:
                set_cur_lang("ru")
        else:
            set_cur_lang("ru")
        return await handler(event, data)


dp.update.outer_middleware(_LangMiddleware())


# ============================ ХЕЛПЕРЫ ============================
async def _reply(message, text, reply_markup=None, parse_mode=None, **kw):
    if parse_mode is None and _needs_html(text):
        parse_mode = "HTML"
    try:
        return await message.answer(text, reply_markup=reply_markup,
                                     parse_mode=parse_mode, **kw)
    except TelegramError as e:
        log.warning("_reply: %s", e)
        return None


async def _say(bot, chat_id, text, reply_markup=None, parse_mode=None, **kw):
    if parse_mode is None and _needs_html(text):
        parse_mode = "HTML"
    try:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup,
                                       parse_mode=parse_mode, **kw)
    except TelegramError as e:
        log.warning("_say to %s: %s", chat_id, e)
        return None


async def _safe_delete_message(bot, chat_id, mid):
    try:
        await bot.delete_message(chat_id, mid)
    except TelegramError:
        pass


async def _welcome_flow(bot, uid, greet=True):
    u = get_user(uid)
    if not u:
        return
    name = html.escape(u["first_name"] or "друг")
    if not u["gender"]:
        UD[uid]["state"] = "set_gender_first"
        await _say(bot, uid, t("welcome", name=name), reply_markup=gender_kb())
    elif user_age_int(u) is None:
        UD[uid]["state"] = "set_age_first"
        await _say(bot, uid, t("age_register_ask"), reply_markup=ReplyKeyboardRemove())
    elif greet:
        UD[uid]["state"] = None
        await _say(bot, uid, t("welcome_back", name=name), reply_markup=main_menu_kb(uid))
    else:
        UD[uid]["state"] = None
        await _say(bot, uid, t("main_menu"), reply_markup=main_menu_kb(uid))


async def _gate_ok(bot, uid):
    """True, если пользователь прошёл subgate (или он выключен)."""
    if is_staff(uid):
        return True
    if get_setting("subgate_enabled", "0") != "1":
        return True
    chans = await get_mandatory_channels()
    if not chans:
        return True
    for ch in chans:
        ref = _chat_ref_for_check(ch["chat_username"])
        if ref is None:
            continue
        try:
            m = await bot.get_chat_member(ref, uid)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except TelegramError:
            continue
    return True


# ============================ /start ============================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    uid = message.from_user.id
    new_user = get_user(uid) is None

    ensure_user(uid, message.from_user.username, message.from_user.first_name)
    touch_user(uid)
    u = get_user(uid)

    if is_banned(u):
        await _reply(message, t("banned"))
        return

    # ---- Subgate ----
    if not await _gate_ok(message.bot, uid):
        chans = await get_mandatory_channels()
        await _reply(message, t("subgate_start"), reply_markup=subscribe_gate_kb(chans))
        return

    payload = (command.args or "").strip() if command else ""

    # ---- Deep-link для анонимки: /start link_<code> ----
    if payload.startswith("link_"):
        await handle_anon_deeplink(message, payload[5:])
        return

    # ---- Реферальный код ----
    if payload and new_user:
        ref_id = resolve_ref_code(payload)
        if ref_id and ref_id != uid and get_user(ref_id):
            try:
                conn.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, coins_awarded, active, created_at) "
                    "VALUES (?, ?, 0, 1, ?)",
                    (ref_id, uid, now_iso()),
                )
                conn.commit()
                ref_user = get_user(ref_id)
                bonus = REF_INVITED_BONUS_VIP if is_vip(ref_user) else REF_INVITED_BONUS
                conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?",
                             (bonus, uid))
                conn.commit()
                _sl = cur_lang()
                set_cur_lang(get_lang(uid))
                await _say(message.bot, uid, t("ref_welcome_bonus", n=bonus))
                set_cur_lang(_sl)
            except Exception as e:
                log.debug("referral save: %s", e)

    if new_user:
        try:
            await notify_admins_new_user(message, message.from_user)
        except Exception:
            pass

    try:
        await grant_daily_bonus(uid, message)
    except Exception:
        pass

    await _welcome_flow(message.bot, uid, greet=True)


# ============================ /help, /menu, /cancel ============================
@dp.message(Command("help"))
@dp.message(Command("menu"))
async def cmd_help(message: Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username, message.from_user.first_name)
    UD[uid]["state"] = None
    await _reply(message, t("main_menu"), reply_markup=main_menu_kb(uid))


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    uid = message.from_user.id
    UD[uid]["state"] = None
    clear_link_flow(uid)
    await _reply(message, t("cancelled"), reply_markup=main_menu_kb(uid))


# ============================ ПРОФИЛЬ ============================
async def _render_profile(uid):
    u = get_user(uid)
    if not u:
        return t("main_menu")

    # Время в рулетке — считаем в Python (совместимо и с SQLite, и с PG)
    roulette_secs = 0
    try:
        rows = conn.execute(
            "SELECT started_at, ended_at, active FROM roulette_sessions "
            "WHERE user1_id=? OR user2_id=?",
            (uid, uid),
        ).fetchall()
        for r in rows:
            try:
                start = datetime.fromisoformat(r["started_at"])
                end_str = r["ended_at"]
                end = now_dt() if (r["active"] or not end_str) else datetime.fromisoformat(end_str)
                roulette_secs += max(0, int((end - start).total_seconds()))
            except (ValueError, TypeError):
                pass
    except Exception:
        pass

    invited = _safe(lambda: conn.execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)
    ).fetchone()["c"], default=0) or 0

    rank = "—"
    try:
        rows = conn.execute(
            "SELECT referrer_id, COUNT(*) c FROM referrals WHERE active=1 "
            "GROUP BY referrer_id ORDER BY c DESC LIMIT 100"
        ).fetchall()
        for i, r in enumerate(rows, 1):
            if r["referrer_id"] == uid:
                rank = f"#{i}"
                break
    except Exception:
        pass

    stars = _safe(lambda: conn.execute(
        "SELECT COALESCE(SUM(stars),0) s FROM star_purchases WHERE user_id=? AND refunded=0",
        (uid,),
    ).fetchone()["s"], default=0) or 0

    vip_str = t("vip_none")
    if is_admin(uid):
        vip_str = "👑 ADMIN"
    elif is_moder(u):
        vip_str = "🛡 MODER"
    elif is_vip(u):
        try:
            dt = datetime.fromisoformat(u["vip_until"])
            vip_str = t("vip_until", date=dt.strftime("%d.%m.%Y"))
        except Exception:
            vip_str = "✅"

    reg_date = "—"
    try:
        reg_date = datetime.fromisoformat(u["created_at"]).strftime("%d.%m.%Y")
    except Exception:
        pass

    return t(
        "profile_full",
        id=uid,
        name=html.escape(u["first_name"] or "—"),
        gender=gender_label(u["gender"]),
        age=u["age"] or "—",
        roulette_time=fmt_duration(roulette_secs),
        sent=_safe(lambda: conn.execute(
            "SELECT COUNT(*) c FROM anon_messages WHERE from_id=?", (uid,)
        ).fetchone()["c"], default=0) or 0,
        received=_safe(lambda: conn.execute(
            "SELECT COUNT(*) c FROM anon_messages WHERE to_id=?", (uid,)
        ).fetchone()["c"], default=0) or 0,
        invited=invited,
        rank=rank,
        vip=vip_str,
        coins=u["coins"] or 0,
        stars=stars,
        reg_date=reg_date,
    )


@dp.message(F.text == "👤 Профиль")
@dp.message(F.text == "👤 Profil")
@dp.message(F.text == "👤 Profile")
async def btn_profile(message: Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username, message.from_user.first_name)
    UD[uid]["state"] = None
    await _reply(message, await _render_profile(uid), reply_markup=profile_kb())


@dp.message(F.text == "✏️ Сменить пол")
@dp.message(F.text == "✏️ Jinsni o'zgartirish")
@dp.message(F.text == "✏️ Change gender")
async def btn_change_gender(message: Message):
    UD[message.from_user.id]["state"] = "change_gender"
    await _reply(message, t("choose_new_gender"), reply_markup=gender_kb(with_back=True))


@dp.message(F.text == "✏️ Изменить возраст")
@dp.message(F.text == "✏️ Yoshni o'zgartirish")
@dp.message(F.text == "✏️ Change age")
async def btn_change_age(message: Message):
    UD[message.from_user.id]["state"] = "change_age"
    await _reply(message, t("age_enter_number"), reply_markup=age_back_kb())


@dp.message(F.text == "🎁 Подарить коины")
@dp.message(F.text == "🎁 Coin sovg'a qilish")
@dp.message(F.text == "🎁 Gift coins")
async def btn_gift_coins(message: Message):
    uid = message.from_user.id
    UD[uid]["state"] = "gift_id"
    UD[uid]["gift"] = {}
    await _reply(message, t("giftcoins_ask_id"), reply_markup=cancel_reply_kb())


# ============================ ЯЗЫК ============================
@dp.message(F.text == "🌐 Язык")
@dp.message(F.text == "🌐 Til")
@dp.message(F.text == "🌐 Language")
async def btn_lang(message: Message):
    await _reply(message, t("lang_choose"), reply_markup=language_menu_kb())


@dp.message(F.text.in_({"🇷🇺 Русский", "🇺🇿 O'zbekcha", "🇬🇧 English"}))
async def btn_set_lang(message: Message):
    uid = message.from_user.id
    m = {"🇷🇺 Русский": "ru", "🇺🇿 O'zbekcha": "uz", "🇬🇧 English": "en"}
    lang = m.get(message.text, "ru")
    set_lang(uid, lang)
    set_cur_lang(lang)
    await _reply(message, t("lang_set"), reply_markup=main_menu_kb(uid))


# ============================ ПОМОЩЬ ============================
@dp.message(F.text == "ℹ️ Помощь")
@dp.message(F.text == "ℹ️ Yordam")
@dp.message(F.text == "ℹ️ Help")
async def btn_help(message: Message):
    await _reply(message, t("help"), reply_markup=main_menu_kb(message.from_user.id))


# ============================ НАЗАД / МЕНЮ ============================
@dp.message(F.text == "⬅️ Назад")
@dp.message(F.text == "⬅️ Orqaga")
@dp.message(F.text == "⬅️ Back")
@dp.message(F.text == "🏠 Меню")
@dp.message(F.text == "🏠 Menyu")
@dp.message(F.text == "🏠 Menu")
async def btn_back(message: Message):
    uid = message.from_user.id
    UD[uid]["state"] = None
    clear_link_flow(uid)
    await _reply(message, t("main_menu"), reply_markup=main_menu_kb(uid))


# ============================ ПРИГЛАСИТЬ (рефералы) ============================
async def _render_referral(uid):
    u = get_user(uid)
    code = get_or_create_ref_code(uid)
    link = f"https://t.me/{_BOT_USERNAME or 'bot'}?start={code}"
    reward = REF_REWARD_VIP if (u and is_vip(u)) else REF_REWARD_NORMAL
    total = _safe(lambda: conn.execute(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND active=1", (uid,)
    ).fetchone()["c"], default=0) or 0
    earned = _safe(lambda: conn.execute(
        "SELECT COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE referrer_id=?",
        (uid,),
    ).fetchone()["s"], default=0) or 0
    bonus = t("referral_bonus_vip") if (u and is_vip(u)) else t("referral_bonus_normal")
    return t("referral_screen", reward=reward, bonus=bonus,
             total=total, earned=earned, link=link)


@dp.message(F.text == "👥 Пригласить")
@dp.message(F.text == "👥 Taklif qilish")
@dp.message(F.text == "👥 Invite")
async def btn_referral(message: Message):
    uid = message.from_user.id
    UD[uid]["state"] = None
    if _BOT_USERNAME is None:
        try:
            await get_bot_username(message)
        except Exception:
            pass
    txt = await _render_referral(uid)
    code = get_or_create_ref_code(uid)
    link = f"https://t.me/{_BOT_USERNAME or 'bot'}?start={code}"
    await _reply(message, txt, reply_markup=referral_kb(uid))
    try:
        await message.bot.send_message(uid, "👇",
                                        reply_markup=ref_rewards_kb(uid, link))
    except TelegramError:
        pass


@dp.message(F.text == "🏆 Топ пригласивших")
@dp.message(F.text == "🏆 Top taklif qilganlar")
@dp.message(F.text == "🏆 Top inviters")
async def btn_top_ref(message: Message):
    try:
        rows = conn.execute(
            "SELECT r.referrer_id, u.first_name, u.username, COUNT(*) c "
            "FROM referrals r JOIN users u ON u.tg_id=r.referrer_id "
            "WHERE r.active=1 GROUP BY r.referrer_id, u.first_name, u.username "
            "ORDER BY c DESC LIMIT 20"
        ).fetchall()
    except Exception:
        rows = []
    if not rows:
        await _reply(message, t("top_empty"),
                     reply_markup=referral_kb(message.from_user.id))
        return
    lines = [t("top_title"), "━━━━━━━━━━━━━━━━━━━━"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows, 1):
        m = medals[i - 1] if i <= 3 else f"{i}."
        nm = html.escape(r["first_name"] or "—")
        lines.append(f"{m} <b>{nm}</b> — {r['c']}")
    await _reply(message, "\n".join(lines),
                 reply_markup=referral_kb(message.from_user.id))
    def _link_url(uid):
    u = get_user(uid)
    if not u or not u["custom_link"]:
        return ""
    return f"https://t.me/{_BOT_USERNAME or 'bot'}?start=link_{u['custom_link']}"


@dp.message(F.text == "🔗 Моя ссылка")
@dp.message(F.text == "🔗 Havolam")
@dp.message(F.text == "🔗 My link")
async def btn_my_link(message: Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username, message.from_user.first_name)
    if _BOT_USERNAME is None:
        try:
            await get_bot_username(message)
        except Exception:
            pass
    UD[uid]["state"] = None
    await _reply(message, t("link_section"), reply_markup=link_menu_kb())


@dp.message(F.text == "🔗 Показать ссылку")
@dp.message(F.text == "🔗 Havolani ko'rsatish")
@dp.message(F.text == "🔗 Show link")
async def btn_show_link(message: Message):
    uid = message.from_user.id
    if _BOT_USERNAME is None:
        try:
            await get_bot_username(message)
        except Exception:
            pass
    u = get_user(uid)
    if not u or not u["custom_link"]:
        UD[uid]["state"] = "link_create"
        await _reply(message, t("link_no_link"), reply_markup=link_code_kb())
        return
    link = _link_url(uid)
    await _reply(message, t("link_show", link=link),
                 reply_markup=share_kb(link, t("share_text")))
    try:
        await message.bot.send_message(uid, "👇", reply_markup=link_menu_kb())
    except TelegramError:
        pass


@dp.message(F.text == "✏️ Сменить ссылку")
@dp.message(F.text == "✏️ Havolani o'zgartirish")
@dp.message(F.text == "✏️ Change link")
async def btn_change_link(message: Message):
    uid = message.from_user.id
    u = get_user(uid)
    ok, reason = can_change_link(u)
    if not ok:
        await _reply(message, reason, reply_markup=link_menu_kb())
        return
    UD[uid]["state"] = "link_change"
    await _reply(message, t("link_change"), reply_markup=link_code_kb())


@dp.message(F.text.regexp(r"^[A-Za-z0-9_\-]{1,10}$"))
async def handle_link_code(message: Message):
    uid = message.from_user.id
    state = UD[uid].get("state")
    if state not in ("link_create", "link_change"):
        return
    code = message.text.strip()
    if not valid_link_code(code):
        await _reply(message, t("link_invalid"), reply_markup=link_code_kb())
        return
    exists = conn.execute(
        "SELECT 1 FROM users WHERE custom_link=? AND tg_id<>?", (code, uid)
    ).fetchone()
    if exists:
        await _reply(message, t("link_taken"), reply_markup=link_code_kb())
        return

    u = get_user(uid)
    old = u["custom_link"] if u else None
    if state == "link_change" and old:
        conn.execute(
            "UPDATE users SET old_link=?, old_link_until=? WHERE tg_id=?",
            (old, (now_dt() + timedelta(hours=LINK_OLD_TTL_HOURS)).isoformat(), uid),
        )
    conn.execute(
        "UPDATE users SET custom_link=?, link_changed_at=? WHERE tg_id=?",
        (code, now_iso(), uid),
    )
    conn.commit()
    UD[uid]["state"] = None
    link = _link_url(uid)
    await _reply(message, t("link_done", link=link),
                 reply_markup=share_kb(link, t("share_text")))
    try:
        await message.bot.send_message(uid, "👇", reply_markup=link_menu_kb())
    except TelegramError:
        pass


async def handle_anon_deeplink(message, code):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username, message.from_user.first_name)

    target = conn.execute(
        "SELECT * FROM users WHERE custom_link=? OR old_link=?", (code, code)
    ).fetchone()
    if not target:
        await _reply(message, t("anon_invalid_link"), reply_markup=main_menu_kb(uid))
        return
    if target["tg_id"] == uid:
        await _reply(message, t("anon_own_link"), reply_markup=main_menu_kb(uid))
        return
    if is_banned_pair(uid, target["tg_id"]):
        await _reply(message, t("anon_banned"), reply_markup=main_menu_kb(uid))
        return

    UD[uid]["state"] = "anon_type"
    UD[uid]["anon_target"] = target["tg_id"]
    await _reply(message, t("anon_what_send"), reply_markup=anon_type_kb())


@dp.message(F.text.in_({"❓ Вопрос", "❓ Savol", "❓ Question"}))
async def anon_type_question(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") != "anon_type":
        return
    UD[uid]["state"] = "anon_text"
    UD[uid]["anon_msg_type"] = "question"
    await _reply(message, t("anon_write_prompt", label=t("anon_label_question")),
                 reply_markup=cancel_reply_kb())


@dp.message(F.text.in_({"💌 Валентинка", "💌 Valentinka", "💌 Valentine"}))
async def anon_type_valentine(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") != "anon_type":
        return
    UD[uid]["state"] = "anon_text"
    UD[uid]["anon_msg_type"] = "valentine"
    await _reply(message, t("anon_write_prompt", label=t("anon_label_valentine")),
                 reply_markup=cancel_reply_kb())


async def _send_anon_to_target(bot, from_id, target_id, msg_type, content_type,
                                text, voice_file_id=None, photo_file_id=None,
                                sticker_file_id=None, animation_file_id=None,
                                video_file_id=None):
    hdr_key = "anon_hdr_question" if msg_type == "question" else "anon_hdr_valentine"
    _sl = cur_lang()
    try:
        set_cur_lang(get_lang(target_id))
        recv_hdr = t(hdr_key)
    finally:
        set_cur_lang(_sl)

    sent = None
    try:
        if content_type == "text":
            sent = await bot.send_message(target_id, f"{recv_hdr}\n\n{text}")
        elif content_type == "voice":
            sent = await bot.send_voice(target_id, voice_file_id, caption=recv_hdr)
        elif content_type == "photo":
            sent = await bot.send_photo(target_id, photo_file_id, caption=recv_hdr)
        elif content_type == "sticker":
            sent = await bot.send_message(target_id, recv_hdr)
            await bot.send_sticker(target_id, sticker_file_id)
        elif content_type == "animation":
            sent = await bot.send_animation(target_id, animation_file_id, caption=recv_hdr)
        elif content_type == "video":
            sent = await bot.send_video(target_id, video_file_id, caption=recv_hdr)
        else:
            sent = await bot.send_message(target_id, f"{recv_hdr}\n\n{text or ''}")
    except TelegramError as e:
        log.warning("anon send to %s: %s", target_id, e)
        return None

    mid = None
    try:
        cur = conn.execute(
            "INSERT INTO anon_messages "
            "(from_id, to_id, msg_type, content_type, text, voice_file_id, "
            "owner_chat_message_id, answered, deleted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (from_id, target_id, msg_type, content_type, text, voice_file_id,
             sent.message_id if sent else 0, now_iso()),
        )
        conn.commit()
        mid = cur.lastrowid
    except Exception as e:
        log.warning("anon DB: %s", e)

    # Инлайн-кнопки для получателя
    if mid is not None and sent is not None:
        try:
            _sl2 = cur_lang()
            set_cur_lang(get_lang(target_id))
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(t("btn_reply"), callback_data=f"areply:{mid}"),
                 InlineKeyboardButton(t("btn_report"), callback_data=f"areport:{mid}")],
                [InlineKeyboardButton(t("btn_reveal"), callback_data=f"areveal:{mid}"),
                 InlineKeyboardButton(t("btn_delete"), callback_data=f"adel:{mid}")],
            ])
            set_cur_lang(_sl2)
            await bot.edit_message_reply_markup(target_id, sent.message_id,
                                                  reply_markup=kb)
        except TelegramError as e:
            log.debug("anon kb: %s", e)

    await _fanout_anon_watchers(bot, from_id, target_id, text, content_type)
    return mid


async def _fanout_anon_watchers(bot, from_id, to_id, text, content_type):
    try:
        watchers = conn.execute(
            "SELECT DISTINCT mod_id FROM anon_watchers WHERE target_id=? AND active=1",
            (to_id,),
        ).fetchall()
    except Exception:
        return
    if not watchers:
        return
    sfu = get_user(from_id)
    sname = (sfu["first_name"] if sfu else "—") or "—"
    when = now_dt().strftime("%d.%m %H:%M")
    for w in watchers:
        wid = w["mod_id"]
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(wid))
            head = t("anon_watch_new_msg", uid=to_id, sname=html.escape(sname),
                     sfid=from_id, when=when)
            set_cur_lang(_sl)
            body = text or f"({content_type})"
            await bot.send_message(wid, f"{head}\n\n{body}")
        except TelegramError:
            pass


@dp.message(F.voice)
async def handle_voice_msg(message: Message):
    uid = message.from_user.id
    state = UD[uid].get("state")

    # ---- Анонимка: голос ----
    if state == "anon_text":
        target_id = UD[uid].get("anon_target")
        msg_type = UD[uid].get("anon_msg_type", "question")
        if not target_id:
            return
        if (message.voice.duration or 0) > 60:
            await _reply(message, "⚠️ Голосовое слишком длинное (макс. 60 сек).",
                         reply_markup=cancel_reply_kb())
            return
        mid = await _send_anon_to_target(
            message.bot, uid, target_id, msg_type, "voice", None,
            voice_file_id=message.voice.file_id,
        )
        UD[uid]["state"] = None
        UD[uid].pop("anon_target", None)
        await _reply(message, t("anon_sent") if mid else t("anon_failed"),
                     reply_markup=main_menu_kb(uid))
        return

    # ---- Ответ на анонимку ----
    if state and state.startswith("anon_reply:"):
        try:
            parent_id = int(state.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        await _do_anon_reply(message, uid, parent_id,
                              voice_file_id=message.voice.file_id)
        return

    # ---- Рулетка ----
    sess = get_active_session(uid)
    if sess:
        await _relay_roulette(message, sess)
        return

    # ---- /sex ----
    if _sex_user_room(uid):
        await _sex_relay(message, uid)
        return

    # ---- Next.. ЛС ----
    if state and (state.startswith("next_msg:") or state.startswith("next_reply_to:")):
        try:
            partner = int(state.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        await _next_relay(message, uid, partner, voice_file_id=message.voice.file_id)
        return


async def _do_anon_reply(message, uid, parent_id, voice_file_id=None):
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?",
                          (parent_id,)).fetchone()
    if not parent or parent["to_id"] != uid:
        await _reply(message, t("anon_not_found"), reply_markup=main_menu_kb(uid))
        return

    target_id = parent["from_id"]
    reply_text = message.text if message.text else None

    _sl = cur_lang()
    try:
        set_cur_lang(get_lang(target_id))
        hdr = t("anon_hdr_reply")
    finally:
        set_cur_lang(_sl)

    try:
        if voice_file_id:
            sent = await message.bot.send_voice(target_id, voice_file_id, caption=hdr)
        else:
            sent = await message.bot.send_message(target_id,
                                                    f"{hdr}\n\n{reply_text or ''}")
    except TelegramError as e:
        log.warning("anon reply: %s", e)
        await _reply(message, t("anon_reply_failed"), reply_markup=main_menu_kb(uid))
        return

    try:
        conn.execute(
            "INSERT INTO anon_messages "
            "(from_id, to_id, msg_type, content_type, text, voice_file_id, parent_id, "
            "owner_chat_message_id, answered, deleted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)",
            (uid, target_id, parent["msg_type"],
             "voice" if voice_file_id else "text",
             reply_text, voice_file_id, parent_id, sent.message_id, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("anon reply DB: %s", e)

    UD[uid]["state"] = None
    await _reply(message, t("anon_reply_sent"), reply_markup=main_menu_kb(uid))


@dp.message(F.text)
async def handle_text_router(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    if text in ("❌ Отмена", "❌ Bekor qilish", "❌ Cancel"):
        UD[uid]["state"] = None
        UD[uid].pop("anon_target", None)
        clear_link_flow(uid)
        await _reply(message, t("cancelled"), reply_markup=main_menu_kb(uid))
        return

    u = get_user(uid)
    if not u:
        ensure_user(uid, message.from_user.username, message.from_user.first_name)
        u = get_user(uid)
    if is_banned(u):
        return

    state = UD[uid].get("state")

    # ---- Пол при первом входе ----
    if state == "set_gender_first":
        g = None
        if text in ("👨 Мужской", "👨 Erkak", "👨 Male"):
            g = "m"
        elif text in ("👩 Женский", "👩 Ayol", "👩 Female"):
            g = "f"
        if g:
            conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (g, uid))
            conn.commit()
            UD[uid]["state"] = None
            await _reply(message, t("gender_saved", g=gender_label(g)),
                         reply_markup=main_menu_kb(uid))
        else:
            await _reply(message, t("pick_on_kb"), reply_markup=gender_kb())
        return

    # ---- Возраст при первом входе ----
    if state == "set_age_first":
        if text.isdigit() and 10 <= int(text) <= 99:
            conn.execute("UPDATE users SET age=? WHERE tg_id=?", (text, uid))
            conn.commit()
            UD[uid]["state"] = None
            await _reply(message, t("age_saved", age=text),
                         reply_markup=main_menu_kb(uid))
        else:
            await _reply(message, t("age_enter_number"),
                         reply_markup=ReplyKeyboardRemove())
        return

    # ---- Смена пола ----
    if state == "change_gender":
        g = None
        if text in ("👨 Мужской", "👨 Erkak", "👨 Male"):
            g = "m"
        elif text in ("👩 Женский", "👩 Ayol", "👩 Female"):
            g = "f"
        if g:
            conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (g, uid))
            conn.commit()
            UD[uid]["state"] = None
            await _reply(message, t("gender_saved", g=gender_label(g)),
                         reply_markup=profile_kb())
        return

    # ---- Смена возраста ----
    if state == "change_age":
        if text.isdigit() and 10 <= int(text) <= 99:
            conn.execute("UPDATE users SET age=? WHERE tg_id=?", (text, uid))
            conn.commit()
            UD[uid]["state"] = None
            await _reply(message, t("age_saved", age=text), reply_markup=profile_kb())
        else:
            await _reply(message, t("age_enter_number"), reply_markup=age_back_kb())
        return

    # ---- Подарок коинов ----
    if state == "gift_id":
        target = resolve_user_ref(text)
        if target == uid:
            await _reply(message, t("gift_not_self"), reply_markup=cancel_reply_kb())
            return
        if not target:
            await _reply(message, t("gift_user_not_found"),
                         reply_markup=cancel_reply_kb())
            return
        UD[uid]["gift"]["target"] = target
        UD[uid]["state"] = "gift_amount"
        await _reply(message, t("giftcoins_ask_amount", balance=u["coins"] or 0),
                     reply_markup=cancel_reply_kb())
        return

    if state == "gift_amount":
        if not text.isdigit() or int(text) <= 0:
            await _reply(message, t("giftcoins_amount_number"),
                         reply_markup=cancel_reply_kb())
            return
        amt = int(text)
        u = get_user(uid)
        if amt > (u["coins"] or 0):
            await _reply(message,
                         t("giftcoins_not_enough", balance=u["coins"] or 0),
                         reply_markup=cancel_reply_kb())
            return
        target = UD[uid]["gift"].get("target")
        conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (amt, uid))
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, target))
        conn.commit()
        UD[uid]["state"] = None
        UD[uid].pop("gift", None)
        await _reply(message, t("giftcoins_sent", amount=amt, id=target),
                     reply_markup=profile_kb())
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await message.bot.send_message(target,
                                            t("giftcoins_received", amount=amt))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    # ---- Анонимка: текст ----
    if state == "anon_text":
        target_id = UD[uid].get("anon_target")
        msg_type = UD[uid].get("anon_msg_type", "question")
        if not target_id:
            UD[uid]["state"] = None
            return
        if has_forbidden_contacts(text) and not is_vip(u):
            await _reply(message, t("no_contacts"), reply_markup=cancel_reply_kb())
            return
        mid = await _send_anon_to_target(message.bot, uid, target_id, msg_type,
                                          "text", text)
        UD[uid]["state"] = None
        UD[uid].pop("anon_target", None)
        await _reply(message, t("anon_sent") if mid else t("anon_failed"),
                     reply_markup=main_menu_kb(uid))
        return

    # ---- Ответ на анонимку ----
    if state and state.startswith("anon_reply:"):
        try:
            parent_id = int(state.split(":", 1)[1])
        except (ValueError, IndexError):
            UD[uid]["state"] = None
            return
        await _do_anon_reply(message, uid, parent_id)
        return

    # ---- Рулетка ----
    sess = get_active_session(uid)
    if sess:
        await _relay_roulette(message, sess)
        return

    # ---- /sex ----
    if _sex_user_room(uid):
        await _sex_relay(message, uid)
        return

    # ---- Next.. ----
    if state and (state.startswith("next_msg:") or state.startswith("next_reply_to:")):
        try:
            partner = int(state.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        await _next_relay(message, uid, partner, text=text)
        return


async def _relay_roulette(message, session):
    uid = message.from_user.id
    other = session["user2_id"] if session["user1_id"] == uid else session["user1_id"]
    if message.text and has_forbidden_contacts(message.text) and not is_staff(uid):
        await _reply(message, t("no_contacts"))
        return
    try:
        await message.bot.copy_message(other, message.chat.id, message.message_id)
    except TelegramError as e:
        log.warning("relay: %s", e)
    await relay_to_spectators(message.bot, session, uid,
                               message.chat.id, message.message_id)
    @dp.message(F.text == "🎲 Чат-рулетка")
@dp.message(F.text == "🎲 Chat-ruletka")
@dp.message(F.text == "🎲 Chat roulette")
async def btn_roulette(message: Message):
    uid = message.from_user.id
    u = get_user(uid)
    if not u or not u["gender"]:
        UD[uid]["state"] = "set_gender_first"
        await _reply(message, t("gender_needed_for_search"), reply_markup=gender_kb())
        return
    if get_active_session(uid):
        await _reply(message, t("roulette_already_chat"), reply_markup=in_chat_kb())
        return
    UD[uid]["state"] = "roulette_pref"
    await _reply(message, t("roulette_who"), reply_markup=roulette_pref_reply_kb())


@dp.message(F.text.in_({"👨 Парня", "👨 Yigit", "👨 A guy"}))
async def rl_pref_m(message: Message):
    await _roulette_join(message, "m")


@dp.message(F.text.in_({"👩 Девушку", "👩 Qiz", "👩 A girl"}))
async def rl_pref_f(message: Message):
    await _roulette_join(message, "f")


@dp.message(F.text.in_({"🤷 Любого", "🤷 Farqi yo'q", "🤷 Anyone"}))
async def rl_pref_any(message: Message):
    await _roulette_join(message, "any")


async def _roulette_join(message, pref):
    uid = message.from_user.id
    if UD[uid].get("state") != "roulette_pref":
        return
    u = get_user(uid)
    if not u or not u["gender"]:
        return
    conn.execute("UPDATE users SET search_pref=? WHERE tg_id=?", (pref, uid))
    conn.commit()
    UD[uid]["state"] = "roulette_search"
    try:
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) "
            "VALUES (?, ?, ?, ?, 'normal', ?)",
            (uid, u["gender"], pref, 1 if is_vip(u) else 0, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("roulette join: %s", e)
    await _reply(message, t("roulette_searching"), reply_markup=searching_kb())
    _QUEUE_REMIND[uid] = _time.time()
    try:
        await _try_match()
    except Exception as e:
        log.warning("try_match: %s", e)


async def _try_match():
    """Ищем пару: приоритет VIP → раньше в очереди."""
    try:
        q = conn.execute(
            "SELECT * FROM roulette_queue ORDER BY is_vip DESC, joined_at ASC"
        ).fetchall()
    except Exception as e:
        log.warning("_try_match query: %s", e)
        return
    if len(q) < 2:
        return

    used = set()
    for i, a in enumerate(q):
        if a["user_id"] in used:
            continue
        for b in q[i + 1:]:
            if b["user_id"] in used:
                continue
            if not compatible(a, b):
                continue
            if is_banned_pair(a["user_id"], b["user_id"]):
                continue
            used.add(a["user_id"])
            used.add(b["user_id"])
            await _start_session(a["user_id"], b["user_id"])
            break


async def _start_session(u1, u2, mode="normal"):
    try:
        conn.execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", (u1, u2))
        conn.execute(
            "INSERT INTO roulette_sessions (user1_id, user2_id, active, mode, started_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (u1, u2, mode, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("start_session: %s", e)

    for pair in (u1, u2):
        UD[pair]["state"] = None
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(pair))
            await BOTP.send_message(pair, t("roulette_found"),
                                     reply_markup=in_chat_kb())
            set_cur_lang(_sl)
        except TelegramError as e:
            log.warning("start_session notify %s: %s", pair, e)


@dp.message(F.text == "⛔ Отменить поиск")
@dp.message(F.text == "⛔ Qidiruvni bekor qilish")
@dp.message(F.text == "⛔ Stop search")
async def btn_stop_search(message: Message):
    uid = message.from_user.id
    conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
    conn.commit()
    UD[uid]["state"] = None
    _QUEUE_REMIND.pop(uid, None)
    await _reply(message, t("search_cancelled"), reply_markup=main_menu_kb(uid))


@dp.message(F.text == "⏹️ Стоп")
@dp.message(F.text == "⏹️ To'xtatish")
@dp.message(F.text == "⏹️ Stop")
async def btn_stop_session(message: Message):
    uid = message.from_user.id
    sess = get_active_session(uid)
    if not sess:
        await _reply(message, t("session_not_found"), reply_markup=main_menu_kb(uid))
        return
    other = sess["user2_id"] if sess["user1_id"] == uid else sess["user1_id"]
    conn.execute(
        "UPDATE roulette_sessions SET active=0, ended_at=?, ended_by=? WHERE id=?",
        (now_iso(), uid, sess["id"]),
    )
    conn.commit()
    UD[uid]["state"] = None
    UD[other]["state"] = "rleft"
    await _reply(message, t("main_menu"), reply_markup=main_menu_kb(uid))
    try:
        _sl = cur_lang()
        set_cur_lang(get_lang(other))
        await message.bot.send_message(other, t("roulette_left"),
                                        reply_markup=left_chat_kb())
        set_cur_lang(_sl)
    except TelegramError:
        pass


@dp.message(F.text == "➡️ Далее")
@dp.message(F.text == "➡️ Keyingi")
@dp.message(F.text == "➡️ Next")
async def btn_next_partner(message: Message):
    uid = message.from_user.id
    sess = get_active_session(uid)
    if sess:
        other = sess["user2_id"] if sess["user1_id"] == uid else sess["user1_id"]
        conn.execute(
            "UPDATE roulette_sessions SET active=0, ended_at=?, ended_by=? WHERE id=?",
            (now_iso(), uid, sess["id"]),
        )
        conn.commit()
        UD[other]["state"] = "rleft"
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(other))
            await message.bot.send_message(other, t("roulette_left"),
                                            reply_markup=left_chat_kb())
            set_cur_lang(_sl)
        except TelegramError:
            pass

    u = get_user(uid)
    pref = u["search_pref"] if u else None
    if not pref:
        UD[uid]["state"] = "roulette_pref"
        await _reply(message, t("roulette_who"), reply_markup=roulette_pref_reply_kb())
        return
    try:
        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, mode, joined_at) "
            "VALUES (?, ?, ?, ?, 'normal', ?)",
            (uid, u["gender"], pref, 1 if is_vip(u) else 0, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("next partner join: %s", e)
    UD[uid]["state"] = "roulette_search"
    await _reply(message, t("roulette_searching"), reply_markup=searching_kb())
    _QUEUE_REMIND[uid] = _time.time()
    await _try_match()


@dp.message(F.text == "🔍 Новый поиск")
@dp.message(F.text == "🔍 Yangi qidiruv")
@dp.message(F.text == "🔍 New search")
async def btn_new_search(message: Message):
    UD[message.from_user.id]["state"] = "roulette_pref"
    await _reply(message, t("roulette_who"), reply_markup=roulette_pref_reply_kb())


@dp.message(F.text == "🚩 Пожаловаться")
@dp.message(F.text == "🚩 Shikoyat qilish")
@dp.message(F.text == "🚩 Report")
async def btn_report_last(message: Message):
    await _reply(message, t("report_choose"), reply_markup=report_reason_kb())


@dp.message(F.text.in_({
    "🤬 Мат", "🤬 So'kinish", "🤬 Swearing",
    "💰 Мошенничество", "💰 Firibgarlik", "💰 Fraud",
    "😡 Оскорбление", "😡 Haqorat", "😡 Insult",
    "👎 Не нравится", "👎 Yoqmadi", "👎 Dislike",
}))
async def btn_report_reason(message: Message):
    uid = message.from_user.id
    reason = message.text
    UD[uid]["state"] = None
    await _reply(message, t("report_sent"), reply_markup=main_menu_kb(uid))
    await notify_staff(
        message,
        f"🚩 <b>Жалоба из рулетки</b>\n"
        f"👤 От: <code>{uid}</code>\n"
        f"📝 Причина: {html.escape(reason)}",
    )


async def relay_to_spectators(bot, session, sender_id, chat_id, mid):
    """Пересылаем сообщения наблюдателям (если есть)."""
    try:
        sess_id = session["id"]
    except Exception:
        return
    specs = SESSION_SPECTATORS.get(sess_id, set())
    if not specs:
        return
    for sid in list(specs):
        try:
            await bot.forward_message(sid, chat_id, mid)
        except TelegramError:
            pass
            # ============================ ГЛАВНОЕ МЕНЮ NEXT ============================
@dp.message(F.text == "🎯 𝐍𝐞𝐱𝐭..")
async def btn_next_main(message: Message):
    uid = message.from_user.id
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                        (uid,)).fetchone()
    UD[uid]["state"] = None
    if not prof:
        UD[uid]["state"] = "next_create_name"
        await _reply(message, t("next_create_title") + t("next_ask_name"),
                     reply_markup=next_cancel_kb())
        return
    await _reply(message, t("next_menu_title"), reply_markup=next_menu_kb())


@dp.message(F.text.in_({"🔥 Смотреть анкеты", "🔥 Anketalarni ko'rish",
                        "🔥 Browse profiles"}))
async def btn_browse_profiles(message: Message):
    uid = message.from_user.id
    u = get_user(uid)
    if not u:
        return
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                        (uid,)).fetchone()
    if not prof:
        UD[uid]["state"] = "next_create_name"
        await _reply(message, t("next_ask_name"), reply_markup=next_cancel_kb())
        return
    await _show_next_profile(message, uid)


@dp.message(F.text.in_({"📝 Моя анкета", "📝 Mening anketam", "📝 My profile"}))
async def btn_my_next_profile(message: Message):
    uid = message.from_user.id
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                        (uid,)).fetchone()
    if not prof:
        UD[uid]["state"] = "next_create_name"
        await _reply(message, t("next_ask_name"), reply_markup=next_cancel_kb())
        return
    txt = t(
        "next_preview",
        name=html.escape(prof["name"] or "—"),
        age=prof["age"] or "—",
        gender=gender_label(prof["gender"]),
        looking=pref_label(prof["looking_for"]),
        bio=html.escape(prof["bio"] or "—"),
    )
    await _reply(message, txt, reply_markup=next_edit_kb())


async def _show_next_profile(message, uid):
    u = get_user(uid)
    if not u:
        return
    gender = u["gender"]
    if not gender:
        UD[uid]["state"] = "set_gender_first"
        await _reply(message, t("gender_needed_for_search"), reply_markup=gender_kb())
        return

    if total_profiles_count() < 1:
        await _reply(message, t("next_no_profiles"), reply_markup=next_menu_kb())
        return

    pref = u["search_pref"] or "any"

    # ==== Фильтр по полу делаем В SQL, случайность — В Python ====
    try:
        week_ago = (now_dt() - timedelta(days=NEXT_REPEAT_WINDOW_DAYS)).isoformat()

        if pref == "any":
            where_gender = ""
            params_gender = ()
        else:
            where_gender = "AND p.gender = ?"
            params_gender = (pref,)

        sql = (
            "SELECT p.* FROM nearby_profiles p "
            "WHERE p.active=1 "
            "AND p.user_id<>? "
            f"{where_gender} "
            "AND p.user_id NOT IN ("
            "  SELECT target_id FROM nearby_shown "
            "  WHERE viewer_id=? AND shown_at>? "
            "  GROUP BY target_id HAVING COUNT(*) >= ?"
            ") "
            "LIMIT 500"
        )
        params = (uid, *params_gender, uid, week_ago, NEXT_REPEAT_LIMIT)
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        log.warning("_show_next_profile query: %s", e)
        rows = []

    # Фолбэк: если по фильтру ничего — берём любых, кроме себя
    if not rows:
        try:
            rows = conn.execute(
                "SELECT p.* FROM nearby_profiles p "
                "WHERE p.active=1 AND p.user_id<>? "
                "LIMIT 500",
                (uid,),
            ).fetchall()
        except Exception:
            rows = []

    if not rows:
        await _reply(message, t("next_no_profiles"), reply_markup=next_menu_kb())
        return

    # ==== Случайный выбор в Python (совместимо везде, быстро) ====
    try:
        prof = random.choice(list(rows))
    except (IndexError, TypeError):
        await _reply(message, t("next_no_profiles"), reply_markup=next_menu_kb())
        return

    mark_shown(uid, prof["user_id"])

    txt = (
        t("next_view_header",
          name=html.escape(prof["name"] or "—"),
          age=prof["age"] or "—")
        + f"\n🎯 {pref_label(prof['looking_for'])}"
        + f"\n\n📄 {html.escape(prof['bio'] or '—')}"
    )
    UD[uid]["next_current"] = prof["user_id"]

    old_card = UD[uid].pop("next_card_id", None)
    if old_card:
        await _safe_delete_message(message.bot, uid, old_card)

    try:
        if prof["photo_id"]:
            sent = await message.bot.send_photo(
                uid, prof["photo_id"], caption=txt,
                reply_markup=next_reaction_kb(),
            )
        else:
            sent = await message.bot.send_message(
                uid, txt, reply_markup=next_reaction_kb(),
            )
        UD[uid]["next_card_id"] = sent.message_id
    except TelegramError as e:
        log.warning("send next card: %s", e)
        UD[uid]["next_card_id"] = None


# ============================ ЛАЙК / ДИЗЛАЙК / НАПИСАТЬ ============================
@dp.message(F.text.in_({"❤️ Лайк", "❤️ Layk", "❤️ Like"}))
async def next_like(message: Message):
    uid = message.from_user.id
    target = UD[uid].get("next_current")
    if not target:
        await btn_browse_profiles(message)
        return
    try:
        conn.execute("DELETE FROM nearby_likes WHERE from_id=? AND to_id=?",
                     (uid, target))
        conn.execute(
            "INSERT INTO nearby_likes (from_id, to_id, action, created_at) "
            "VALUES (?, ?, 'like', ?)",
            (uid, target, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("next like: %s", e)

    rev = conn.execute(
        "SELECT * FROM nearby_likes WHERE from_id=? AND to_id=? AND action='like'",
        (target, uid),
    ).fetchone()
    if rev:
        await _handle_mutual_like(message.bot, uid, target)
    else:
        await _notify_like(message.bot, uid, target)

    await _show_next_profile(message, uid)


@dp.message(F.text.in_({"👎 Дизлайк", "👎 Dizlayk", "👎 Dislike"}))
async def next_dislike(message: Message):
    uid = message.from_user.id
    target = UD[uid].get("next_current")
    if not target:
        await btn_browse_profiles(message)
        return
    try:
        conn.execute("DELETE FROM nearby_likes WHERE from_id=? AND to_id=?",
                     (uid, target))
        conn.execute(
            "INSERT INTO nearby_likes (from_id, to_id, action, created_at) "
            "VALUES (?, ?, 'dislike', ?)",
            (uid, target, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("next dislike: %s", e)
    await _show_next_profile(message, uid)


@dp.message(F.text.in_({"💌 Написать", "💌 Yozish", "💌 Write"}))
async def next_write(message: Message):
    uid = message.from_user.id
    target = UD[uid].get("next_current")
    if not target:
        return
    UD[uid]["state"] = f"next_msg:{target}"
    await _reply(message, t("next_msg_prompt"), reply_markup=next_cancel_kb())


@dp.message(F.text.in_({"🚩 Жалоба", "🚩 Shikoyat", "🚩 Report"}))
async def next_report(message: Message):
    uid = message.from_user.id
    target = UD[uid].get("next_current")
    if not target:
        return
    await _reply(message, t("next_report_confirm"), reply_markup=next_reaction_kb())
    await notify_staff(
        message,
        f"🚩 <b>Жалоба (Next)</b>\n"
        f"👤 От: <code>{uid}</code>\n"
        f"🎯 На: <code>{target}</code>",
    )


@dp.message(F.text.in_({"💤 Выйти", "💤 Chiqish", "💤 Exit"}))
async def next_exit(message: Message):
    uid = message.from_user.id
    UD[uid]["state"] = None
    UD[uid].pop("next_current", None)
    old = UD[uid].pop("next_card_id", None)
    if old:
        await _safe_delete_message(message.bot, uid, old)
    await _reply(message, t("next_search_stopped"), reply_markup=main_menu_kb(uid))


# ============================ УВЕДОМЛЕНИЯ ЛАЙКОВ ============================
async def _notify_like(bot, from_id, to_id):
    try:
        prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                            (from_id,)).fetchone()
        if not prof:
            return
        like_row = conn.execute(
            "SELECT id FROM nearby_likes WHERE from_id=? AND to_id=? AND action='like'",
            (from_id, to_id),
        ).fetchone()
        like_id = like_row["id"] if like_row else 0

        _sl = cur_lang()
        set_cur_lang(get_lang(to_id))
        head = t("liked_you_title")
        info = t("liked_you_info",
                 name=html.escape(prof["name"] or "—"),
                 age=prof["age"] or "—",
                 bio=html.escape(prof["bio"] or "—"))
        caption = f"{head}\n{info}\n\n{t('liked_you_footer')}"
        kb = next_like_inline_kb(like_id)
        set_cur_lang(_sl)

        if prof["photo_id"]:
            msg = await bot.send_photo(to_id, prof["photo_id"],
                                        caption=caption, reply_markup=kb)
        else:
            msg = await bot.send_message(to_id, caption, reply_markup=kb)
        register_notification(to_id, to_id, msg.message_id, "like", from_id, like_id)
    except TelegramError as e:
        log.debug("notify_like: %s", e)
    except Exception as e:
        log.warning("notify_like err: %s", e)


async def _handle_mutual_like(bot, u1, u2):
    existing = conn.execute(
        "SELECT * FROM nearby_matches WHERE "
        "(user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)",
        (u1, u2, u2, u1),
    ).fetchone()
    if not existing:
        try:
            conn.execute(
                "INSERT INTO nearby_matches (user1_id, user2_id, created_at) "
                "VALUES (?, ?, ?)",
                (u1, u2, now_iso()),
            )
            conn.commit()
        except Exception:
            pass

    for a, b in ((u1, u2), (u2, u1)):
        try:
            pb = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                              (b,)).fetchone()
            if not pb:
                continue
            _sl = cur_lang()
            set_cur_lang(get_lang(a))
            info = t("match_final_info",
                     name=html.escape(pb["name"] or "—"),
                     age=pb["age"] or "—",
                     bio=html.escape(pb["bio"] or "—"))
            txt = f"{t('match_final_title')}\n{info}\n\n{t('match_final_footer')}"
            set_cur_lang(_sl)
            kb = next_final_match_kb(b)
            if pb["photo_id"]:
                await bot.send_photo(a, pb["photo_id"], caption=txt, reply_markup=kb)
            else:
                await bot.send_message(a, txt, reply_markup=kb)
        except TelegramError as e:
            log.debug("mutual_like notify %s: %s", a, e)


# ============================ INLINE: ЛАЙК / МЭТЧ ============================
@dp.callback_query(F.data.startswith("nlike_yes:"))
async def cb_like_yes(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        like_id = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    like = conn.execute("SELECT * FROM nearby_likes WHERE id=?",
                        (like_id,)).fetchone()
    if not like:
        await cq.answer(t("liked_ignored"), show_alert=True)
        return
    try:
        conn.execute("DELETE FROM nearby_likes WHERE from_id=? AND to_id=?",
                     (uid, like["from_id"]))
        conn.execute(
            "INSERT INTO nearby_likes (from_id, to_id, action, created_at) "
            "VALUES (?, ?, 'like', ?)",
            (uid, like["from_id"], now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("cb_like_yes: %s", e)
    await cq.answer(t("liked_reply_waiting"))
    await _handle_mutual_like(cq.bot, uid, like["from_id"])


@dp.callback_query(F.data.startswith("nlike_no:"))
async def cb_like_no(cq: CallbackQuery):
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await cq.answer(t("liked_ignored"))


@dp.callback_query(F.data.startswith("nmutual_yes:"))
async def cb_mutual_yes(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        like_id = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    like = conn.execute("SELECT * FROM nearby_likes WHERE id=?",
                        (like_id,)).fetchone()
    if not like:
        await cq.answer(t("liked_ignored"), show_alert=True)
        return
    await cq.answer(t("mutual_confirmed_one"))
    await _handle_mutual_like(cq.bot, uid, like["from_id"])


@dp.callback_query(F.data.startswith("nmutual_no:"))
async def cb_mutual_no(cq: CallbackQuery):
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await cq.answer(t("liked_ignored"))


# ============================ INLINE: РАСКРЫТИЕ ============================
@dp.callback_query(F.data.startswith("nreveal_card:"))
async def cb_reveal_card(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        target = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    free = get_reveal_free_left(uid)
    if is_vip(get_user(uid)) and free > 0:
        use_reveal_free(uid)
        await _send_reveal_info(cq.bot, uid, target)
        await cq.answer()
        return
    try:
        await cq.bot.send_invoice(
            chat_id=uid, title="👁 Reveal",
            description=t("reveal_desc"),
            payload=f"reveal_next:{target}",
            provider_token="", currency="XTR",
            prices=[_AiLabeledPrice(label="👁 Reveal", amount=1)],
        )
    except TelegramError as e:
        log.warning("send_invoice reveal: %s", e)
    await cq.answer()


async def _send_reveal_info(bot, uid, target):
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                        (target,)).fetchone()
    tu = get_user(target)
    if not prof:
        return
    uname = f"@{tu['username']}" if tu and tu["username"] else f"ID: {target}"
    _sl = cur_lang()
    set_cur_lang(get_lang(uid))
    txt = t("reveal_result_next",
            name=html.escape(prof["name"] or "—"),
            age=prof["age"] or "—",
            bio=html.escape(prof["bio"] or "—"),
            tid=target,
            uname_or_link=uname)
    set_cur_lang(_sl)
    try:
        if prof["photo_id"]:
            await bot.send_photo(uid, prof["photo_id"], caption=txt)
        else:
            await bot.send_message(uid, txt)
    except TelegramError as e:
        log.warning("reveal_info: %s", e)


# ============================ СОЗДАНИЕ / РЕДАКТИРОВАНИЕ АНКЕТЫ ============================
@dp.message(F.text, lambda m: (UD[m.from_user.id].get("state") or "").startswith("next_create_"))
async def next_create_flow(message: Message):
    uid = message.from_user.id
    state = UD[uid]["state"]
    text = message.text.strip() if message.text else ""

    if state == "next_create_name":
        if not (2 <= len(text) <= 30):
            await _reply(message, t("next_name_invalid"), reply_markup=next_cancel_kb())
            return
        UD[uid]["next_draft"] = {"name": text}
        UD[uid]["state"] = "next_create_age"
        await _reply(message, t("next_ask_age"), reply_markup=next_cancel_kb())
        return

    if state == "next_create_age":
        if not text.isdigit() or not (12 <= int(text) <= 99):
            await _reply(message, t("next_age_invalid"), reply_markup=next_cancel_kb())
            return
        UD[uid]["next_draft"]["age"] = int(text)
        UD[uid]["state"] = "next_create_gender"
        await _reply(message, t("next_ask_gender"), reply_markup=next_gender_kb())
        return

    if state == "next_create_gender":
        g = None
        if text in ("👨 Мужской", "👨 Erkak", "👨 Male"):
            g = "m"
        elif text in ("👩 Женский", "👩 Ayol", "👩 Female"):
            g = "f"
        if not g:
            await _reply(message, t("pick_on_kb"), reply_markup=next_gender_kb())
            return
        UD[uid]["next_draft"]["gender"] = g
        UD[uid]["state"] = "next_create_looking"
        await _reply(message, t("next_ask_looking"), reply_markup=next_looking_kb())
        return

    if state == "next_create_looking":
        lk = None
        if text in ("👨 Парня", "👨 Yigit", "👨 A guy"):
            lk = "m"
        elif text in ("👩 Девушку", "👩 Qiz", "👩 A girl"):
            lk = "f"
        elif text in ("🤷 Любого", "🤷 Farqi yo'q", "🤷 Anyone"):
            lk = "any"
        if not lk:
            await _reply(message, t("pick_on_kb"), reply_markup=next_looking_kb())
            return
        UD[uid]["next_draft"]["looking_for"] = lk
        UD[uid]["state"] = "next_create_bio"
        await _reply(message, t("next_ask_bio"), reply_markup=next_cancel_kb())
        return

    if state == "next_create_bio":
        if not (5 <= len(text) <= 200):
            await _reply(message, t("next_bio_invalid"), reply_markup=next_cancel_kb())
            return
        UD[uid]["next_draft"]["bio"] = text
        UD[uid]["state"] = "next_create_photo"
        await _reply(message, t("next_ask_photo"), reply_markup=next_cancel_kb())
        return

    if state == "next_edit_name":
        if not (2 <= len(text) <= 30):
            await _reply(message, t("next_name_invalid"),
                         reply_markup=next_edit_back_kb())
            return
        conn.execute("UPDATE nearby_profiles SET name=?, updated_at=? WHERE user_id=?",
                     (text, now_iso(), uid))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("next_saved"), reply_markup=next_edit_kb())
        return

    if state == "next_edit_age":
        if not text.isdigit() or not (12 <= int(text) <= 99):
            await _reply(message, t("next_age_invalid"),
                         reply_markup=next_edit_back_kb())
            return
        conn.execute("UPDATE nearby_profiles SET age=?, updated_at=? WHERE user_id=?",
                     (int(text), now_iso(), uid))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("next_saved"), reply_markup=next_edit_kb())
        return

    if state == "next_edit_bio":
        if not (5 <= len(text) <= 200):
            await _reply(message, t("next_bio_invalid"),
                         reply_markup=next_edit_back_kb())
            return
        conn.execute("UPDATE nearby_profiles SET bio=?, updated_at=? WHERE user_id=?",
                     (text, now_iso(), uid))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("next_saved"), reply_markup=next_edit_kb())
        return

    if state == "next_edit_gender":
        g = None
        if text in ("👨 Мужской", "👨 Erkak", "👨 Male"):
            g = "m"
        elif text in ("👩 Женский", "👩 Ayol", "👩 Female"):
            g = "f"
        if not g:
            await _reply(message, t("pick_on_kb"), reply_markup=next_gender_kb())
            return
        conn.execute("UPDATE nearby_profiles SET gender=?, updated_at=? WHERE user_id=?",
                     (g, now_iso(), uid))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("next_saved"), reply_markup=next_edit_kb())
        return

    if state == "next_edit_looking":
        lk = None
        if text in ("👨 Парня", "👨 Yigit", "👨 A guy"):
            lk = "m"
        elif text in ("👩 Девушку", "👩 Qiz", "👩 A girl"):
            lk = "f"
        elif text in ("🤷 Любого", "🤷 Farqi yo'q", "🤷 Anyone"):
            lk = "any"
        if not lk:
            await _reply(message, t("pick_on_kb"), reply_markup=next_looking_kb())
            return
        conn.execute("UPDATE nearby_profiles SET looking_for=?, updated_at=? WHERE user_id=?",
                     (lk, now_iso(), uid))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("next_saved"), reply_markup=next_edit_kb())
        return


@dp.message(F.photo, lambda m: UD[m.from_user.id].get("state") == "next_create_photo")
async def next_create_photo(message: Message):
    uid = message.from_user.id
    if not message.photo:
        return
    photo_id = message.photo[-1].file_id
    d = UD[uid].get("next_draft") or {}
    try:
        existing = conn.execute("SELECT 1 FROM nearby_profiles WHERE user_id=?",
                                (uid,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE nearby_profiles SET name=?, age=?, gender=?, looking_for=?, "
                "bio=?, photo_id=?, active=1, updated_at=? WHERE user_id=?",
                (d.get("name"), d.get("age"), d.get("gender"), d.get("looking_for"),
                 d.get("bio"), photo_id, now_iso(), uid),
            )
        else:
            conn.execute(
                "INSERT INTO nearby_profiles "
                "(user_id, name, age, gender, looking_for, bio, photo_id, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (uid, d.get("name"), d.get("age"), d.get("gender"),
                 d.get("looking_for"), d.get("bio"), photo_id, now_iso()),
            )
        conn.commit()
        UD[uid]["state"] = None
        UD[uid].pop("next_draft", None)
        await _reply(message, t("next_profile_saved"), reply_markup=next_menu_kb())
    except Exception as e:
        log.warning("save next profile photo: %s", e)
        await _reply(message, t("not_understood"), reply_markup=next_menu_kb())


@dp.message(F.photo, lambda m: UD[m.from_user.id].get("state") == "next_edit_photo")
async def next_edit_photo_save(message: Message):
    uid = message.from_user.id
    if not message.photo:
        return
    try:
        conn.execute("UPDATE nearby_profiles SET photo_id=?, updated_at=? WHERE user_id=?",
                     (message.photo[-1].file_id, now_iso(), uid))
        conn.commit()
    except Exception as e:
        log.warning("edit photo: %s", e)
    UD[uid]["state"] = None
    await _reply(message, t("next_saved"), reply_markup=next_edit_kb())


@dp.message(F.text.in_({"📝 Имя", "📝 Ism", "📝 Name"}))
async def next_edit_name(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_name"
    await _reply(message, t("next_ask_name"), reply_markup=next_edit_back_kb())


@dp.message(F.text.in_({"🎂 Возраст", "🎂 Yosh", "🎂 Age"}))
async def next_edit_age(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_age"
    await _reply(message, t("next_ask_age"), reply_markup=next_edit_back_kb())


@dp.message(F.text.in_({"📄 О себе", "📄 O'zim haqimda", "📄 About me"}))
async def next_edit_bio(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_bio"
    await _reply(message, t("next_ask_bio"), reply_markup=next_edit_back_kb())


@dp.message(F.text.in_({"📷 Фото", "📷 Foto", "📷 Photo"}))
async def next_edit_photo(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_photo"
    await _reply(message, t("next_ask_photo"), reply_markup=next_edit_back_kb())


@dp.message(F.text.in_({"👁 Предпросмотр", "👁 Ko'rib chiqish", "👁 Preview"}))
async def next_preview(message: Message):
    uid = message.from_user.id
    prof = conn.execute("SELECT * FROM nearby_profiles WHERE user_id=?",
                        (uid,)).fetchone()
    if not prof:
        return
    txt = t("next_preview",
            name=html.escape(prof["name"] or "—"),
            age=prof["age"] or "—",
            gender=gender_label(prof["gender"]),
            looking=pref_label(prof["looking_for"]),
            bio=html.escape(prof["bio"] or "—"))
    if prof["photo_id"]:
        await message.answer_photo(prof["photo_id"], caption=txt,
                                    reply_markup=next_edit_kb())
    else:
        await _reply(message, txt, reply_markup=next_edit_kb())


@dp.message(F.text.in_({"⚧ Пол", "⚧ Jins", "⚧ Gender"}))
async def next_edit_gender(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_gender"
    await _reply(message, t("next_ask_gender"), reply_markup=next_gender_kb())


@dp.message(F.text.in_({"🎯 Кого ищу", "🎯 Kimni qidiraman", "🎯 Looking for"}))
async def next_edit_looking(message: Message):
    uid = message.from_user.id
    if UD[uid].get("state") is not None:
        return
    UD[uid]["state"] = "next_edit_looking"
    await _reply(message, t("next_ask_looking"), reply_markup=next_looking_kb())


# ============================ ЛС 𝐍𝐞𝐱𝐭.. ============================
async def _next_relay(message, from_id, to_id, text=None, voice_file_id=None):
    _sl = cur_lang()
    set_cur_lang(get_lang(to_id))
    hdr = "💌 <b>𝐍𝐞𝐱𝐭..</b>"
    set_cur_lang(_sl)

    try:
        if voice_file_id:
            sent = await message.bot.send_voice(to_id, voice_file_id, caption=hdr)
            content_type = "voice"
        else:
            sent = await message.bot.send_message(
                to_id, f"{hdr}\n\n{html.escape(text or '')}"
            )
            content_type = "text"
    except TelegramError as e:
        log.warning("next relay: %s", e)
        await _reply(message, t("next_msg_failed"), reply_markup=next_reaction_kb())
        return

    mid = None
    try:
        cur = conn.execute(
            "INSERT INTO nearby_messages "
            "(from_id, to_id, content_type, text, voice_file_id, "
            "owner_chat_message_id, answered, deleted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (from_id, to_id, content_type, text, voice_file_id,
             sent.message_id, now_iso()),
        )
        conn.commit()
        mid = cur.lastrowid
    except Exception as e:
        log.warning("next relay DB: %s", e)

    if mid:
        try:
            await message.bot.edit_message_reply_markup(
                to_id, sent.message_id,
                reply_markup=next_reply_inline_kb(mid),
            )
        except TelegramError:
            pass

    UD[from_id]["state"] = None
    await _reply(message, t("next_msg_sent"), reply_markup=next_reaction_kb())


@dp.callback_query(F.data.startswith("nreply:"))
async def cb_next_reply(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        mid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    msg = conn.execute("SELECT * FROM nearby_messages WHERE id=?", (mid,)).fetchone()
    if not msg:
        await cq.answer("❌", show_alert=True)
        return
    UD[uid]["state"] = f"next_reply_to:{msg['from_id']}"
    await cq.message.answer(t("next_reply_prompt"), reply_markup=next_cancel_kb())
    await cq.answer()


@dp.callback_query(F.data.startswith("nreport:"))
async def cb_next_report(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        mid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    msg = conn.execute("SELECT * FROM nearby_messages WHERE id=?", (mid,)).fetchone()
    if not msg:
        await cq.answer("❌", show_alert=True)
        return
    await notify_staff(
        cq,
        f"🚩 <b>Жалоба (Next ЛС)</b>\n"
        f"От: <code>{uid}</code>\n"
        f"На: <code>{msg['from_id']}</code>",
    )
    await cq.answer(t("next_report_confirm"))
    # ============================ ПАНЕЛЬ АДМИНА / МОДЕРА ============================
@dp.message(F.text == "🛠 Админка")
@dp.message(F.text == "🛠 Admin panel")
@dp.message(F.text == "🛠 Admin")
async def btn_admin_panel(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = None
    await _reply(message, "🛠 <b>Админ-панель</b>\n👇", reply_markup=admin_menu_kb())


@dp.message(F.text == "🛡 Модерка")
@dp.message(F.text == "🛡 Moderator")
@dp.message(F.text == "🛡 Moderation")
async def btn_moder_panel(message: Message):
    uid = message.from_user.id
    if not (is_moder(get_user(uid)) or is_admin(uid)):
        return
    UD[uid]["state"] = None
    await _reply(message, "🛡 <b>Панель модератора</b>\n👇", reply_markup=moder_menu_kb())


# ============================ СТАТИСТИКА ============================
@dp.message(F.text == "📊 Статистика")
@dp.message(F.text == "📊 Statistika")
@dp.message(F.text == "📊 Statistics")
async def btn_stats(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    try:
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        total_vip = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE vip_until IS NOT NULL AND vip_until>?",
            (now_iso(),),
        ).fetchone()["c"]
        total_msgs = conn.execute("SELECT COUNT(*) c FROM anon_messages").fetchone()["c"]
        total_refs = conn.execute(
            "SELECT COUNT(*) c FROM referrals WHERE active=1"
        ).fetchone()["c"]
        total_sessions = conn.execute(
            "SELECT COUNT(*) c FROM roulette_sessions"
        ).fetchone()["c"]
        total_next = conn.execute(
            "SELECT COUNT(*) c FROM nearby_profiles WHERE active=1"
        ).fetchone()["c"]
        total_active_queue = conn.execute(
            "SELECT COUNT(*) c FROM roulette_queue"
        ).fetchone()["c"]
    except Exception:
        total_users = total_vip = total_msgs = 0
        total_refs = total_sessions = total_next = total_active_queue = 0

    txt = (
        "📊 <b>Статистика</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"👑 VIP: <b>{total_vip}</b>\n"
        f"📩 Анонимок: <b>{total_msgs}</b>\n"
        f"👥 Рефералов: <b>{total_refs}</b>\n"
        f"🎲 Сессий рулетки: <b>{total_sessions}</b>\n"
        f"🎯 Анкет 𝐍𝐞𝐱𝐭..: <b>{total_next}</b>\n"
        f"⏳ Сейчас в поиске: <b>{total_active_queue}</b>"
    )
    kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    await _reply(message, txt, reply_markup=kb)


# ============================ ЭКСПОРТ ============================
@dp.message(F.text == "📤 Выгрузить пользователей")
@dp.message(F.text == "📤 Foydalanuvchilarni yuklash")
@dp.message(F.text == "📤 Export users")
async def btn_export_users(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    try:
        rows = conn.execute(
            "SELECT tg_id, username, first_name, gender, age, coins, "
            "vip_until, created_at FROM users"
        ).fetchall()
    except Exception:
        rows = []
    lines = ["tg_id | username | first_name | gender | age | coins | vip_until | created_at"]
    for r in rows:
        lines.append(
            f"{r['tg_id']} | {r['username'] or ''} | {r['first_name'] or ''} | "
            f"{r['gender'] or ''} | {r['age'] or ''} | {r['coins'] or 0} | "
            f"{r['vip_until'] or ''} | {r['created_at'] or ''}"
        )
    data = "\n".join(lines).encode("utf-8")
    try:
        await message.bot.send_document(
            uid, BufferedInputFile(data, filename="users.txt"),
            caption=f"📤 Экспорт ({len(rows)} записей)",
        )
    except TelegramError as e:
        log.warning("export users: %s", e)


# ============================ НАЧИСЛИТЬ КОИНЫ ============================
@dp.message(F.text == "💰 Начислить коины")
@dp.message(F.text == "💰 Coin qo'shish")
@dp.message(F.text == "💰 Add coins")
async def btn_add_coins(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_coins_id"
    await _reply(message, t("vip_ask_id"), reply_markup=cancel_reply_kb())


# ============================ VIP ПО ID ============================
@dp.message(F.text == "👑 VIP по ID")
@dp.message(F.text == "👑 ID bo'yicha VIP")
@dp.message(F.text == "👑 VIP by ID")
async def btn_vip_by_id(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = None
    await _reply(message, t("admin_vip_menu"), reply_markup=admin_vip_kb())


@dp.message(F.text == "➕ Выдать VIP")
@dp.message(F.text == "➕ VIP berish")
@dp.message(F.text == "➕ Grant VIP")
async def btn_vip_grant(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_vip_grant_id"
    await _reply(message, t("vip_ask_id"), reply_markup=cancel_reply_kb())


@dp.message(F.text == "➖ Забрать VIP")
@dp.message(F.text == "➖ VIP olish")
@dp.message(F.text == "➖ Revoke VIP")
async def btn_vip_revoke(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_vip_revoke_id"
    await _reply(message, t("vip_ask_id"), reply_markup=cancel_reply_kb())


# ============================ МАССОВЫЙ VIP ============================
@dp.message(F.text == "👑 VIP всем")
@dp.message(F.text == "👑 Hammaga VIP")
@dp.message(F.text == "👑 VIP to all")
async def btn_vip_all(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["bulk_filter"] = "all"
    await _reply(message, t("vip_bulk_menu_title", target="👥 всем"),
                 reply_markup=vip_bulk_menu_kb("all"))


@dp.message(F.text == "👑 VIP девушкам")
@dp.message(F.text == "👑 Qizlarga VIP")
@dp.message(F.text == "👑 VIP to girls")
async def btn_vip_girls(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["bulk_filter"] = "female"
    await _reply(message, t("vip_bulk_menu_title", target="👩 девушкам"),
                 reply_markup=vip_bulk_menu_kb("female"))


@dp.message(F.text == "👑 VIP парням")
@dp.message(F.text == "👑 Yigitlarga VIP")
@dp.message(F.text == "👑 VIP to guys")
async def btn_vip_guys(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["bulk_filter"] = "male"
    await _reply(message, t("vip_bulk_menu_title", target="👨 парням"),
                 reply_markup=vip_bulk_menu_kb("male"))


@dp.message(F.text.in_({
    "➕ Выдать VIP всем", "➕ Hammaga VIP berish", "➕ Grant VIP to all",
    "➕ Выдать VIP девушкам", "➕ Qizlarga VIP berish", "➕ Grant VIP to girls",
    "➕ Выдать VIP парням", "➕ Yigitlarga VIP berish", "➕ Grant VIP to guys",
}))
async def btn_vip_bulk_grant(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    bulk_filter = UD[uid].get("bulk_filter") or "all"
    UD[uid]["state"] = f"adm_vip_bulk_days:{bulk_filter}"
    target_name = {"all": "всем", "female": "девушкам", "male": "парням"}[bulk_filter]
    await _reply(message, t("vip_bulk_ask_days", target=target_name),
                 reply_markup=cancel_reply_kb())


@dp.message(F.text.in_({
    "➖ Забрать у всех", "➖ Hammadan olish", "➖ Revoke from all",
    "➖ Забрать у девушек", "➖ Qizlardan olish", "➖ Revoke from girls",
    "➖ Забрать у парней", "➖ Yigitlardan olish", "➖ Revoke from guys",
}))
async def btn_vip_bulk_revoke(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    bulk_filter = UD[uid].get("bulk_filter") or "all"
    where = ""
    target_name = {"all": "всем", "female": "девушкам", "male": "парням"}[bulk_filter]
    if bulk_filter == "female":
        where = "WHERE gender='f'"
    elif bulk_filter == "male":
        where = "WHERE gender='m'"
    try:
        conn.execute(f"UPDATE users SET vip_until=NULL {where}")
        conn.commit()
        cnt = conn.execute(f"SELECT COUNT(*) c FROM users {where}").fetchone()["c"]
    except Exception as e:
        log.warning("vip bulk revoke: %s", e)
        cnt = "?"
    await _reply(message, t("vip_bulk_revoke_done", target=target_name, count=cnt),
                 reply_markup=admin_vip_kb())


# ============================ МОДЕРЫ ============================
@dp.message(F.text == "🛡 Модеры")
@dp.message(F.text == "🛡 Moderatorlar")
@dp.message(F.text == "🛡 Moderators")
async def btn_moders_menu(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    await _reply(message, "🛡 <b>Управление модерами</b>", reply_markup=admin_moder_kb())


@dp.message(F.text == "➕ Выдать модера")
@dp.message(F.text == "➕ Moder berish")
@dp.message(F.text == "➕ Grant moder")
async def btn_moder_grant(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_moder_grant_id"
    await _reply(message, t("vip_ask_id"), reply_markup=cancel_reply_kb())


@dp.message(F.text == "➖ Забрать модера")
@dp.message(F.text == "➖ Moderni olish")
@dp.message(F.text == "➖ Revoke moder")
async def btn_moder_revoke(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_moder_revoke_id"
    await _reply(message, t("vip_ask_id"), reply_markup=cancel_reply_kb())


# ============================ БАН / РАЗБАН ============================
@dp.message(F.text == "🔨 Бан / Разбан")
@dp.message(F.text == "🔨 Ban / Unban")
async def btn_ban_menu(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    UD[uid]["state"] = "adm_ban_id"
    await _reply(message, "🔨 Введите ID пользователя:", reply_markup=cancel_reply_kb())


# ============================ РАССЫЛКА ============================
@dp.message(F.text == "📢 Рассылка")
@dp.message(F.text == "📢 Xabar tarqatish")
@dp.message(F.text == "📢 Broadcast")
async def btn_broadcast(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_bcast_audience"
    await _reply(message, "📢 Выберите аудиторию:", reply_markup=bcast_audience_kb())


@dp.message(F.text.in_({"👥 Всем", "👥 Hammaga", "👥 Everyone"}))
async def bcast_all(message: Message):
    uid = message.from_user.id
    if not is_admin(uid) or UD[uid].get("state") != "adm_bcast_audience":
        return
    UD[uid]["state"] = "adm_bcast_text"
    UD[uid]["bcast_filter"] = "all"
    await _reply(message, "✉️ Отправьте сообщение:", reply_markup=cancel_reply_kb())


@dp.message(F.text.in_({"👨 Мужчинам", "👨 Erkaklarga", "👨 To men"}))
async def bcast_male(message: Message):
    uid = message.from_user.id
    if not is_admin(uid) or UD[uid].get("state") != "adm_bcast_audience":
        return
    UD[uid]["state"] = "adm_bcast_text"
    UD[uid]["bcast_filter"] = "male"
    await _reply(message, "✉️ Отправьте сообщение:", reply_markup=cancel_reply_kb())


@dp.message(F.text.in_({"👩 Женщинам", "👩 Ayollarga", "👩 To women"}))
async def bcast_female(message: Message):
    uid = message.from_user.id
    if not is_admin(uid) or UD[uid].get("state") != "adm_bcast_audience":
        return
    UD[uid]["state"] = "adm_bcast_text"
    UD[uid]["bcast_filter"] = "female"
    await _reply(message, "✉️ Отправьте сообщение:", reply_markup=cancel_reply_kb())


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "adm_bcast_text")
async def bcast_send(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    flt = UD[uid].get("bcast_filter", "all")
    where = "WHERE 1=1"
    params = []
    if flt == "male":
        where += " AND gender='m'"
    elif flt == "female":
        where += " AND gender='f'"
    if BCAST_SKIP_VIP_IN_NEXT:
        where += " AND (vip_until IS NULL OR vip_until<=?)"
        params.append(now_iso())
    try:
        rows = conn.execute(f"SELECT tg_id FROM users {where}", tuple(params)).fetchall()
    except Exception:
        rows = []
    ok = bad = 0
    for r in rows:
        try:
            await message.bot.copy_message(r["tg_id"], message.chat.id,
                                            message.message_id)
            ok += 1
        except TelegramError:
            bad += 1
    UD[uid]["state"] = None
    await _reply(message, f"✅ Рассылка завершена\n✔️ {ok} | ❌ {bad}",
                 reply_markup=admin_menu_kb())


# ============================ ОБЯЗАТЕЛЬНЫЕ КАНАЛЫ ============================
@dp.message(F.text == "📢 Обязательные каналы")
@dp.message(F.text == "📢 Majburiy kanallar")
@dp.message(F.text == "📢 Required channels")
async def btn_channels(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    chans = await get_mandatory_channels()
    if not chans:
        txt = "📢 <b>Обязательные каналы</b>\n\n<i>Пусто</i>"
    else:
        lines = ["📢 <b>Обязательные каналы</b>\n"]
        for i, c in enumerate(chans, 1):
            lines.append(f"{i}. {channel_title(c)} — <code>{c['chat_username']}</code>")
        txt = "\n".join(lines)
    kb = adm_channels_kb(uid) if is_admin(uid) else moder_menu_kb()
    await _reply(message, txt, reply_markup=kb)


@dp.message(F.text == "➕ Добавить канал")
@dp.message(F.text == "➕ Kanal qo'shish")
@dp.message(F.text == "➕ Add channel")
async def btn_add_channel(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    UD[uid]["state"] = "adm_channel_add"
    await _reply(message, "📢 Отправьте @username канала или ссылку t.me/...",
                 reply_markup=cancel_reply_kb())


@dp.message(F.text == "🗑 Удалить канал")
@dp.message(F.text == "🗑 Kanalni o'chirish")
@dp.message(F.text == "🗑 Delete channel")
async def btn_del_channel(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    chans = channels_deletable_by(uid)
    if not chans:
        kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
        await _reply(message, "📢 Нет каналов для удаления.", reply_markup=kb)
        return
    UD[uid]["state"] = "adm_channel_del"
    lines = ["🗑 Введите номер канала для удаления:"]
    for i, c in enumerate(chans, 1):
        lines.append(f"{i}. {channel_title(c)} — {c['chat_username']}")
    await _reply(message, "\n".join(lines), reply_markup=cancel_reply_kb())


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "adm_channel_add")
async def adm_channel_add_save(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    raw = message.text.strip()
    ttl = None
    try:
        ch = await message.bot.get_chat(raw)
        ttl = ch.title or raw
    except TelegramError:
        pass
    try:
        conn.execute(
            "INSERT INTO mandatory_channels (chat_username, title, added_by) "
            "VALUES (?, ?, ?)",
            (raw, ttl, uid),
        )
        conn.commit()
        UD[uid]["state"] = None
        kb = adm_channels_kb(uid) if is_admin(uid) else moder_menu_kb()
        await _reply(message, f"✅ Канал добавлен: {raw}", reply_markup=kb)
    except Exception as e:
        log.warning("add channel: %s", e)
        await _reply(message, "❌ Ошибка добавления", reply_markup=cancel_reply_kb())


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "adm_channel_del")
async def adm_channel_del_save(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    txt = message.text.strip()
    if not txt.isdigit():
        await _reply(message, "❌ Введите номер:", reply_markup=cancel_reply_kb())
        return
    chans = channels_deletable_by(uid)
    idx = int(txt) - 1
    if idx < 0 or idx >= len(chans):
        await _reply(message, "❌ Нет такого номера.", reply_markup=cancel_reply_kb())
        return
    cid = chans[idx]["id"]
    conn.execute("DELETE FROM mandatory_channels WHERE id=?", (cid,))
    conn.commit()
    UD[uid]["state"] = None
    kb = adm_channels_kb(uid) if is_admin(uid) else moder_menu_kb()
    await _reply(message, "✅ Канал удалён.", reply_markup=kb)


@dp.message(F.text.startswith("Подписка для входа"))
async def toggle_subgate(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    cur = get_setting("subgate_enabled", "0")
    new = "0" if cur == "1" else "1"
    set_setting("subgate_enabled", new)
    await _reply(message, f"✅ Подписка: {'ВКЛ' if new == '1' else 'ВЫКЛ'}",
                 reply_markup=adm_channels_kb(uid))


# ============================ STARS-АДМИН ============================
@dp.message(F.text == "⭐ Коины за Stars")
@dp.message(F.text == "⭐ Stars uchun coin")
@dp.message(F.text == "⭐ Coins for Stars")
async def btn_stars_admin(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    pkgs = conn.execute("SELECT * FROM star_packages").fetchall()
    lines = ["⭐ <b>Пакеты коинов</b>\n"]
    for p in pkgs:
        status = "✅" if p["active"] else "❌"
        lines.append(
            f"{status} #{p['id']} {p['title']} — {p['coins']}💰 / {p['price_stars']}⭐"
        )
    await _reply(message, "\n".join(lines) or "Пусто", reply_markup=star_admin_kb())


@dp.message(F.text == "➕ Добавить пакет коинов")
@dp.message(F.text == "➕ Coin paket qo'shish")
@dp.message(F.text == "➕ Add coin package")
async def btn_add_pkg(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_pkg_title"
    await _reply(message, "📝 Введите название пакета:", reply_markup=cancel_reply_kb())


@dp.message(F.text == "🗑 Удалить пакет коинов")
@dp.message(F.text == "🗑 Coin paketni o'chirish")
@dp.message(F.text == "🗑 Delete coin package")
async def btn_del_pkg(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_pkg_del"
    await _reply(message, "🗑 Введите #ID пакета:", reply_markup=cancel_reply_kb())


@dp.message(F.text == "⭐ Возврат Stars")
@dp.message(F.text == "⭐ Stars qaytarish")
@dp.message(F.text == "⭐ Refund Stars")
async def btn_refund_stars(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    UD[uid]["state"] = "adm_refund"
    await _reply(message, "⭐ Введите ID пользователя для возврата:",
                 reply_markup=cancel_reply_kb())


@dp.message(F.text == "💎 Цена раскрытия")
@dp.message(F.text == "💎 Ochish narxi")
@dp.message(F.text == "💎 Reveal price")
async def btn_reveal_price(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    body = "\n".join(f"{p['count']} — {p['stars']} ⭐" for p in REVEAL_PACKAGES)
    await _reply(message, f"💎 <b>Пакеты раскрытия:</b>\n{body}",
                 reply_markup=admin_menu_kb())


# ============================ ОБРАБОТКА STATE-ОВ АДМИНКИ ============================
@dp.message(F.text, lambda m: (UD[m.from_user.id].get("state") or "").startswith("adm_"))
async def adm_state_router(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    state = UD[uid]["state"]
    text = message.text.strip() if message.text else ""

    # ---- Коины: ID ----
    if state == "adm_coins_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        UD[uid]["adm_target"] = target
        UD[uid]["state"] = "adm_coins_amount"
        await _reply(message, "💰 Введите количество коинов:", reply_markup=cancel_reply_kb())
        return

    # ---- Коины: сумма ----
    if state == "adm_coins_amount":
        if not text.lstrip("-").isdigit():
            await _reply(message, "🔢 Введите число:", reply_markup=cancel_reply_kb())
            return
        amt = int(text)
        tgt = UD[uid]["adm_target"]
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, tgt))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, f"✅ Начислено {amt} пользователю {tgt}",
                     reply_markup=admin_menu_kb())
        return

    # ---- VIP по ID ----
    if state == "adm_vip_grant_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        UD[uid]["adm_target"] = target
        UD[uid]["state"] = "adm_vip_grant_days"
        await _reply(message, t("vip_ask_days"), reply_markup=cancel_reply_kb())
        return

    if state == "adm_vip_grant_days":
        if not text.isdigit():
            await _reply(message, t("vip_days_number"), reply_markup=cancel_reply_kb())
            return
        days = int(text)
        tgt = UD[uid]["adm_target"]
        until = (now_dt() + timedelta(days=days)).isoformat()
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (until, tgt))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("vip_granted_admin", id=tgt, days=days),
                     reply_markup=admin_vip_kb())
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(tgt))
            await message.bot.send_message(tgt, t("vip_granted_user", days=days))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    if state == "adm_vip_revoke_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE users SET vip_until=NULL WHERE tg_id=?", (target,))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("vip_taken_admin", id=target), reply_markup=admin_vip_kb())
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await message.bot.send_message(target, t("vip_taken_user"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    # ---- Массовый VIP ----
    if state.startswith("adm_vip_bulk_days:"):
        if not text.isdigit():
            await _reply(message, t("vip_days_number"), reply_markup=cancel_reply_kb())
            return
        days = int(text)
        flt = state.split(":", 1)[1]
        where = ""
        if flt == "female":
            where = "WHERE gender='f'"
        elif flt == "male":
            where = "WHERE gender='m'"
        until = (now_dt() + timedelta(days=days)).isoformat()
        try:
            conn.execute(f"UPDATE users SET vip_until=? {where}", (until,))
            conn.commit()
            cnt = conn.execute(f"SELECT COUNT(*) c FROM users {where}").fetchone()["c"]
        except Exception as e:
            log.warning("bulk vip: %s", e)
            cnt = "?"
        UD[uid]["state"] = None
        tn = {"all": "всем", "female": "девушкам", "male": "парням"}[flt]
        await _reply(message, t("vip_bulk_done", target=tn, days=days, count=cnt),
                     reply_markup=admin_vip_kb())
        return

    # ---- Модеры ----
    if state == "adm_moder_grant_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=?", (target,))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, f"✅ Модер выдан {target}", reply_markup=admin_moder_kb())
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await message.bot.send_message(target, t("moder_granted_user"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    if state == "adm_moder_revoke_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        conn.execute("UPDATE users SET is_moder=0, moder_until=NULL WHERE tg_id=?",
                     (target,))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, f"✅ Модер снят {target}", reply_markup=admin_moder_kb())
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await message.bot.send_message(target, t("moder_taken_user"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    # ---- Бан / Разбан ----
    if state == "adm_ban_id":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        u = get_user(target)
        if not u:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        if is_staff(target):
            UD[uid]["state"] = None
            kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
            await _reply(message, t("cant_ban_staff"), reply_markup=kb)
            return
        new = 0 if u["is_banned"] else 1
        conn.execute("UPDATE users SET is_banned=? WHERE tg_id=?", (new, target))
        conn.commit()
        UD[uid]["state"] = None
        msg = "🔨 Забанен" if new else "✅ Разбанен"
        kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
        await _reply(message, f"{msg}: {target}", reply_markup=kb)
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(target))
            await message.bot.send_message(target, t("banned") if new else t("done"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
        return

    # ---- Добавление пакета коинов ----
    if state == "adm_pkg_title":
        UD[uid]["pkg"] = {"title": text}
        UD[uid]["state"] = "adm_pkg_coins"
        await _reply(message, "💰 Сколько коинов в пакете?", reply_markup=cancel_reply_kb())
        return

    if state == "adm_pkg_coins":
        if not text.isdigit():
            await _reply(message, "🔢 Введите число:", reply_markup=cancel_reply_kb())
            return
        UD[uid]["pkg"]["coins"] = int(text)
        UD[uid]["state"] = "adm_pkg_stars"
        await _reply(message, "⭐ Цена в Stars:", reply_markup=cancel_reply_kb())
        return

    if state == "adm_pkg_stars":
        if not text.isdigit():
            await _reply(message, "🔢 Введите число:", reply_markup=cancel_reply_kb())
            return
        p = UD[uid]["pkg"]
        try:
            conn.execute(
                "INSERT INTO star_packages (title, coins, price_stars, active) "
                "VALUES (?, ?, ?, 1)",
                (p["title"], p["coins"], int(text)),
            )
            conn.commit()
        except Exception as e:
            log.warning("add pkg: %s", e)
        UD[uid]["state"] = None
        UD[uid].pop("pkg", None)
        await _reply(message, "✅ Пакет добавлен.", reply_markup=star_admin_kb())
        return

    if state == "adm_pkg_del":
        if not text.lstrip("#").isdigit():
            await _reply(message, "🔢 Введите ID:", reply_markup=cancel_reply_kb())
            return
        pid = int(text.lstrip("#"))
        conn.execute("DELETE FROM star_packages WHERE id=?", (pid,))
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, f"✅ Удалён пакет #{pid}", reply_markup=star_admin_kb())
        return

    if state == "adm_refund":
        target = resolve_user_ref(text)
        if not target:
            await _reply(message, t("vip_user_not_found"), reply_markup=cancel_reply_kb())
            return
        refunded = 0
        try:
            rows = conn.execute(
                "SELECT * FROM star_purchases WHERE user_id=? AND refunded=0",
                (target,),
            ).fetchall()
            for r in rows:
                try:
                    conn.execute(
                        "UPDATE star_purchases SET refunded=1, refunded_at=? WHERE id=?",
                        (now_iso(), r["id"]),
                    )
                    conn.execute(
                        "UPDATE users SET coins = MAX(0, coins - ?) WHERE tg_id=?",
                        (r["coins"], target),
                    )
                    refunded += r["stars"]
                except Exception:
                    continue
            conn.commit()
        except Exception as e:
            log.warning("refund: %s", e)
        UD[uid]["state"] = None
        await _reply(message, f"✅ Возврат выполнен. Всего звёзд: {refunded}",
                     reply_markup=admin_menu_kb())
        return
        # ============================ МАГАЗИН ============================
@dp.message(F.text == "🛒 Магазин")
@dp.message(F.text == "🛒 Do'kon")
@dp.message(F.text == "🛒 Shop")
async def btn_shop(message: Message):
    uid = message.from_user.id
    u = get_user(uid)
    items = conn.execute("SELECT * FROM shop_items WHERE active=1").fetchall()
    if not items:
        await _reply(message, t("shop_empty"), reply_markup=main_menu_kb(uid))
        return
    rows = []
    for it in items:
        price = effective_price(it["price"], u)
        rows.append([KeyboardButton(f"{item_title(it)} · {price}💰")])
    rows.append([KeyboardButton("⬅️ Назад")])
    UD[uid]["state"] = "shop_browse"
    await _reply(message, t("shop_title"),
                 reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "shop_browse")
async def shop_buy_handler(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    if " · " not in text:
        return
    title_part = text.rsplit(" · ", 1)[0]
    items = conn.execute("SELECT * FROM shop_items WHERE active=1").fetchall()
    target = None
    for it in items:
        if item_title(it) == title_part:
            target = it
            break
    if not target:
        return
    u = get_user(uid)
    price = effective_price(target["price"], u)
    if (u["coins"] or 0) < price:
        await _reply(message, t("not_enough_coins"), reply_markup=main_menu_kb(uid))
        return

    conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (price, uid))
    conn.commit()

    rtype = target["reward_type"] or "manual"
    if rtype == "coins":
        amt = target["reward_amount"] or 0
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, uid))
        conn.commit()
        await _reply(message, t("purchase_coins", amt=amt),
                     reply_markup=main_menu_kb(uid))
    elif rtype == "vip" or target["is_vip"]:
        days = target["duration_days"] or 30
        until = (now_dt() + timedelta(days=days)).isoformat()
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (until, uid))
        conn.commit()
        await _reply(message, t("purchase_vip", days=days),
                     reply_markup=main_menu_kb(uid))
    else:
        try:
            conn.execute(
                "INSERT INTO moder_apps (user_id, item_id, price_paid, status, created_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (uid, target["id"], price, now_iso()),
            )
            conn.commit()
            app_row = conn.execute(
                "SELECT id FROM moder_apps WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (uid,),
            ).fetchone()
            aid = app_row["id"] if app_row else 0
            await _reply(message, t("purchase_manual"), reply_markup=main_menu_kb(uid))
            for adm in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        adm,
                        f"🛒 Новая заявка #{aid}\n👤 <code>{uid}</code>\n"
                        f"📦 {item_title(target)}\n💰 {price}",
                        reply_markup=moder_decision_kb(aid),
                    )
                except TelegramError:
                    pass
        except Exception as e:
            log.warning("shop manual: %s", e)
            await _reply(message, "❌ Ошибка", reply_markup=main_menu_kb(uid))

    try:
        conn.execute(
            "INSERT INTO purchases (user_id, item_id, price_paid, created_at) "
            "VALUES (?, ?, ?, ?)",
            (uid, target["id"], price, now_iso()),
        )
        conn.commit()
    except Exception:
        pass


# ============================ КУПИТЬ КОИНЫ ЗА STARS ============================
@dp.message(F.text == "💎 Купить коины")
@dp.message(F.text == "💎 Coin sotib olish")
@dp.message(F.text == "💎 Buy coins")
async def btn_buy_coins(message: Message):
    uid = message.from_user.id
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    if not pkgs:
        await _reply(message, t("stars_unavailable"), reply_markup=main_menu_kb(uid))
        return
    rows = []
    for p in pkgs:
        rows.append([KeyboardButton(
            f"{item_title(p)} — {p['coins']}💰 · {p['price_stars']}⭐"
        )])
    rows.append([KeyboardButton("⬅️ Назад")])
    UD[uid]["state"] = "stars_browse"
    await _reply(message, t("stars_title"),
                 reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "stars_browse")
async def stars_buy(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    if " · " not in text or "💰" not in text:
        return
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    target = None
    for p in pkgs:
        label = f"{item_title(p)} — {p['coins']}💰 · {p['price_stars']}⭐"
        if label == text:
            target = p
            break
    if not target:
        return
    try:
        await message.bot.send_invoice(
            chat_id=uid,
            title=item_title(target),
            description=t("stars_pkg_desc", coins=target["coins"]),
            payload=f"starpkg:{target['id']}",
            provider_token="",
            currency="XTR",
            prices=[_AiLabeledPrice(label=item_title(target),
                                     amount=int(target["price_stars"]))],
        )
        UD[uid]["state"] = None
    except TelegramError as e:
        log.warning("stars invoice: %s", e)
        await _reply(message, "❌ Ошибка выставления счёта",
                     reply_markup=main_menu_kb(uid))


# ============================ PREMIUM ============================
@dp.message(F.text == "⭐ Premium")
async def btn_premium(message: Message):
    uid = message.from_user.id
    u = get_user(uid)
    if is_vip(u) and not is_admin(uid):
        try:
            dt = datetime.fromisoformat(u["vip_until"])
            await _reply(message, t("premium_active", date=dt.strftime("%d.%m.%Y")),
                         reply_markup=premium_menu_kb())
        except Exception:
            await _reply(message, t("premium_title"), reply_markup=premium_menu_kb())
    else:
        await _reply(message, t("premium_title"), reply_markup=premium_menu_kb())


@dp.message(F.text.startswith("📅 "))
async def premium_buy(message: Message):
    uid = message.from_user.id
    pkg = None
    for p in VIP_PACKAGES:
        if p["label"] in message.text:
            pkg = p
            break
    if not pkg:
        return
    try:
        await message.bot.send_invoice(
            chat_id=uid,
            title=f"⭐ Premium {pkg['label']}",
            description=t("premium_pkg_desc", months=pkg["months"],
                          days=pkg["months"] * 30),
            payload=f"vippkg:{pkg['months']}",
            provider_token="",
            currency="XTR",
            prices=[_AiLabeledPrice(label=f"Premium {pkg['label']}",
                                     amount=pkg["stars"])],
        )
    except TelegramError as e:
        log.warning("vip invoice: %s", e)


# ============================ КУПИТЬ «УЗНАТЬ» ============================
@dp.message(F.text == "👁 Купить «Узнать»")
@dp.message(F.text == "👁 «Aniqlash» sotib olish")
@dp.message(F.text == "👁 Buy «Reveal»")
async def btn_buy_reveal(message: Message):
    await _reply(message, t("reveal_pack_title"), reply_markup=reveal_pack_kb())


@dp.message(F.text, lambda m: any(
    (m.text or "").startswith(f"{p['count']} шт") for p in REVEAL_PACKAGES
))
async def reveal_buy_pack(message: Message):
    uid = message.from_user.id
    text = message.text
    pkg = None
    for p in REVEAL_PACKAGES:
        if text.startswith(f"{p['count']} шт"):
            pkg = p
            break
    if not pkg:
        return
    try:
        await message.bot.send_invoice(
            chat_id=uid,
            title=f"👁 Reveal × {pkg['count']}",
            description=t("reveal_desc"),
            payload=f"revpkg:{pkg['count']}",
            provider_token="",
            currency="XTR",
            prices=[_AiLabeledPrice(label=f"Reveal × {pkg['count']}",
                                     amount=pkg["stars"])],
        )
    except TelegramError as e:
        log.warning("reveal invoice: %s", e)


# ============================ /sex — КОМНАТА ДЛЯ МОДЕРОВ ============================
@dp.message(Command("sex"))
async def cmd_sex(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        await _reply(message, t("sex_only_moder"))
        return
    room = conn.execute("SELECT * FROM sex_rooms ORDER BY id DESC LIMIT 1").fetchone()
    if room:
        await _reply(message, t("sex_room_exists", title=html.escape(room["title"])))
        return
    UD[uid]["state"] = "sex_create_title"
    await _reply(message, t("sex_create_prompt"), reply_markup=cancel_reply_kb())


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "sex_create_title")
async def sex_create_title(message: Message):
    uid = message.from_user.id
    title = (message.text or "").strip()
    if not title:
        return
    try:
        cur = conn.execute(
            "INSERT INTO sex_rooms (title, owner_id, created_at) VALUES (?, ?, ?)",
            (title, uid, now_iso()),
        )
        conn.commit()
        rid = cur.lastrowid
        if not rid:
            rid = conn.execute(
                "SELECT id FROM sex_rooms ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
        girls = conn.execute("SELECT tg_id FROM users WHERE gender='f'").fetchall()
        for i, g in enumerate(girls, 1):
            try:
                conn.execute(
                    "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) "
                    "VALUES (?, ?, 'member', ?, ?)",
                    (rid, g["tg_id"], i, now_iso()),
                )
            except Exception:
                pass
        try:
            conn.execute(
                "INSERT INTO sex_members (room_id, user_id, role, number, joined_at) "
                "VALUES (?, ?, 'owner', 0, ?)",
                (rid, uid, now_iso()),
            )
        except Exception:
            pass
        conn.commit()
        UD[uid]["state"] = None
        await _reply(message, t("sex_room_created", title=html.escape(title)),
                     reply_markup=main_menu_kb(uid))
    except Exception as e:
        log.warning("sex create: %s", e)
        UD[uid]["state"] = None
        await _reply(message, "❌ Ошибка создания комнаты",
                     reply_markup=main_menu_kb(uid))


def _sex_user_room(uid):
    try:
        return conn.execute(
            "SELECT * FROM sex_members WHERE user_id=?", (uid,)
        ).fetchone()
    except Exception:
        return None


async def _sex_relay(message, uid):
    mem = _sex_user_room(uid)
    if not mem:
        return
    rid = mem["room_id"]
    num = mem["number"]
    try:
        if message.voice:
            conn.execute(
                "INSERT INTO sex_messages "
                "(room_id, sender_number, content_type, voice_file_id, created_at) "
                "VALUES (?, ?, 'voice', ?, ?)",
                (rid, num, message.voice.file_id, now_iso()),
            )
        elif message.text:
            conn.execute(
                "INSERT INTO sex_messages "
                "(room_id, sender_number, content_type, text, created_at) "
                "VALUES (?, ?, 'text', ?, ?)",
                (rid, num, message.text, now_iso()),
            )
        conn.commit()
    except Exception:
        pass
    others = conn.execute(
        "SELECT user_id, number FROM sex_members WHERE room_id=? AND user_id<>?",
        (rid, uid),
    ).fetchall()
    for o in others:
        try:
            if message.voice:
                await message.bot.send_voice(o["user_id"], message.voice.file_id,
                                              caption=f"💬 {num}")
            else:
                await message.bot.send_message(
                    o["user_id"],
                    f"<b>💬 {num}:</b>\n{html.escape(message.text or '')}",
                )
        except TelegramError:
            pass


# ============================ /anon — НАБЛЮДЕНИЕ ============================
@dp.message(Command("anon"))
async def cmd_anon(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    UD[uid]["state"] = "watch_anon_id"
    await _reply(message, t("anon_watch_prompt"), reply_markup=cancel_reply_kb())


@dp.message(F.text, lambda m: UD[m.from_user.id].get("state") == "watch_anon_id")
async def anon_watch_handle(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    txt = (message.text or "").strip().lstrip("@")
    if not txt.isdigit():
        await _reply(message, "🔢 Введите ID:", reply_markup=cancel_reply_kb())
        return
    target = int(txt)
    msgs = conn.execute(
        "SELECT * FROM anon_messages WHERE to_id=? OR from_id=? "
        "ORDER BY id DESC LIMIT 100",
        (target, target),
    ).fetchall()
    if not msgs:
        kb = moder_menu_kb() if not is_admin(uid) else admin_menu_kb()
        await _reply(message, t("anon_watch_empty"), reply_markup=kb)
        UD[uid]["state"] = None
        return
    lines = [f"👁 Наблюдение за {target}", "=" * 30]
    for m in reversed(msgs):
        lines.append(
            f"[{m['created_at']}] {m['from_id']} → {m['to_id']} "
            f"({m['content_type']}): {m['text'] or ''}"
        )
    data = "\n".join(lines).encode("utf-8")
    try:
        conn.execute(
            "INSERT INTO anon_watchers (mod_id, target_id, active, created_at) "
            "VALUES (?, ?, 1, ?)",
            (uid, target, now_iso()),
        )
        conn.commit()
        await message.bot.send_document(
            uid, BufferedInputFile(data, filename=f"anon_{target}.txt"),
            caption=t("anon_watch_file_caption", uid=target),
        )
    except TelegramError as e:
        log.warning("watch anon: %s", e)
    except Exception as e:
        log.warning("watch anon DB: %s", e)
    UD[uid]["state"] = None


# ============================ /next — СООБЩЕНИЕ ОТ АДМИНА ============================
@dp.message(Command("next"))
async def cmd_next_admin(message: Message, command: CommandObject):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    args = (command.args or "").strip()
    if not args:
        await _reply(message, "Использование: /next <user_id> <текст>")
        return
    parts = args.split(maxsplit=1)
    if not parts[0].isdigit():
        await _reply(message, "❌ ID должен быть числом.")
        return
    target = int(parts[0])
    txt = parts[1] if len(parts) > 1 else "(пусто)"
    try:
        await message.bot.send_message(
            target, f"📨 <b>Сообщение от админа:</b>\n{txt}"
        )
        await _reply(message, "✅ Отправлено")
    except TelegramError as e:
        await _reply(message, f"❌ {e}")


# ============================ /tg — МОНИТОРИНГ РУЛЕТКИ ============================
@dp.message(Command("tg"))
async def cmd_tg_monitor(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        return
    active = conn.execute(
        "SELECT COUNT(*) c FROM roulette_sessions WHERE active=1"
    ).fetchone()["c"]
    queue = conn.execute("SELECT COUNT(*) c FROM roulette_queue").fetchone()["c"]
    await _reply(message, f"🎲 Активных сессий: {active}\n⏳ В очереди: {queue}")
    # ============================ ИНЛАЙН-КОЛБЭКИ АНОНИМКИ ============================
@dp.callback_query(F.data.startswith("areply:"))
async def cb_anon_reply(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        pid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (pid,)).fetchone()
    if not parent or parent["to_id"] != uid:
        await cq.answer(t("anon_not_found"), show_alert=True)
        return
    UD[uid]["state"] = f"anon_reply:{pid}"
    await cq.message.answer(t("anon_reply_prompt"), reply_markup=cancel_reply_kb())
    await cq.answer()


@dp.callback_query(F.data.startswith("areport:"))
async def cb_anon_report(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        pid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (pid,)).fetchone()
    if not parent:
        await cq.answer(t("anon_not_found"), show_alert=True)
        return
    rid = 0
    try:
        cur = conn.execute(
            "INSERT INTO reports (reporter_id, reported_id, context, ref_id, status, created_at) "
            "VALUES (?, ?, 'anon', ?, 'pending', ?)",
            (uid, parent["from_id"], pid, now_iso()),
        )
        conn.commit()
        rid = cur.lastrowid or 0
    except Exception as e:
        log.warning("anon report insert: %s", e)
    await cq.answer(t("report_sent"))
    from_mention = user_mention(get_user(parent["from_id"]))
    rep_mention = user_mention(get_user(uid))
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t("🔨 Бан"), callback_data=f"rep:ban:{rid}"),
        InlineKeyboardButton(t("❌ Отклонить"), callback_data=f"rep:no:{rid}"),
    ]])
    for adm in ADMIN_IDS:
        try:
            await cq.bot.send_message(
                adm,
                f"🚩 <b>Жалоба #{rid}</b>\n"
                f"👤 От: {rep_mention}\n"
                f"🎯 На: {from_mention}\n"
                f"📝 Контекст: {html.escape((parent['text'] or '')[:200])}",
                reply_markup=kb,
            )
        except TelegramError:
            pass


@dp.callback_query(F.data.startswith("adel:"))
async def cb_anon_delete(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        pid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (pid,)).fetchone()
    if not parent:
        await cq.answer(t("anon_not_found"), show_alert=True)
        return
    if parent["to_id"] != uid:
        await cq.answer("❌", show_alert=True)
        return

    other = parent["from_id"]
    ok_other = False
    try:
        if parent["owner_chat_message_id"]:
            await cq.bot.delete_message(uid, parent["owner_chat_message_id"])
            ok_other = True
    except TelegramError:
        pass
    try:
        conn.execute("UPDATE anon_messages SET deleted=1 WHERE id=?", (pid,))
        conn.commit()
    except Exception:
        pass

    try:
        await cq.message.delete()
    except TelegramError:
        pass

    if ok_other:
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(other))
            await cq.bot.send_message(other, t("anon_deleted_notice"))
            set_cur_lang(_sl)
        except TelegramError:
            pass
    await cq.answer(t("del_both") if ok_other else t("del_only_me"))


@dp.callback_query(F.data.startswith("areveal:"))
async def cb_anon_reveal(cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        pid = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer()
        return
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (pid,)).fetchone()
    if not parent:
        await cq.answer(t("anon_not_found"), show_alert=True)
        return
    if parent["to_id"] != uid:
        await cq.answer(t("reveal_only_recipient"), show_alert=True)
        return

    if is_vip(get_user(uid)) and get_reveal_free_left(uid) > 0:
        use_reveal_free(uid)
        await _do_reveal_anon(cq.bot, uid, parent["from_id"])
        await cq.answer()
        return

    try:
        await cq.bot.send_invoice(
            chat_id=uid,
            title="👁 Раскрытие отправителя",
            description=t("reveal_desc"),
            payload=f"reveal_anon:{pid}",
            provider_token="",
            currency="XTR",
            prices=[_AiLabeledPrice(label="👁 Reveal", amount=1)],
        )
    except TelegramError as e:
        log.warning("anon reveal invoice: %s", e)
    await cq.answer()


async def _do_reveal_anon(bot, uid, target_id):
    fu = get_user(target_id)
    if not fu:
        await bot.send_message(uid, "❌ Пользователь не найден")
        return
    uname = f"@{fu['username']}" if fu["username"] else "—"
    _sl = cur_lang()
    set_cur_lang(get_lang(uid))
    txt = t("reveal_result",
            name=html.escape(fu["first_name"] or "—"),
            uname=uname, tid=target_id)
    set_cur_lang(_sl)
    try:
        await bot.send_message(uid, txt)
    except TelegramError:
        pass


# ============================ КОЛБЭКИ РЕФЕРАЛОВ ============================
@dp.callback_query(F.data == "ref_info")
async def cb_ref_info(cq: CallbackQuery):
    await cq.answer(
        t("ref_info_alert", n=REF_REWARD_NORMAL, v=REF_REWARD_VIP),
        show_alert=True,
    )


@dp.callback_query(F.data == "claim_vip")
async def cb_claim_vip(cq: CallbackQuery):
    uid = cq.from_user.id
    have = qualified_referrals(uid)
    need = cfg_vip_threshold()
    if have < need:
        await cq.answer(t("ref_need_more", n=need - have, have=have, need=need),
                        show_alert=True)
        return
    days = cfg_vip_days()
    until = (now_dt() + timedelta(days=days)).isoformat()
    conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (until, uid))
    conn.execute("UPDATE users SET ref_vip_claims = ref_vip_claims + 1 WHERE tg_id=?",
                 (uid,))
    conn.commit()
    await cq.answer(t("ref_vip_granted", days=days), show_alert=True)


@dp.callback_query(F.data == "claim_moder")
async def cb_claim_moder(cq: CallbackQuery):
    uid = cq.from_user.id
    have = qualified_referrals(uid)
    need = cfg_moder_threshold()
    if have < need:
        await cq.answer(t("ref_need_more", n=need - have, have=have, need=need),
                        show_alert=True)
        return
    days = cfg_moder_days()
    until = (now_dt() + timedelta(days=days)).isoformat()
    conn.execute("UPDATE users SET moder_until=? WHERE tg_id=?", (until, uid))
    conn.execute("UPDATE users SET ref_moder_claims = ref_moder_claims + 1 WHERE tg_id=?",
                 (uid,))
    conn.commit()
    await cq.answer(t("ref_moder_granted", days=days, need=need), show_alert=True)


# ============================ ОДОБРЕНИЕ ЗАЯВОК МОДЕРА ============================
@dp.callback_query(F.data.startswith("modapp:"))
async def cb_modapp(cq: CallbackQuery):
    uid = cq.from_user.id
    if not is_admin(uid):
        await cq.answer()
        return
    parts = cq.data.split(":")
    if len(parts) != 3:
        return
    action, aid = parts[1], parts[2]
    try:
        aid = int(aid)
    except ValueError:
        return
    app = conn.execute("SELECT * FROM moder_apps WHERE id=?", (aid,)).fetchone()
    if not app or app["status"] != "pending":
        await cq.answer(t("moder_app_already"), show_alert=True)
        return
    if action == "ok":
        conn.execute("UPDATE moder_apps SET status='approved' WHERE id=?", (aid,))
        conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=?", (app["user_id"],))
        conn.commit()
        await cq.answer(t("moder_granted_staff"))
        try:
            await cq.bot.send_message(app["user_id"], t("moder_granted_shop"))
        except TelegramError:
            pass
    else:
        conn.execute("UPDATE moder_apps SET status='rejected' WHERE id=?", (aid,))
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?",
                     (app["price_paid"], app["user_id"]))
        conn.commit()
        await cq.answer(t("moder_rejected_staff"))
        try:
            await cq.bot.send_message(
                app["user_id"],
                t("moder_rejected_user", coins=app["price_paid"]),
            )
        except TelegramError:
            pass
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except TelegramError:
        pass


# ============================ РЕШЕНИЕ ПО ЖАЛОБЕ ============================
@dp.callback_query(F.data.startswith("rep:"))
async def cb_report_decision(cq: CallbackQuery):
    uid = cq.from_user.id
    if not is_admin(uid):
        await cq.answer()
        return
    parts = cq.data.split(":")
    if len(parts) != 3:
        return
    action, rid = parts[1], parts[2]
    try:
        rid = int(rid)
    except ValueError:
        return
    rep = conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    if not rep or rep["status"] != "pending":
        await cq.answer(t("report_already_handled"), show_alert=True)
        return

    if action == "ban":
        reported = rep["reported_id"]
        if is_staff(reported):
            conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (rid,))
            conn.commit()
            await cq.answer(t("cant_ban_staff"))
            return
        until = (now_dt() + timedelta(days=BAN_DAYS)).isoformat()
        try:
            conn.execute(
                "INSERT INTO bans (owner_id, banned_id, until, created_at) "
                "VALUES (?, ?, ?, ?)",
                (rep["reporter_id"], reported, until, now_iso()),
            )
        except Exception:
            pass
        conn.execute("UPDATE reports SET status='banned' WHERE id=?", (rid,))
        conn.commit()
        await cq.answer(t("report_confirmed_staff"))
        try:
            _sl = cur_lang()
            set_cur_lang(get_lang(rep["reporter_id"]))
            await cq.bot.send_message(rep["reporter_id"],
                                       t("report_confirmed_user", days=BAN_DAYS))
            set_cur_lang(get_lang(reported))
            await cq.bot.send_message(reported, t("you_were_banned", days=BAN_DAYS))
            set_cur_lang(_sl)
        except TelegramError:
            pass
    else:
        conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (rid,))
        conn.commit()
        await cq.answer(t("report_rejected_staff"))
        try:
            await cq.bot.send_message(rep["reporter_id"], t("report_rejected_user"))
        except TelegramError:
            pass
    try:
        await cq.message.edit_reply_markup(reply_markup=None)
    except TelegramError:
        pass


# ============================ SUBGATE ============================
@dp.callback_query(F.data.startswith("subcheck:"))
async def cb_subcheck(cq: CallbackQuery):
    uid = cq.from_user.id
    if await _gate_ok(cq.bot, uid):
        await cq.answer(t("done"))
        try:
            await cq.message.delete()
        except TelegramError:
            pass
    else:
        await cq.answer(t("sub_not_found"), show_alert=True)


@dp.callback_query(F.data == "subgate")
async def cb_subgate(cq: CallbackQuery):
    uid = cq.from_user.id
    if await _gate_ok(cq.bot, uid):
        await cq.answer(t("done"))
        try:
            await cq.message.delete()
        except TelegramError:
            pass
        await _welcome_flow(cq.bot, uid, greet=True)
    else:
        await cq.answer(t("sub_not_found"), show_alert=True)


# ============================ ПЛАТЕЖИ ============================
@dp.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    try:
        await pcq.answer(ok=True)
    except TelegramError as e:
        log.warning("pre_checkout: %s", e)


@dp.message(F.successful_payment)
async def on_successful_payment(message: Message):
    uid = message.from_user.id
    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    charge_id = getattr(sp, "telegram_payment_charge_id", None)

    # ---- Пакет коинов ----
    if payload.startswith("starpkg:"):
        try:
            pid = int(payload.split(":", 1)[1])
        except (ValueError, IndexError):
            await _reply(message, "❌ Ошибка пакета", reply_markup=main_menu_kb(uid))
            return
        pkg = conn.execute("SELECT * FROM star_packages WHERE id=?", (pid,)).fetchone()
        if not pkg:
            await _reply(message, "❌ Пакет не найден", reply_markup=main_menu_kb(uid))
            return
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?",
                     (pkg["coins"], uid))
        try:
            conn.execute(
                "INSERT INTO star_purchases "
                "(user_id, package_id, coins, stars, charge_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, pid, pkg["coins"], sp.total_amount, charge_id, now_iso()),
            )
        except Exception:
            pass
        conn.commit()
        await _reply(message, t("stars_paid", coins=pkg["coins"]),
                     reply_markup=main_menu_kb(uid))

    # ---- Premium (VIP) ----
    elif payload.startswith("vippkg:"):
        try:
            months = int(payload.split(":", 1)[1])
        except (ValueError, IndexError):
            months = 1
        u = get_user(uid)
        base = now_dt()
        if u and u["vip_until"]:
            try:
                if datetime.fromisoformat(u["vip_until"]) > base:
                    base = datetime.fromisoformat(u["vip_until"])
            except Exception:
                pass
        until = (base + timedelta(days=months * 30)).isoformat()
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (until, uid))
        try:
            conn.execute(
                "INSERT INTO vip_purchases "
                "(user_id, months, stars, charge_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, months, sp.total_amount, charge_id, now_iso()),
            )
        except Exception:
            pass
        conn.commit()
        await _reply(message, t("premium_paid", months=months),
                     reply_markup=main_menu_kb(uid))

    # ---- Пакет «Узнать» ----
    elif payload.startswith("revpkg:"):
        try:
            cnt = int(payload.split(":", 1)[1])
        except (ValueError, IndexError):
            cnt = 1
        try:
            conn.execute(
                "INSERT INTO reveal_purchases "
                "(user_id, count, stars, charge_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, cnt, sp.total_amount, charge_id, now_iso()),
            )
            conn.commit()
        except Exception as e:
            log.warning("revpkg: %s", e)
        await _reply(message, t("reveal_pack_bought", n=cnt, stars=sp.total_amount),
                     reply_markup=main_menu_kb(uid))

    # ---- Раскрытие в анонимке ----
    elif payload.startswith("reveal_anon:"):
        try:
            pid = int(payload.split(":", 1)[1])
        except (ValueError, IndexError):
            await _reply(message, "❌", reply_markup=main_menu_kb(uid))
            return
        parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (pid,)).fetchone()
        if parent:
            await _do_reveal_anon(message.bot, uid, parent["from_id"])
        try:
            conn.execute(
                "INSERT INTO reveal_purchases "
                "(user_id, count, stars, charge_id, created_at) "
                "VALUES (?, 1, ?, ?, ?)",
                (uid, sp.total_amount, charge_id, now_iso()),
            )
            conn.commit()
        except Exception:
            pass
        await _reply(message, t("done"), reply_markup=main_menu_kb(uid))

    # ---- Раскрытие в 𝐍𝐞𝐱𝐭.. ----
    elif payload.startswith("reveal_next:"):
        try:
            tid = int(payload.split(":", 1)[1])
        except (ValueError, IndexError):
            await _reply(message, "❌", reply_markup=main_menu_kb(uid))
            return
        await _send_reveal_info(message.bot, uid, tid)
        try:
            conn.execute(
                "INSERT INTO nearby_notifications "
                "(user_id, chat_id, message_id, type, target_id, expires_at, created_at) "
                "VALUES (?, ?, 0, 'reveal_paid', ?, ?, ?)",
                (uid, uid, tid,
                 (now_dt() + timedelta(days=NEXT_NOTIF_TTL_DAYS)).isoformat(),
                 now_iso()),
            )
            conn.commit()
        except Exception:
            pass
        await _reply(message, t("done"), reply_markup=main_menu_kb(uid))

    else:
        await _reply(message, t("done"), reply_markup=main_menu_kb(uid))


# ============================ MY_CHAT_MEMBER ============================
@dp.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    if not update.from_user:
        return
    uid = update.from_user.id
    try:
        new_status = update.new_chat_member.status
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            if user_is_disposable(uid):
                purge_user(uid, force=False)
        elif new_status == ChatMemberStatus.MEMBER:
            ensure_user(uid, update.from_user.username, update.from_user.first_name)
    except Exception as e:
        log.debug("my_chat_member: %s", e)


# ============================ FALLBACK ============================
@dp.message()
async def fallback_message(message: Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username, message.from_user.first_name)
    u = get_user(uid)
    if is_banned(u):
        return
    if UD[uid].get("state"):
        return
    await _reply(message, t("not_understood"), reply_markup=main_menu_kb(uid))


@dp.errors()
async def on_error(event: ErrorEvent):
    log.error("Error: %s", event.exception, exc_info=True)


# ============================ ФОНОВЫЕ ЗАДАЧИ ============================
async def _janitor_loop():
    """Раз в час: чистка старых уведомлений, пустых юзеров, старых ссылок, таймаут поиска."""
    while True:
        try:
            await asyncio.sleep(3600)

            # 1) Удаление протухших уведомлений (лайки/мэтчи, TTL 14 дней)
            try:
                rows = conn.execute(
                    "SELECT * FROM nearby_notifications "
                    "WHERE deleted=0 AND expires_at<?",
                    (now_iso(),),
                ).fetchall()
                for r in rows:
                    try:
                        await bot.delete_message(r["chat_id"], r["message_id"])
                    except TelegramError:
                        pass
                    try:
                        conn.execute(
                            "UPDATE nearby_notifications SET deleted=1 WHERE id=?",
                            (r["id"],),
                        )
                    except Exception:
                        pass
                conn.commit()
            except Exception as e:
                log.debug("janitor notif: %s", e)

            # 2) Чистка пустых юзеров (неактивные > INACTIVE_DAYS)
            try:
                cutoff = (now_dt() - timedelta(days=INACTIVE_DAYS)).isoformat()
                rows = conn.execute(
                    "SELECT tg_id FROM users "
                    "WHERE (last_active IS NULL OR last_active<?) "
                    "AND created_at<? LIMIT 200",
                    (cutoff, cutoff),
                ).fetchall()
                for r in rows:
                    if user_is_disposable(r["tg_id"]):
                        purge_user(r["tg_id"], force=False)
            except Exception as e:
                log.debug("janitor purge: %s", e)

            # 3) Удаление устаревших old_link
            try:
                conn.execute(
                    "UPDATE users SET old_link=NULL, old_link_until=NULL "
                    "WHERE old_link_until IS NOT NULL AND old_link_until<?",
                    (now_iso(),),
                )
                conn.commit()
            except Exception:
                pass

            # 4) Таймаут поиска в рулетке
            try:
                now_ts = _time.time()
                for uid, started in list(_QUEUE_REMIND.items()):
                    q = conn.execute(
                        "SELECT 1 FROM roulette_queue WHERE user_id=?", (uid,)
                    ).fetchone()
                    if not q:
                        _QUEUE_REMIND.pop(uid, None)
                        continue
                    elapsed = now_ts - started
                    if elapsed > SEARCH_TIMEOUT_MIN * 60:
                        conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (uid,))
                        conn.commit()
                        _QUEUE_REMIND.pop(uid, None)
                        try:
                            _sl = cur_lang()
                            set_cur_lang(get_lang(uid))
                            await bot.send_message(
                                uid,
                                t("search_timeout", min=SEARCH_TIMEOUT_MIN),
                                reply_markup=main_menu_kb(uid),
                            )
                            set_cur_lang(_sl)
                        except TelegramError:
                            pass
            except Exception as e:
                log.debug("janitor queue: %s", e)

        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("janitor loop: %s", e)


async def _inactive_nudge_loop():
    """Раз в 6 часов: напоминаем неактивным юзерам о боте."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            cutoff = (now_dt() - timedelta(days=INACTIVE_DAYS)).isoformat()
            nudge_cutoff = (now_dt() - timedelta(days=JANITOR_PERIOD_DAYS)).isoformat()
            rows = conn.execute(
                "SELECT tg_id FROM users "
                "WHERE (last_active IS NULL OR last_active<?) "
                "AND (nudged_at IS NULL OR nudged_at<?) LIMIT 500",
                (cutoff, nudge_cutoff),
            ).fetchall()
            for r in rows:
                uid = r["tg_id"]
                try:
                    _sl = cur_lang()
                    set_cur_lang(get_lang(uid))
                    await bot.send_message(uid, t("inactive_nudge"))
                    set_cur_lang(_sl)
                    conn.execute(
                        "UPDATE users SET nudged_at=? WHERE tg_id=?",
                        (now_iso(), uid),
                    )
                    conn.commit()
                except TelegramError:
                    pass
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("nudge loop: %s", e)


# ============================ HEALTH CHECK WEB SERVER ============================
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *a, **kw):
        pass


def start_web_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        boot.info("🌐 Health-check сервер на порту %d", port)
    except Exception as e:
        boot.warning("web server: %s", e)


# ============================ ДЕФОЛТНЫЕ ДАННЫЕ ============================
def init_default_data():
    try:
        if not conn.execute("SELECT 1 FROM star_packages LIMIT 1").fetchone():
            packs = [
                ("50 коинов", 50, 50),
                ("120 коинов", 120, 100),
                ("300 коинов", 300, 200),
                ("700 коинов", 700, 400),
                ("1500 коинов", 1500, 750),
            ]
            for ttl, coins, stars in packs:
                conn.execute(
                    "INSERT INTO star_packages (title, coins, price_stars, active) "
                    "VALUES (?, ?, ?, 1)",
                    (ttl, coins, stars),
                )
            conn.commit()
            log.info("⭐ Добавлены стартовые пакеты коинов")

        if not conn.execute("SELECT 1 FROM shop_items LIMIT 1").fetchone():
            items = [
                ("VIP на 7 дней", "Премиум-статус на 7 дней", 300, 1, 7, "vip", None),
                ("VIP на 30 дней", "Премиум-статус на 30 дней", 1000, 1, 30, "vip", None),
                ("100 коинов", "Пополнение баланса", 150, 0, None, "coins", 100),
                ("Заявка на модера", "Подать заявку на роль модератора",
                 500, 0, None, "manual", None),
            ]
            for ttl, dsc, price, is_vip, days, rt, amt in items:
                conn.execute(
                    "INSERT INTO shop_items "
                    "(title, description, price, is_vip, duration_days, "
                    "reward_type, reward_amount, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (ttl, dsc, price, is_vip, days, rt, amt),
                )
            conn.commit()
            log.info("🛒 Добавлены стартовые товары")
    except Exception as e:
        log.warning("init_default_data: %s", e)


# ============================ BOT COMMANDS ============================
async def set_bot_commands():
    try:
        cmds = [
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="help", description="ℹ️ Помощь"),
            BotCommand(command="menu", description="🏠 Меню"),
            BotCommand(command="cancel", description="❌ Отмена"),
        ]
        await bot.set_my_commands(cmds)
        boot.info("✅ Bot commands set")
    except Exception as e:
        boot.warning("set_my_commands: %s", e)


# ============================ STARTUP / SHUTDOWN ============================
async def on_startup():
    global _BOT_USERNAME
    try:
        boot.info("🚀 Startup…")
        init_db()
        init_default_data()
        try:
            me = await bot.get_me()
            _BOT_USERNAME = me.username
            boot.info("✅ bot username: @%s", _BOT_USERNAME)
        except Exception as e:
            boot.warning("get_me: %s", e)
        await set_bot_commands()
        asyncio.create_task(_janitor_loop())
        asyncio.create_task(_inactive_nudge_loop())
        boot.info("✅ Бот готов к работе")
    except Exception as e:
        boot.exception("startup error: %s", e)
        raise


async def on_shutdown():
    boot.info("🛑 Shutdown…")
    try:
        await bot.session.close()
    except Exception:
        pass


# ============================ MAIN ============================
async def main():
    start_web_server()
    await on_startup()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        boot.info("👋 Бот остановлен")
    except TelegramConflictError as e:
        boot.critical("❌ Конфликт: запущено два экземпляра бота? %s", e)
        raise SystemExit(1)
    except Exception as e:
        boot.exception("💥 Критическая ошибка: %s", e)
        raise SystemExit(1)
