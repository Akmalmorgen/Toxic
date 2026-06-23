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
