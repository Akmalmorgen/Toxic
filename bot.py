"""
Анонимный бот: Анон.Вопрос / Валентинка + Чат-рулетка по полу + Магазин (коины, VIP) + Админка.
Стек: python-telegram-bot (PTB) v21, sqlite3 (stdlib).
"""

import os
import sqlite3
import logging
import random
import string
import html
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, LabeledPrice,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, ChatMemberHandler, ContextTypes, filters,
)
from telegram.error import TelegramError, Conflict

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather")

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
        def fetchone(self):
            r = self._raw.fetchone()
            return _Row(self._cols, r) if r is not None else None
        def fetchall(self):
            return [_Row(self._cols, r) for r in self._raw.fetchall()]
        @property
        def lastrowid(self):
            if "id" not in self._cols:
                return None
            idx = self._cols.index("id")
            r = self._raw.fetchone()
            return r[idx] if r else None

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
                self.url, connect_timeout=10,
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
    if not user_row or not user_row["vip_until"]:
        return False
    try:
        return datetime.fromisoformat(user_row["vip_until"]) > now_dt()
    except ValueError:
        return False


def is_admin(tg_id):
    return tg_id in ADMIN_IDS


def gender_label(code):
    return {"m": "Мужской", "f": "Женский"}.get(code, "—")


def pref_label(code):
    return {"m": "Парня", "f": "Девушку", "any": "Любого"}.get(code, "—")


def effective_price(price, user_row):
    """Цена с учётом VIP-скидки."""
    if is_vip(user_row):
        return max(0, round(price * (100 - VIP_DISCOUNT_PERCENT) / 100))
    return price


async def try_delete_message(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass



def main_menu_kb(tg_id):
    rows = [
        [KeyboardButton("🔗 Моя ссылка"), KeyboardButton("🎲 Чат-рулетка")],
        [KeyboardButton("👤 Профиль"), KeyboardButton("🛒 Магазин")],
        [KeyboardButton("👥 Пригласить"), KeyboardButton("ℹ️ Помощь")],
    ]
    # Кнопка покупки коинов за Stars — только если админ добавил хотя бы один пакет
    if conn.execute("SELECT 1 FROM star_packages WHERE active=1 LIMIT 1").fetchone():
        rows.append([KeyboardButton("💎 Купить коины")])
    if is_admin(tg_id):
        rows.append([KeyboardButton("🛠 Админка")])
    else:
        u = get_user(tg_id)
        if is_moder(u):
            rows.append([KeyboardButton("🛡 Модерка")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def yes_no_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("✅ Да"), KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True, one_time_keyboard=True)


def reward_type_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💎 Коины"), KeyboardButton("⏳ VIP")],
        [KeyboardButton("🛡 Модер"), KeyboardButton("📦 Вручную")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True, one_time_keyboard=True)


def admin_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 Статистика"), KeyboardButton("📤 Выгрузить пользователей")],
        [KeyboardButton("💰 Начислить коины"), KeyboardButton("📢 Обязательные каналы")],
        [KeyboardButton("📣 Реклама"), KeyboardButton("✉️ Рассылка")],
        [KeyboardButton("🛡 Модеры"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("⭐ Коины за Stars")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


def star_admin_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить пакет коинов")],
        [KeyboardButton("🗑 Удалить пакет коинов")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


def moder_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚩 Жалобы"), KeyboardButton("🔨 Бан / Разбан")],
        [KeyboardButton("📤 Выгрузить пользователей"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📢 Рассылка")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


def moder_decision_kb(app_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Выдать", callback_data=f"modapp:ok:{app_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"modapp:no:{app_id}"),
    ]])


def gender_kb(with_back=False):
    rows = [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")]]
    if with_back:
        rows.append([KeyboardButton("⬅️ Назад")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def link_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔗 Показать ссылку"), KeyboardButton("✏️ Сменить ссылку")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


def roulette_pref_reply_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("👨 Парня"), KeyboardButton("👩 Девушку"), KeyboardButton("🤷 Любого")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True, one_time_keyboard=True)


def anon_type_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("❓ Вопрос"), KeyboardButton("💌 Валентинка")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True)


def report_reason_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🤬 Мат"), KeyboardButton("💰 Мошенничество")],
        [KeyboardButton("😡 Оскорбление"), KeyboardButton("🔞 18+ стикеры")],
        [KeyboardButton("👎 Не нравится")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True)


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
    return ReplyKeyboardMarkup([
        [KeyboardButton("✏️ Сменить пол")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


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
        await context.bot.send_message(uid, f"🎁 Ежедневный VIP-бонус: <b>+{VIP_DAILY_BONUS}</b> 💎", parse_mode="HTML")
    except TelegramError:
        pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    existed = get_user(tg_user.id) is not None
    user = ensure_user(tg_user.id, tg_user.username, tg_user.first_name)
    if is_banned(user):
        await update.message.reply_text("🚫 Вы заблокированы и не можете пользоваться ботом.")
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
            f"✨ <b>ДОБРО ПОЖАЛОВАТЬ, {html.escape(name)}!</b> 🔥\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <b>ToxIcUz</b> 💙 — <i>твой личный бот для весёлого общения и тайных признаний.</i>\n\n"
            "💎 <b>Что умеет бот:</b>\n"
            "<blockquote>├ принимать вопросы и валентинки анонимно\n"
            "├ искать собеседника в рулетке\n"
            "└ держать всё в тайне</blockquote>\n"
            "👑 Чтобы продолжить, укажите свой пол:",
            parse_mode="HTML",
            reply_markup=gender_kb(),
        )
        return

    await update.message.reply_text(
        "Главное меню 👇", reply_markup=main_menu_kb(tg_user.id)
    )


async def set_gender_from_text(update, context):
    """Обработка выбора/смены пола через reply-клавиатуру."""
    text = update.message.text
    state = context.user_data.get("state")
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(update.effective_user.id))
        return
    gender = {"👨 Мужской": "m", "👩 Женский": "f"}.get(text)
    if not gender:
        await update.message.reply_text("Выберите вариант на клавиатуре 👇", reply_markup=gender_kb(state == "set_gender_profile"))
        return
    conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (gender, update.effective_user.id))
    conn.commit()
    context.user_data["state"] = None
    await update.message.reply_text(
        f"✅ Готово! Ваш пол: <b>{gender_label(gender)}</b>\n\nГлавное меню 👇",
        parse_mode="HTML",
        reply_markup=main_menu_kb(update.effective_user.id),
    )



async def on_gender_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gender = query.data.split(":")[1]
    conn.execute("UPDATE users SET gender=? WHERE tg_id=?", (gender, query.from_user.id))
    conn.commit()
    await query.edit_message_text(f"Пол сохранён: {gender_label(gender)} ✅")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="Главное меню 👇",
        reply_markup=main_menu_kb(query.from_user.id),
    )


async def on_back_main(update, context):
    query = update.callback_query
    await query.answer()
    await try_delete_message(context, query.message.chat_id, query.message.message_id)
    await context.bot.send_message(
        query.from_user.id,
        "Главное меню 👇",
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
            return False, f"Ссылку можно сменить через {days_left} дн. Или купи VIP для снятия ограничения 👑"
    except ValueError:
        return True, None



async def show_link_menu(update, context):
    await clean_screen(update, context)
    context.user_data["state"] = "link_menu"
    await send_menu(update, context, "🔗 <b>Раздел «Моя ссылка»</b>\n\nВыберите действие 👇", link_menu_kb(), parse_mode="HTML")


async def link_menu_router(update, context):
    text = update.message.text
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(update.effective_user.id))
        return
    if text == "🔗 Показать ссылку":
        await show_my_link(update, context)
        return
    if text == "✏️ Сменить ссылку":
        await start_change_link(update, context)
        return
    await update.message.reply_text("Выберите действие на клавиатуре 👇", reply_markup=link_menu_kb())


async def show_my_link(update, context):
    user = get_user(update.effective_user.id)
    if not user["custom_link"]:
        context.user_data["state"] = "awaiting_link_code"
        await update.message.reply_text(
            "У вас ещё нет ссылки.\nПридумайте код (до 10 символов: латиница, цифры, «-», «_»):",
            reply_markup=cancel_reply_kb(),
        )
        return
    bot_username = (await context.bot.get_me()).username
    link = f"t.me/{bot_username}?start={user['custom_link']}"
    await update.message.reply_text(
        "🔗 <b>Ваша персональная ссылка:</b>\n"
        f"<blockquote>{html.escape(link)}</blockquote>"
        "<i>Делитесь ей — вам будут писать анонимно</i> 💌",
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
        "Придумайте новый код (до 10 символов: латиница, цифры, «-», «_»).\n"
        "Старая ссылка сразу перестанет работать.",
        reply_markup=cancel_reply_kb(),
    )


async def process_link_code(update, context, code):
    code = (code or "").strip()
    if code == "❌ Отмена":
        context.user_data["state"] = "link_menu"
        await update.message.reply_text("Отменено.", reply_markup=link_menu_kb())
        return
    if not valid_link_code(code):
        await update.message.reply_text(
            "Код должен быть до 10 символов (латиница, цифры, «-», «_»). Попробуйте ещё раз:",
            reply_markup=cancel_reply_kb(),
        )
        return
    exists = conn.execute("SELECT tg_id FROM users WHERE custom_link=?", (code,)).fetchone()
    if exists and exists["tg_id"] != update.effective_user.id:
        await update.message.reply_text("Этот код уже занят, попробуйте другой:", reply_markup=cancel_reply_kb())
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
        "✅ <b>Готово! Ваша ссылка:</b>\n"
        f"<blockquote>{html.escape(link)}</blockquote>",
        parse_mode="HTML",
        reply_markup=link_menu_kb(),
    )


async def handle_incoming_link(update, context, code):
    sender_id = update.effective_user.id
    sender_row = ensure_user(sender_id, update.effective_user.username, update.effective_user.first_name)
    if is_banned(sender_row):
        await update.message.reply_text("🚫 Вы заблокированы и не можете пользоваться ботом.")
        return
    owner = conn.execute("SELECT * FROM users WHERE custom_link=?", (code,)).fetchone()
    if not owner:
        await update.message.reply_text("Эта ссылка недействительна 😕")
        return
    if owner["tg_id"] == sender_id:
        await update.message.reply_text(
            "Это ваша собственная ссылка 🙂 Самому себе писать нельзя.",
            reply_markup=main_menu_kb(sender_id),
        )
        return
    ban = conn.execute(
        "SELECT * FROM bans WHERE owner_id=? AND banned_id=? AND until>?",
        (owner["tg_id"], sender_id, now_iso()),
    ).fetchone()
    if ban:
        await update.message.reply_text("Вы временно не можете писать этому пользователю 🚫")
        return
    context.user_data["state"] = "awaiting_anon_type"
    context.user_data["anon_target"] = owner["tg_id"]
    await update.message.reply_text("Что хотите отправить?", reply_markup=anon_type_kb())



async def on_anon_type_text(update, context):
    text = update.message.text
    if text == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("anon_target", None)
        await update.message.reply_text(
            "Отменено. Главное меню 👇",
            reply_markup=main_menu_kb(update.effective_user.id)
        )
        return
    if text == "❓ Вопрос":
        msg_type = "question"
    elif text == "💌 Валентинка":
        msg_type = "valentine"
    else:
        await update.message.reply_text("Выбери один из вариантов:", reply_markup=anon_type_kb())
        return
    context.user_data["anon_type"] = msg_type
    context.user_data["state"] = "awaiting_anon_content"
    label = "вопрос" if msg_type == "question" else "валентинку"
    await update.message.reply_text(
        f"Напишите ваш {label} текстом или отправьте голосовое сообщение:",
        reply_markup=ReplyKeyboardRemove()
    )


# Заголовки доставляемого анонимного сообщения по типу
ANON_HEADERS = {
    "question": "📩 <b>Вам пришёл анонимный вопрос</b>",
    "valentine": "💌 <b>Вам пришла анонимная валентинка</b>",
    "reply": "💬 <b>Вам ответили</b>",
}


# Превью содержимого сообщения для цитаты в треде
def anon_preview(row):
    if not row:
        return ""
    if row["content_type"] == "text" and row["text"]:
        p = row["text"]
    elif row["content_type"] == "voice":
        p = "🎤 голосовое сообщение"
    else:
        p = "📎 медиа"
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

    # Цитата родительского сообщения — чтобы не путаться, на что отвечают
    quote = ""
    if parent_id:
        parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (parent_id,)).fetchone()
        prev = anon_preview(parent)
        if prev:
            quote = f"↩️ <i>в ответ на:</i>\n<blockquote>{html.escape(prev)}</blockquote>\n"

    badge = "👑 " if vip_badge else ""
    header = badge + ANON_HEADERS.get(msg_type, "📩 <b>Новое анонимное сообщение</b>")
    buttons = [[InlineKeyboardButton("✍️ Ответить", callback_data=f"reply:{mid}")]]
    if allow_report:
        buttons.append([InlineKeyboardButton("🚩 Пожаловаться", callback_data=f"report_anon:{mid}")])
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
        return None

    conn.execute("UPDATE anon_messages SET owner_chat_message_id=? WHERE id=?", (sent.message_id, mid))
    conn.commit()

    # Подтверждение автору + кнопка удаления (сотрёт обе копии)
    del_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{mid}")]])
    try:
        author_msg = await context.bot.send_message(author_id, "✅ Отправлено", reply_markup=del_kb)
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
                "📷 Фото/стикеры/гиф/видео могут отправлять только VIP 👑 (см. Магазин).\n"
                "Отправь текст или голосовое.",
            )
            return None
        return "media", None, None
    await update.message.reply_text("Поддерживается текст, голосовое" + (", фото, стикеры, гиф, видео" if is_v else "") + ".")
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
                f"Лимит {DAILY_LIMIT} сообщений в сутки исчерпан. "
                "VIP снимает это ограничение 👑 (см. Магазин).",
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
            sender.id, "Не удалось доставить сообщение получателю 😕", reply_markup=main_menu_kb(sender.id)
        )
        return
    await context.bot.send_message(sender.id, "Главное меню 👇", reply_markup=main_menu_kb(sender.id))


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
            "Напиши ответ (текст или голосовое):",
            reply_to_message_id=reply_to,
        )
    except TelegramError:
        await context.bot.send_message(query.from_user.id, "Напиши ответ (текст или голосовое):")



async def process_reply_content(update, context):
    replier = update.effective_user
    replier_row = ensure_user(replier.id, replier.username, replier.first_name)
    msg_id = context.user_data.get("reply_target_msg")
    parent = conn.execute("SELECT * FROM anon_messages WHERE id=?", (msg_id,)).fetchone()
    if not parent:
        await update.message.reply_text("Сообщение не найдено.", reply_markup=main_menu_kb(replier.id))
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
        await update.message.reply_text("Не удалось доставить ответ 😕", reply_markup=main_menu_kb(replier.id))
        return
    await update.message.reply_text("Ответ отправлен ✅", reply_markup=main_menu_kb(replier.id))



async def get_mandatory_channels():
    return conn.execute("SELECT * FROM mandatory_channels").fetchall()


async def user_subscribed_all(context, user_id, channels):
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["chat_username"], user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
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
            text = "Чтобы удалить сообщение, подпишись на канал(ы):\n\n"
            text += "\n".join(f"https://t.me/{c['chat_username'].lstrip('@')}" for c in channels)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Я подписался, проверить", callback_data=f"subcheck:{msg_id}")]])
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
        await query.message.reply_text("Подписка не найдена, проверь ещё раз 🙏")
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
            await query.answer("Сообщение устарело (нет в базе) — удалено только у тебя.", show_alert=True)
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
    try:
        if deleted_recipient:
            await query.answer("Удалено у обоих ✅", show_alert=True)
        else:
            await query.answer("Удалено у тебя. У собеседника не вышло (старше 48ч?).", show_alert=True)
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
    await query.message.reply_text("Выбери причину жалобы:", reply_markup=report_reason_kb())


async def process_report_reason(update, context):
    text = update.message.text
    if text == "❌ Отмена":
        context.user_data["state"] = None
        context.user_data.pop("report_context", None)
        context.user_data.pop("report_ref_id", None)
        context.user_data.pop("reported_id", None)
        await update.message.reply_text(
            "Жалоба отменена.",
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
        await update.message.reply_text("Выбери один из вариантов:", reply_markup=report_reason_kb())
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
        "Жалоба отправлена админу на рассмотрение 🚩",
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
            InlineKeyboardButton("✅ Подтвердить (бан 7 дн.)", callback_data=f"repadm:ok:{report_id}"),
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
            InlineKeyboardButton("✅ Подтвердить (бан 7 дн.)", callback_data=f"repadm:ok:{report_id}"),
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
        await query.answer("Только для модерации.", show_alert=True)
        return
    _, decision, report_id = query.data.split(":")
    report_id = int(report_id)
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not report or report["status"] != "pending":
        await query.edit_message_text("Жалоба уже обработана.")
        return
    if decision == "ok":
        until = (now_dt() + timedelta(days=BAN_DAYS)).isoformat()
        conn.execute(
            "INSERT INTO bans (owner_id, banned_id, until, created_at) VALUES (?, ?, ?, ?)",
            (report["reporter_id"], report["reported_id"], until, now_iso()),
        )
        conn.execute("UPDATE reports SET status='confirmed' WHERE id=?", (report_id,))
        conn.commit()
        try:
            await context.bot.send_message(
                report["reporter_id"], f"Жалоба подтверждена. Отправитель заблокирован на {BAN_DAYS} дней ✅"
            )
        except TelegramError:
            pass
        await query.edit_message_text("Жалоба подтверждена, бан выдан ✅")
    else:
        conn.execute("UPDATE reports SET status='rejected' WHERE id=?", (report_id,))
        conn.commit()
        try:
            await context.bot.send_message(report["reporter_id"], "Жалоба отклонена администратором.")
        except TelegramError:
            pass
        await query.edit_message_text("Жалоба отклонена ❌")



async def show_profile(update, context):
    user = get_user(update.effective_user.id)
    vip_status = "—"
    if is_vip(user):
        vip_status = f"до {user['vip_until'][:10]} 👑"
    text = (
        "👤 <b>Ваш профиль</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>"
        f"Пол: <b>{gender_label(user['gender'])}</b>\n"
        f"Поиск в рулетке: <b>{pref_label(user['search_pref']) if user['search_pref'] else '—'}</b>\n"
        f"Коины: <b>{user['coins']}</b> 💎\n"
        f"VIP: <b>{vip_status}</b>"
        "</blockquote>"
    )
    await clean_screen(update, context)
    context.user_data["state"] = "profile"
    await send_menu(update, context, text, profile_kb(), parse_mode="HTML")


async def profile_router(update, context):
    text = update.message.text
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(update.effective_user.id))
        return
    if text == "✏️ Сменить пол":
        context.user_data["state"] = "set_gender_profile"
        await clean_screen(update, context)
        await send_menu(update, context, "Выберите новый пол:", gender_kb(with_back=True))
        return
    await context.bot.send_message(update.effective_chat.id, "Выберите действие на клавиатуре 👇", reply_markup=profile_kb())


def roulette_pref_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👨 Парня", callback_data="rpref:m"),
        InlineKeyboardButton("👩 Девушку", callback_data="rpref:f"),
        InlineKeyboardButton("🤷 Любого", callback_data="rpref:any"),
    ]])


def searching_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("⛔ Отменить поиск")]], resize_keyboard=True)


def cancel_reply_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True, one_time_keyboard=True)


def bcast_audience_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("👥 Всем")],
        [KeyboardButton("👨 Мужчинам"), KeyboardButton("👩 Женщинам")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True, one_time_keyboard=True)


def in_chat_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующий", callback_data="roulette_next")],
        [InlineKeyboardButton("⛔ Стоп", callback_data="roulette_stop")]
    ])


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
        await context.bot.send_message(update.effective_chat.id, "Вы уже в чате. Пишите собеседнику или используйте кнопки ниже 👇", reply_markup=in_chat_kb())
        return
    in_queue = conn.execute("SELECT 1 FROM roulette_queue WHERE user_id=?", (user["tg_id"],)).fetchone()
    if in_queue:
        await context.bot.send_message(update.effective_chat.id, "Идёт поиск собеседника… ⏳", reply_markup=searching_kb())
        return
    context.user_data["state"] = "roulette_pref"
    await send_menu(update, context, "🎲 Кого вы хотите найти?", roulette_pref_reply_kb())


async def roulette_pref_router(update, context):
    text = update.message.text
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(update.effective_user.id))
        return
    pref = {"👨 Парня": "m", "👩 Девушку": "f", "🤷 Любого": "any"}.get(text)
    if not pref:
        await context.bot.send_message(update.effective_chat.id, "Выберите вариант на клавиатуре 👇", reply_markup=roulette_pref_reply_kb())
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
    await context.bot.send_message(update.effective_chat.id, "Идёт поиск собеседника… ⏳", reply_markup=searching_kb())


async def on_roulette_cancel(update, context):
    query = update.callback_query
    await query.answer()
    conn.execute("DELETE FROM roulette_queue WHERE user_id=?", (query.from_user.id,))
    conn.commit()
    await query.edit_message_text("Поиск отменён.")
    await context.bot.send_message(query.from_user.id, "Главное меню 👇", reply_markup=main_menu_kb(query.from_user.id))


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
                        await context.bot.send_message(uid, "Собеседник найден! 🎉 Пиши смело.", reply_markup=in_chat_kb())
                    except TelegramError:
                        pass
                break


async def end_roulette_session(context, ender_id, requeue_ender=False):
    session = get_active_session(ender_id)
    if not session:
        return
    other_id = session["user2_id"] if session["user1_id"] == ender_id else session["user1_id"]
    conn.execute(
        "UPDATE roulette_sessions SET active=0, ended_by=?, ended_at=? WHERE id=?",
        (ender_id, now_iso(), session["id"]),
    )
    conn.commit()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚩 Жалоба на собеседника", callback_data=f"rrep:{session['id']}")]])
    try:
        await context.bot.send_message(other_id, "Собеседник покинул чат.", reply_markup=kb)
        await context.bot.send_message(other_id, "Главное меню 👇", reply_markup=main_menu_kb(other_id))
    except TelegramError:
        pass
    if requeue_ender:
        user = get_user(ender_id)
        conn.execute(
            "INSERT INTO roulette_queue (user_id, gender, pref, is_vip, joined_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET gender=excluded.gender, pref=excluded.pref, is_vip=excluded.is_vip, joined_at=excluded.joined_at",
            (ender_id, user["gender"], user["search_pref"] or "any", 1 if is_vip(user) else 0, now_iso()),
        )
        conn.commit()


async def on_roulette_next(update, context):
    query = update.callback_query
    await query.answer("Ищем нового собеседника...")
    await end_roulette_session(context, query.from_user.id, requeue_ender=True)
    await context.bot.send_message(query.from_user.id, "Ищем нового собеседника… ⏳", reply_markup=searching_kb())


async def on_roulette_stop(update, context):
    query = update.callback_query
    await query.answer("Чат завершён")
    await end_roulette_session(context, query.from_user.id, requeue_ender=False)
    await context.bot.send_message(query.from_user.id, "Чат завершён.", reply_markup=main_menu_kb(query.from_user.id))



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
    if not session or not session["ended_by"]:
        return
    reporter_id = query.from_user.id
    reported_id = session["ended_by"]
    if reporter_id == reported_id:
        return
    context.user_data["state"] = "awaiting_report_reason"
    context.user_data["report_context"] = "roulette"
    context.user_data["report_ref_id"] = session_id
    context.user_data["reported_id"] = reported_id
    await query.message.reply_text("Выбери причину жалобы:", reply_markup=report_reason_kb())


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
    text = "🛒 <b>Магазин</b>\nВыберите товар 👇" if items else "🛒 <b>Магазин пока пуст.</b>"
    await nav(update, context, text, ReplyKeyboardMarkup(rows, resize_keyboard=True), parse_mode="HTML")


async def shop_router(update, context):
    text = update.message.text
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(uid))
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
        await nav(update, context, "Выберите товар на клавиатуре 👇", ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True))
        return
    item = conn.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        await nav(update, context, "Товар недоступен.", main_menu_kb(uid))
        return
    context.user_data["pending_item"] = item_id
    context.user_data["state"] = "shop_confirm"
    price = effective_price(item["price"], get_user(uid))
    if price != item["price"]:
        price_txt = f"<b>{price}</b> 💎 (VIP-скидка, обычно {item['price']})"
    else:
        price_txt = f"<b>{price}</b> 💎"
    await nav(
        update, context,
        f"Купить «<b>{html.escape(item['title'])}</b>» за {price_txt}?",
        yes_no_kb(), parse_mode="HTML",
    )


async def shop_confirm_router(update, context):
    text = update.message.text
    uid = update.effective_user.id
    if text == "❌ Отмена":
        await show_shop(update, context)
        return
    if text != "✅ Да":
        await update.message.reply_text("Выберите 👇", reply_markup=yes_no_kb())
        return
    item_id = context.user_data.get("pending_item")
    item = conn.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        context.user_data["state"] = None
        await update.message.reply_text("Товар недоступен.", reply_markup=main_menu_kb(uid))
        return
    await do_purchase(update, context, item)


async def do_purchase(update, context, item):
    uid = update.effective_user.id
    user = get_user(uid)
    price = effective_price(item["price"], user)
    if user["coins"] < price:
        context.user_data["state"] = None
        await nav(update, context, "Недостаточно коинов 💎", main_menu_kb(uid))
        return
    conn.execute("UPDATE users SET coins = coins - ? WHERE tg_id=?", (price, uid))
    conn.execute(
        "INSERT INTO purchases (user_id, item_id, price_paid, created_at) VALUES (?, ?, ?, ?)",
        (uid, item["id"], price, now_iso()),
    )
    conn.commit()
    user = get_user(uid)
    discount_note = f" (со скидкой VIP, обычно {item['price']})" if price != item["price"] else ""
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"💰 Покупка!\nПользователь: {user_mention(user)}\n"
                f"Товар: {html.escape(item['title'])}\nЦена: {price} 💎{discount_note}",
                parse_mode="HTML",
            )
        except TelegramError:
            pass
    rt = item["reward_type"] or "manual"
    if rt == "manual" and item["is_vip"]:
        rt = "vip"
    if rt == "coins":
        amt = item["reward_amount"] or 0
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (amt, uid))
        conn.commit()
        context.user_data["state"] = None
        await nav(update, context, f"✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b> 💎", main_menu_kb(uid), parse_mode="HTML")
    elif rt == "vip":
        days = item["reward_amount"] or item["duration_days"] or 30
        base = max(now_dt(), datetime.fromisoformat(user["vip_until"])) if user["vip_until"] else now_dt()
        new_until = base + timedelta(days=days)
        conn.execute("UPDATE users SET vip_until=? WHERE tg_id=?", (new_until.isoformat(), uid))
        conn.commit()
        context.user_data["state"] = None
        await nav(update, context, f"✅ <b>Покупка совершена!</b> VIP активен на <b>{days}</b> дн. 👑", main_menu_kb(uid), parse_mode="HTML")
    elif rt == "moder":
        context.user_data["moder_price"] = price
        context.user_data["moder_item_id"] = item["id"]
        context.user_data["moder_app"] = {}
        context.user_data["state"] = "moder_q_gender"
        await nav(
            update, context,
            "📝 <b>Анкета на модератора.</b>\n\nВаш пол?",
            ReplyKeyboardMarkup(
                [[KeyboardButton("👨 Мужской"), KeyboardButton("👩 Женский")], [KeyboardButton("❌ Отмена")]],
                resize_keyboard=True, one_time_keyboard=True,
            ),
            parse_mode="HTML",
        )
    else:  # manual
        context.user_data["state"] = None
        await nav(
            update, context,
            "✅ <b>Покупка совершена!</b> Админ свяжется с вами и выдаст товар.",
            main_menu_kb(uid), parse_mode="HTML",
        )


# ── Анкета модератора ──

async def moder_q_router(update, context):
    state = context.user_data.get("state")
    text = update.message.text
    uid = update.effective_user.id
    if text == "❌ Отмена":
        price = context.user_data.get("moder_price", 0)
        if price:
            conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (price, uid))
            conn.commit()
        context.user_data["state"] = None
        context.user_data.pop("moder_app", None)
        await update.message.reply_text(
            f"Анкета отменена. Коины ({price} 💎) возвращены.",
            reply_markup=main_menu_kb(uid),
        )
        return
    app = context.user_data.setdefault("moder_app", {})
    if state == "moder_q_gender":
        app["gender"] = text
        context.user_data["state"] = "moder_q_age"
        await update.message.reply_text("Сколько вам лет?", reply_markup=cancel_reply_kb())
    elif state == "moder_q_age":
        app["age"] = text
        context.user_data["state"] = "moder_q_tgtime"
        await update.message.reply_text("Сколько времени проводите в Telegram в день?", reply_markup=cancel_reply_kb())
    elif state == "moder_q_tgtime":
        app["tg_time"] = text
        context.user_data["state"] = "moder_q_avail"
        await update.message.reply_text("Сколько готовы уделять боту? Когда вы онлайн?", reply_markup=cancel_reply_kb())
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
        "✅ Анкета отправлена администратору. Ожидайте решения!",
        reply_markup=main_menu_kb(uid),
    )


async def on_moder_app_decision(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("Только для админа.", show_alert=True)
        return
    _, decision, app_id = query.data.split(":")
    app_id = int(app_id)
    app = conn.execute("SELECT * FROM moder_apps WHERE id=?", (app_id,)).fetchone()
    if not app or app["status"] != "pending":
        await query.edit_message_text("Заявка уже обработана.")
        return
    buyer_id = app["user_id"]
    if decision == "ok":
        conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=?", (buyer_id,))
        conn.execute("UPDATE moder_apps SET status='approved' WHERE id=?", (app_id,))
        conn.commit()
        try:
            await context.bot.send_message(
                buyer_id,
                "🎉 <b>Вы теперь Модер!</b> Добро пожаловать в команду.\n"
                "За бонусом напишите админу @ToxIc_0707 — он всё выдаст.",
                parse_mode="HTML",
                reply_markup=main_menu_kb(buyer_id),
            )
        except TelegramError:
            pass
        await query.edit_message_text("✅ Модерка выдана.")
    else:
        conn.execute("UPDATE users SET coins = coins + ? WHERE tg_id=?", (app["price_paid"], buyer_id))
        conn.execute("UPDATE moder_apps SET status='rejected' WHERE id=?", (app_id,))
        conn.commit()
        try:
            await context.bot.send_message(
                buyer_id,
                f"К сожалению, заявка на модера отклонена. Коины ({app['price_paid']} 💎) возвращены.",
            )
        except TelegramError:
            pass
        await query.edit_message_text("❌ Заявка отклонена, коины возвращены.")


async def process_shop_add(update, context):
    state = context.user_data["state"]
    text = update.message.text.strip()
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
    await update.message.reply_text("Выберите товар для изменения 👇", reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


def shop_edit_item_kb(item):
    rows = [[KeyboardButton("📝 Название"), KeyboardButton("💰 Цена")]]
    if item["reward_type"] == "coins":
        rows.append([KeyboardButton("💎 Сумма коинов")])
    elif item["reward_type"] == "vip" or item["is_vip"]:
        rows.append([KeyboardButton("⏳ Срок VIP")])
    rows.append([KeyboardButton("🗑 Удалить товар")])
    rows.append([KeyboardButton("⬅️ Назад")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def shop_edit_router(update, context):
    state = context.user_data.get("state")
    text = update.message.text
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
    text = update.message.text.strip()
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
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Выдать модера"), KeyboardButton("➖ Забрать модера")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


async def show_admin_moder(update, context):
    context.user_data["state"] = "admin_moder"
    await update.message.reply_text("🛡 Управление модерами:", reply_markup=admin_moder_kb())


async def admin_moder_router(update, context):
    text = update.message.text
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
    text = update.message.text.strip()
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
            await context.bot.send_message(target, "🎉 Вам выдана роль модератора! В меню появилась кнопка «🛡 Модерка».", reply_markup=main_menu_kb(target))
        except TelegramError:
            pass
        await update.message.reply_text(f"✅ Модерка выдана пользователю {target}.", reply_markup=admin_moder_kb())
    else:
        conn.execute("UPDATE users SET is_moder=0 WHERE tg_id=?", (target,))
        conn.commit()
        try:
            await context.bot.send_message(target, "Роль модератора снята.", reply_markup=main_menu_kb(target))
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
    text = update.message.text.strip()
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
    text = update.message.text
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu_kb(uid))
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
            InlineKeyboardButton("✅ Бан 7 дн.", callback_data=f"repadm:ok:{r['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"repadm:no:{r['id']}"),
        ]])
        await context.bot.send_message(update.effective_chat.id, body, reply_markup=kb)


async def notify_staff(context, text, reply_markup=None):
    """Уведомление всем админам и модерам."""
    targets = set(ADMIN_IDS)
    for r in conn.execute("SELECT tg_id FROM users WHERE is_moder=1").fetchall():
        targets.add(r["tg_id"])
    for tid in targets:
        try:
            await context.bot.send_message(tid, text, reply_markup=reply_markup)
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
    text = update.message.text
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



async def on_adm_stats(update, context):
    query = update.callback_query
    await query.answer()
    users_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    msgs_count = conn.execute("SELECT COUNT(*) c FROM anon_messages").fetchone()["c"]
    sessions_count = conn.execute("SELECT COUNT(*) c FROM roulette_sessions").fetchone()["c"]
    vip_count = conn.execute("SELECT COUNT(*) c FROM users WHERE vip_until>?", (now_iso(),)).fetchone()["c"]
    await query.message.reply_text(
        f"📊 Статистика:\nПользователей: {users_count}\nАнон-сообщений: {msgs_count}\n"
        f"Сессий рулетки: {sessions_count}\nVIP сейчас: {vip_count}"
    )


async def on_adm_export(update, context):
    query = update.callback_query
    await query.answer()
    rows = conn.execute("SELECT tg_id, username, gender FROM users").fetchall()
    path = os.path.join(os.path.dirname(__file__), "users_export.txt")
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"id={r['tg_id']} | username=@{r['username']} | gender={r['gender']}\n")
    with open(path, "rb") as f:
        await context.bot.send_document(query.from_user.id, document=f)


async def on_adm_coins(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_coins_id"
    await query.message.reply_text("Введи tg_id пользователя:")


async def process_adm_coins_wizard(update, context):
    state = context.user_data["state"]
    text = update.message.text.strip()
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



async def on_adm_channels(update, context):
    query = update.callback_query
    await query.answer()
    channels = await get_mandatory_channels()
    text = "Обязательные каналы:\n" + ("\n".join(c["chat_username"] for c in channels) or "(пусто)")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить канал", callback_data="adm_channel_add")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
    ])
    await query.message.reply_text(text, reply_markup=kb)


async def on_adm_channel_add(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_channel_add"
    await query.message.reply_text("Пришли @username канала:")


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


async def on_admin_menu_callback(update, context):
    query = update.callback_query
    await query.answer()
    await try_delete_message(context, query.message.chat_id, query.message.message_id)
    class FakeMessage:
        def __init__(self, chat_id, user_id):
            self.chat_id = chat_id
            self.message_id = None
    class FakeUpdate:
        def __init__(self, user_id, chat_id):
            self.effective_user = type('User', (), {'id': user_id})()
            self.message = FakeMessage(chat_id, user_id)
    fake_update = FakeUpdate(query.from_user.id, query.message.chat_id)
    await show_admin_menu(fake_update, context)


async def on_adm_ad(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_ad_text"
    context.user_data["ad"] = {}
    await query.message.reply_text("Текст рекламы:")


async def process_adm_ad_wizard(update, context):
    state = context.user_data["state"]
    text = update.message.text.strip()
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
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📤 Отправить всем")], [KeyboardButton("❌ Отмена")]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )


async def process_ad_send(update, context):
    text = update.message.text
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


async def on_adm_broadcast(update, context):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Всем", callback_data="bcast_aud:all"),
        InlineKeyboardButton("Мужчинам", callback_data="bcast_aud:m"),
        InlineKeyboardButton("Женщинам", callback_data="bcast_aud:f"),
    ]])
    await query.message.reply_text("Кому отправить рассылку?", reply_markup=kb)


async def on_bcast_audience(update, context):
    query = update.callback_query
    await query.answer()
    aud = query.data.split(":")[1]
    context.user_data["state"] = "adm_bcast_content"
    context.user_data["bcast_aud"] = aud
    await query.message.reply_text("Отправь сообщение для рассылки (текст/фото/голосовое):")


async def process_bcast_content(update, context):
    uid = update.effective_user.id
    back_kb = admin_menu_kb() if is_admin(uid) else moder_menu_kb()
    if update.message.text == "❌ Отмена":
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
        await nav(update, context, "Покупка коинов пока недоступна.", main_menu_kb(uid))
        return
    smap, rows = {}, []
    for p in pkgs:
        label = f"{p['title']} — ⭐{p['price_stars']}"
        smap[label] = p["id"]
        rows.append([KeyboardButton(label)])
    rows.append([KeyboardButton("⬅️ Назад")])
    context.user_data["star_map"] = smap
    context.user_data["state"] = "star_shop"
    await nav(update, context, "💎 <b>Покупка коинов за Telegram Stars</b>\nВыбери пакет 👇",
              ReplyKeyboardMarkup(rows, resize_keyboard=True), parse_mode="HTML")


async def star_shop_router(update, context):
    text = update.message.text
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(uid))
        return
    pid = context.user_data.get("star_map", {}).get(text)
    if pid is None:
        await update.message.reply_text("Выбери пакет на клавиатуре 👇")
        return
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=? AND active=1", (pid,)).fetchone()
    if not pkg:
        await nav(update, context, "Пакет недоступен.", main_menu_kb(uid))
        return
    context.user_data["star_pending"] = pid
    context.user_data["state"] = "star_confirm"
    await nav(
        update, context,
        f"Купить «<b>{html.escape(pkg['title'])}</b>» ({pkg['coins']} 💎) за <b>⭐{pkg['price_stars']}</b>?",
        yes_no_kb(), parse_mode="HTML",
    )


async def star_confirm_router(update, context):
    text = update.message.text
    uid = update.effective_user.id
    if text == "❌ Отмена":
        await show_star_shop(update, context)
        return
    if text != "✅ Да":
        await update.message.reply_text("Выбери 👇", reply_markup=yes_no_kb())
        return
    pid = context.user_data.get("star_pending")
    pkg = conn.execute("SELECT * FROM star_packages WHERE id=? AND active=1", (pid,)).fetchone()
    if not pkg:
        await nav(update, context, "Пакет недоступен.", main_menu_kb(uid))
        return
    context.user_data["state"] = None
    await context.bot.send_message(
        uid, "💳 Счёт выставлен ниже. Оплати кнопкой или вернись в меню 👇",
        reply_markup=main_menu_kb(uid),
    )
    await context.bot.send_invoice(
        chat_id=uid,
        title=pkg["title"],
        description=f"{pkg['coins']} коинов для бота",
        payload=f"coins:{pkg['id']}",
        provider_token="",       # пусто = Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(pkg["title"], pkg["price_stars"])],
    )


async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    uid = update.effective_user.id
    payload = sp.invoice_payload or ""
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
        f"✅ <b>Оплата прошла!</b> Начислено <b>{coins}</b> 💎",
        parse_mode="HTML", reply_markup=main_menu_kb(uid),
    )
    user = get_user(uid)
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                aid,
                f"⭐ Покупка коинов!\n{user_mention(user)}\n"
                f"Пакет: {html.escape(pkg['title']) if pkg else '-'}\nКоинов: {coins} / Звёзд: {sp.total_amount}",
                parse_mode="HTML",
            )
        except TelegramError:
            pass


# ── Админ: управление пакетами коинов за Stars ──

async def show_star_admin(update, context):
    pkgs = conn.execute("SELECT * FROM star_packages WHERE active=1").fetchall()
    lst = "\n".join(f"• {p['title']} — {p['coins']} 💎 за ⭐{p['price_stars']}" for p in pkgs) or "(пакетов нет)"
    context.user_data["state"] = "star_admin"
    await update.message.reply_text(f"⭐ Пакеты коинов за Stars:\n{lst}", reply_markup=star_admin_kb())


async def star_admin_router(update, context):
    text = update.message.text
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
        await update.message.reply_text("Какой пакет удалить?", reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))
        return
    await update.message.reply_text("Выбери действие 👇", reply_markup=star_admin_kb())


async def process_star_wizard(update, context):
    state = context.user_data.get("state")
    text = update.message.text.strip()
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
        await context.bot.send_message(
            inviter_id,
            f"🎉 По твоей ссылке пришёл друг! Тебе начислено <b>+{reward}</b> 💎",
            parse_mode="HTML",
        )
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
    bonus = " 👑 (VIP-бонус)" if vip else " (у VIP — 50 💎)"
    text = (
        "👥 <b>Приглашай друзей — зарабатывай коины!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"За каждого друга: <b>{reward}</b> 💎{bonus}\n"
        f"Приглашено: <b>{total}</b>\n"
        f"Заработано: <b>{earned}</b> 💎\n\n"
        "🔗 Твоя ссылка:\n"
        f"<blockquote>{html.escape(link)}</blockquote>"
        "⚠️ Если друг заблокирует бота — коины за него спишутся обратно."
    )
    context.user_data["state"] = "referral"
    await nav(update, context, text, referral_kb(), parse_mode="HTML")


def referral_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🏆 Топ пригласивших")],
        [KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)


async def referral_router(update, context):
    text = update.message.text
    uid = update.effective_user.id
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(uid))
        return
    if text == "🏆 Топ пригласивших":
        await show_top(update, context)
        return
    await update.message.reply_text("Выбери действие 👇", reply_markup=referral_kb())


async def show_top(update, context):
    rows = conn.execute(
        "SELECT referrer_id, COUNT(*) c, COALESCE(SUM(coins_awarded),0) s FROM referrals WHERE active=1 "
        "GROUP BY referrer_id ORDER BY c DESC, s DESC LIMIT 10"
    ).fetchall()
    if not rows:
        await nav(update, context, "Пока никто никого не пригласил. Будь первым! 🚀", referral_kb())
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ пригласивших</b>", "━━━━━━━━━━━━━━━━━━━━"]
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
                await context.bot.send_message(
                    ref["referrer_id"],
                    f"⚠️ Приглашённый друг заблокировал бота — <b>{ref['coins_awarded']}</b> 💎 списаны обратно.",
                    parse_mode="HTML",
                )
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
    text = (
        "ℹ️ <b>О боте ToxIcUz</b> 💙\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Бот анонимных сообщений и общения.\n\n"
        "🔗 <b>Моя ссылка</b> — твоя личная ссылка. Делись ей: тебе будут писать "
        "анонимные вопросы и валентинки.\n"
        "🎲 <b>Чат-рулетка</b> — поиск случайного собеседника по полу.\n"
        "👤 <b>Профиль</b> — пол, коины, VIP-статус.\n"
        "🛒 <b>Магазин</b> — трать коины на VIP и товары.\n"
        "👥 <b>Пригласить</b> — зови друзей: +20 💎 (VIP +50 💎).\n"
        "💎 <b>Купить коины</b> — пополнение за Telegram Stars ⭐.\n\n"
        "💎 <b>Коины</b> — внутренняя валюта (за рефералов и покупки).\n"
        "👑 <b>VIP даёт:</b>\n"
        "<blockquote>• без лимита сообщений\n"
        "• скидка 20% в магазине\n"
        "• +5 💎 каждый день\n"
        "• приоритет в рулетке\n"
        "• корона в анонимках\n"
        "• медиа (фото/видео/гиф) в анонимках\n"
        "• безлимитная смена ссылки</blockquote>\n"
        "❓ <b>Как пользоваться:</b>\n"
        "1. Укажи пол.\n"
        "2. Возьми ссылку в «🔗 Моя ссылка» и делись ею.\n"
        "3. Отвечай на анонимки, играй в рулетке, зарабатывай коины."
    )
    await nav(update, context, text, main_menu_kb(uid), parse_mode="HTML")


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = update.message.text if update.message else None
    _u = get_user(update.effective_user.id)
    if _u and is_banned(_u) and not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Вы заблокированы и не можете пользоваться ботом.")
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
    if state == "shop_confirm":
        await shop_confirm_router(update, context)
        return
    if state == "shop":
        await shop_router(update, context)
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
        await nav(update, context, "Поиск отменён. Главное меню 👇", main_menu_kb(update.effective_user.id))
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
    if text == "⬅️ Назад":
        context.user_data["state"] = None
        await nav(update, context, "Главное меню 👇", main_menu_kb(update.effective_user.id))
        return
    await nav(update, context, "Не понял команду. Воспользуйтесь меню 👇", main_menu_kb(update.effective_user.id))


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


async def on_error(update, context):
    """Глобальный обработчик ошибок — чтобы не падать и не спамить трейсбеками."""
    err = context.error
    if isinstance(err, Conflict):
        log.warning("Conflict: бот запущен в нескольких местах. Оставь один инстанс!")
        return
    log.error("Ошибка при обработке апдейта: %s", err)


def main():
    init_db()
    # фоновый веб-сервер (для Render и пр.) — не мешает боту на polling
    threading.Thread(target=_keep_alive_server, daemon=True).start()
    builder = Application.builder().token(BOT_TOKEN)
    # Увеличенные таймауты (помогает при медленной/нестабильной сети)
    builder = builder.connect_timeout(30).read_timeout(30).write_timeout(30).pool_timeout(30)
    app = builder.build()

    # Регистрируем команды бота (помогает клиенту TG с навигацией)
    async def post_init(application):
        await application.bot.set_my_commands([("start", "Запустить бота")])

    app.post_init = post_init

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_error_handler(on_error)
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(on_back_main, pattern=r"^back_main$"))
    app.add_handler(CallbackQueryHandler(on_reply_button, pattern=r"^reply:"))
    app.add_handler(CallbackQueryHandler(on_delete_button, pattern=r"^del:"))
    app.add_handler(CallbackQueryHandler(on_subcheck_button, pattern=r"^subcheck:"))
    app.add_handler(CallbackQueryHandler(on_report_anon, pattern=r"^report_anon:"))
    app.add_handler(CallbackQueryHandler(on_report_admin_decision, pattern=r"^repadm:"))
    app.add_handler(CallbackQueryHandler(on_roulette_cancel, pattern=r"^roulette_cancel$"))
    app.add_handler(CallbackQueryHandler(on_roulette_next, pattern=r"^roulette_next$"))
    app.add_handler(CallbackQueryHandler(on_roulette_stop, pattern=r"^roulette_stop$"))
    app.add_handler(CallbackQueryHandler(on_roulette_report, pattern=r"^rrep:"))
    app.add_handler(CallbackQueryHandler(on_moder_app_decision, pattern=r"^modapp:"))
    media_filter = (
        filters.VOICE | filters.PHOTO | filters.Sticker.ALL | filters.ANIMATION
        | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL
    )
    app.add_handler(MessageHandler(media_filter, media_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.job_queue.run_repeating(roulette_matchmaker, interval=ROULETTE_TICK_SECONDS, first=ROULETTE_TICK_SECONDS)
    log.info("Бот запущен, поллинг...")
    app.run_polling()


if __name__ == "__main__":
    main()
