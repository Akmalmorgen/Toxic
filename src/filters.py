"""
Фильтры и проверки пользователей: права, статусы, антиспам.

Все функции принимают user_row (строку из БД) или tg_id и возвращают bool.
Type hints на всех публичных функциях.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from .config import ADMIN_IDS, ADMIN_ACCESS_KEY
from .db import get_user, conn
from .utils import now_dt, safe_get, safe_int


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКИ РОЛЕЙ
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(tg_id: int) -> bool:
    """True если пользователь — администратор (из ADMIN_IDS в .env)."""
    return tg_id in ADMIN_IDS


def is_moder(user_row: Any) -> bool:
    """True если пользователь — модератор (постоянный или временный)."""
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
    """True если пользователь — админ или модератор."""
    if is_admin(tg_id):
        return True
    u = get_user(tg_id)
    return is_moder(u)


def is_banned(user_row: Any) -> bool:
    """True если пользователь заблокирован."""
    return bool(user_row) and bool(user_row["is_banned"])


def is_vip(user_row: Any) -> bool:
    """True если у пользователя активен VIP (или он админ/модер — VIP навсегда)."""
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
    except ValueError:
        return False


def is_unlimited(user_row: Any) -> bool:
    """True если аккаунт безлимитный (админ/модер): бесконечные коины, без ограничений."""
    if not user_row:
        return False
    try:
        return is_admin(user_row["tg_id"]) or is_moder(user_row)
    except (KeyError, TypeError):
        return False


def has_admin_access(tg_id: int) -> bool:
    """Доступ к админ-панели: настоящий админ ИЛИ модер с разблокированным ключом."""
    if is_admin(tg_id):
        return True
    u = get_user(tg_id)
    try:
        return bool(u) and is_moder(u) and bool(u["admin_unlocked"])
    except (KeyError, IndexError, TypeError):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ВОЗРАСТ И 18+
# ═══════════════════════════════════════════════════════════════════════════════

def user_age_int(user_row: Any) -> Optional[int]:
    """Возраст пользователя как число (или None если не задан/нечисловой)."""
    if not user_row:
        return None
    try:
        a = user_row["age"]
    except (KeyError, IndexError, TypeError):
        return None
    if a is None:
        return None
    s = str(a).strip()
    return int(s) if s.isdigit() else None


def is_adult(user_row: Any) -> bool:
    """True если возраст задан и >= 18 (доступ к 18+ разделу)."""
    a = user_age_int(user_row)
    return a is not None and a >= 18


def is_eighteenplus_active(user_row: Any) -> bool:
    """True если у пользователя есть купленный доступ к 18+ чату (или админ/модер)."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# АНТИСПАМ: БЛОКИРОВКА КОНТАКТОВ / РЕКЛАМЫ
# ═══════════════════════════════════════════════════════════════════════════════

def has_forbidden_contacts(text: Optional[str]) -> bool:
    """True если в тексте есть @юзернеймы, ссылки, домены, соцсети или длинные числа (ID/телефон).

    Используется для запрета обмена контактами/рекламы каналов в анонимках и рулетке.
    """
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
    if re.search(
        r'\b[a-z0-9][a-z0-9-]*\.'
        r'(com|ru|uz|net|org|io|me|info|biz|tv|app|link|site|online|club|store|xyz|kz)\b',
        low,
    ):
        return True

    # явные названия соцсетей/мессенджеров
    if re.search(
        r'\b(instagram|insta|tiktok|youtube|youtu|whatsapp|watsap|vatsap|'
        r'facebook|snapchat|discord|onlyfans|vkontakte|'
        r'тикток|инстаграм|ютуб|ватсап|вотсап)\b',
        low,
    ):
        return True

    # длинные числовые последовательности (ID Telegram / номер телефона): 7+ цифр
    for m in re.finditer(r'[\d\s\-()+]{7,}', text):
        if sum(c.isdigit() for c in m.group()) >= 7:
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРНЫЕ БАНЫ (между двумя пользователями)
# ═══════════════════════════════════════════════════════════════════════════════

def is_banned_pair(u1: int, u2: int) -> bool:
    """True если между двумя пользователями есть активный бан (в любую сторону)."""
    from .utils import now_iso
    row = conn.execute(
        "SELECT 1 FROM bans WHERE until>? AND "
        "((owner_id=? AND banned_id=?) OR (owner_id=? AND banned_id=?))",
        (now_iso(), u1, u2, u2, u1),
    ).fetchone()
    return row is not None


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ ДЛЯ РУЛЕТКИ
# ═══════════════════════════════════════════════════════════════════════════════

def compatible(a: Any, b: Any) -> bool:
    """Совместимость двух записей очереди рулетки по полу/предпочтениям."""
    a_ok = a["pref"] == "any" or a["pref"] == b["gender"]
    b_ok = b["pref"] == "any" or b["pref"] == a["gender"]
    return a_ok and b_ok


def age_match(a: Any, b: Any) -> bool:
    """Взаимный фильтр по возрасту для 18+: возраст каждого в диапазоне другого."""
    a_age = safe_int(safe_get(a, "actual_age"))
    b_age = safe_int(safe_get(b, "actual_age"))
    a_min = safe_int(safe_get(a, "age_min")) or 18
    a_max = safe_int(safe_get(a, "age_max")) or 200
    b_min = safe_int(safe_get(b, "age_min")) or 18
    b_max = safe_int(safe_get(b, "age_max")) or 200
    a_ok = (b_age is None) or (a_min <= b_age <= a_max)
    b_ok = (a_age is None) or (b_min <= a_age <= b_max)
    return a_ok and b_ok


# ═══════════════════════════════════════════════════════════════════════════════
# DISPOSABLE (можно ли безопасно удалить аккаунт)
# ═══════════════════════════════════════════════════════════════════════════════

def user_is_disposable(uid: int) -> bool:
    """True если аккаунт «пустой» и его можно безопасно удалить:
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
