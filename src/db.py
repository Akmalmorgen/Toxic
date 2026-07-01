"""
Слой базы данных: подключение (SQLite / PostgreSQL), миграции, индексы, CRUD.

Один и тот же код работает с обоими движками благодаря слою совместимости.
TTL-кэш на get_user() снижает нагрузку в ~4 раза.
"""

from __future__ import annotations

import logging
import os
import re as _re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import DATABASE_URL, DB_PATH, USE_PG

log = logging.getLogger("anon_bot.db")


# ═══════════════════════════════════════════════════════════════════════════════
# СЛОЙ СОВМЕСТИМОСТИ: единый API для sqlite и PostgreSQL (Neon)
# ═══════════════════════════════════════════════════════════════════════════════

if USE_PG:
    import psycopg2

    _pg_lock = threading.RLock()

    class _Row(dict):
        """Унифицированная строка: доступ по имени row['col'] и по индексу row[0]."""
        def __init__(self, cols: list[str], vals: tuple):
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
                idx = self._cols.index("id")
                self._lastrowid = self._rows[0][idx]

        def fetchone(self) -> Optional[_Row]:
            if self._pos >= len(self._rows):
                return None
            r = self._rows[self._pos]
            self._pos += 1
            return _Row(self._cols, r)

        def fetchall(self) -> list[_Row]:
            rows = [_Row(self._cols, r) for r in self._rows[self._pos:]]
            self._pos = len(self._rows)
            return rows

        @property
        def lastrowid(self) -> Optional[int]:
            return self._lastrowid

    def _translate_schema(script: str) -> str:
        s = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        s = _re.sub(r"\bINTEGER\b", "BIGINT", s)
        return s

    class _PgConnection:
        def __init__(self, url: str):
            self.url = url
            self._connect()

        def _connect(self):
            self._conn = psycopg2.connect(
                self.url, connect_timeout=30,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            )
            self._conn.autocommit = True

        def execute(self, sql: str, params: tuple = ()):
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

        def executescript(self, script: str):
            with _pg_lock:
                cur = self._conn.cursor()
                cur.execute(_translate_schema(script))
                return _PgCursor(cur)

        def commit(self):
            pass  # autocommit

        def rollback(self):
            pass

        def cursor(self):
            return self

    conn = _PgConnection(DATABASE_URL)
    log.info("БД: PostgreSQL (Neon)")
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
        log.warning("sqlite pragma skip: %s", _e)
    log.info("БД: sqlite (%s)", DB_PATH)


def db():
    """Возвращает подключение к БД (для прямых запросов)."""
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ СХЕМЫ
# ═══════════════════════════════════════════════════════════════════════════════

def init_db() -> None:
    """Создаёт все таблицы (если не существуют), запускает миграции и индексы."""
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
        ref_code TEXT,
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
        last_message_at TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT
    );
    CREATE TABLE IF NOT EXISTS shop_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        title_uz TEXT,
        title_en TEXT,
        description TEXT,
        price INTEGER NOT NULL,
        is_vip INTEGER NOT NULL DEFAULT 0,
        is_18plus INTEGER NOT NULL DEFAULT 0,
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
        title TEXT,
        added_by INTEGER
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
    CREATE TABLE IF NOT EXISTS link_flow (
        user_id INTEGER PRIMARY KEY,
        target_id INTEGER NOT NULL,
        msg_type TEXT,
        state TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS eighteen_plus_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        title_uz TEXT,
        title_en TEXT,
        description TEXT,
        price INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS age_verification_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        photo_file_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_response TEXT,
        created_at TEXT NOT NULL,
        responded_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS moder_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        moder_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        target_id INTEGER,
        details TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ad_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        button_text TEXT,
        button_url TEXT,
        added_by INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    _migrate()
    _ensure_indexes()


def _migrate() -> None:
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
        "ALTER TABLE users ADD COLUMN ref_code TEXT",
        "ALTER TABLE mandatory_channels ADD COLUMN title TEXT",
        "ALTER TABLE mandatory_channels ADD COLUMN added_by INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE roulette_queue ADD COLUMN actual_age INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN age_min INTEGER",
        "ALTER TABLE roulette_queue ADD COLUMN age_max INTEGER",
        "ALTER TABLE roulette_sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE roulette_sessions ADD COLUMN last_message_at TEXT",
        "ALTER TABLE shop_items ADD COLUMN is_18plus INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE star_packages ADD COLUMN title_uz TEXT",
        "ALTER TABLE star_packages ADD COLUMN title_en TEXT",
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


def _ensure_indexes() -> None:
    """Индексы для горячих запросов."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u1 ON roulette_sessions(active, user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_active_u2 ON roulette_sessions(active, user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_u1 ON roulette_sessions(user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_u2 ON roulette_sessions(user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_to ON anon_messages(to_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_from ON anon_messages(from_id)",
        "CREATE INDEX IF NOT EXISTS idx_anon_parent ON anon_messages(parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
        "CREATE INDEX IF NOT EXISTS idx_reports_reported ON reports(reported_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_pair ON bans(owner_id, banned_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_banned ON bans(banned_id)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
        "CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_starpur_user ON star_purchases(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_refcode ON users(ref_code)",
        "CREATE INDEX IF NOT EXISTS idx_users_lastactive ON users(last_active)",
        "CREATE INDEX IF NOT EXISTS idx_ageverif_status ON age_verification_requests(status)",
        "CREATE INDEX IF NOT EXISTS idx_moderapps_status ON moder_apps(status)",
        "CREATE INDEX IF NOT EXISTS idx_queue_mode ON roulette_queue(mode)",
        "CREATE INDEX IF NOT EXISTS idx_moderlog_moder ON moder_log(moder_id)",
        "CREATE INDEX IF NOT EXISTS idx_moderlog_target ON moder_log(target_id)",
    ]
    created = 0
    for q in indexes:
        try:
            conn.execute(q)
            created += 1
        except Exception as e:
            log.warning("index skip: %s (%s)", q.split(" ON ")[0], e)
    conn.commit()
    log.info("БД: индексы готовы (%d/%d)", created, len(indexes))


# ═══════════════════════════════════════════════════════════════════════════════
# TTL-КЭШ get_user()
# ═══════════════════════════════════════════════════════════════════════════════

_USER_CACHE: dict[int, tuple[Any, float]] = {}
_USER_CACHE_TTL: float = 5.0


def cache_invalidate(tg_id: int) -> None:
    """Инвалидирует кэш пользователя (вызывать при любой записи в users)."""
    _USER_CACHE.pop(tg_id, None)


def get_user(tg_id: int) -> Optional[Any]:
    """Получает пользователя по tg_id (с кэшированием на 5 сек)."""
    now = time.time()
    cached = _USER_CACHE.get(tg_id)
    if cached and cached[1] > now:
        return cached[0]
    row = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    _USER_CACHE[tg_id] = (row, now + _USER_CACHE_TTL)
    return row


def ensure_user(tg_id: int, username: Optional[str], first_name: Optional[str] = None) -> Any:
    """Создаёт или обновляет пользователя, возвращает актуальную строку."""
    from .utils import now_iso  # lazy import для избежания circular
    u = get_user(tg_id)
    if u is None:
        conn.execute(
            "INSERT INTO users (tg_id, username, first_name, coins, created_at) VALUES (?, ?, ?, 0, ?)",
            (tg_id, username, first_name, now_iso()),
        )
        conn.commit()
        cache_invalidate(tg_id)
        u = get_user(tg_id)
    else:
        changed = False
        if u["username"] != username:
            conn.execute("UPDATE users SET username=? WHERE tg_id=?", (username, tg_id))
            changed = True
        if first_name and u["first_name"] != first_name:
            conn.execute("UPDATE users SET first_name=? WHERE tg_id=?", (first_name, tg_id))
            changed = True
        if changed:
            conn.commit()
            cache_invalidate(tg_id)
            u = get_user(tg_id)
    return u


def resolve_user_ref(text: str) -> Optional[int]:
    """Находит пользователя по числовому tg_id или @username. Возвращает tg_id или None."""
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


def touch_user(uid: int) -> None:
    """Отмечает активность пользователя (не чаще раза в час)."""
    from .utils import now_iso, now_dt
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
        cache_invalidate(uid)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS (key-value store)
# ═══════════════════════════════════════════════════════════════════════════════

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    except Exception:
        return default
    return row["value"] if row and row["value"] is not None else default


def get_setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: Any) -> None:
    conn.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
