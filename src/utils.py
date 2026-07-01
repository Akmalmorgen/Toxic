"""
Утилиты бота: время, безопасные хелперы, аудит-лог, антифлуд, перевод.

Все вспомогательные функции, не привязанные к конкретному модулю.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import (
    CB_COOLDOWN,
    ROULETTE_MSG_LIMIT,
    ROULETTE_MSG_WINDOW,
)

log = logging.getLogger("anon_bot.utils")


# ═══════════════════════════════════════════════════════════════════════════════
# ВРЕМЯ
# ═══════════════════════════════════════════════════════════════════════════════

def now_iso() -> str:
    """Текущее UTC-время в ISO формате."""
    return datetime.utcnow().isoformat()


def now_dt() -> datetime:
    """Текущее UTC-время как datetime."""
    return datetime.utcnow()


def fmt_duration(seconds: int | float, lang: str = "ru") -> str:
    """Человекочитаемая длительность."""
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    hu = {"ru": "ч", "uz": "soat", "en": "h"}.get(lang, "h")
    mu = {"ru": "мин", "uz": "daq", "en": "min"}.get(lang, "min")
    if h > 0:
        return f"{h} {hu} {m} {mu}"
    return f"{m} {mu}"


# ═══════════════════════════════════════════════════════════════════════════════
# БЕЗОПАСНЫЕ ХЕЛПЕРЫ
# ═══════════════════════════════════════════════════════════════════════════════

def safe_get(row: Any, key: str, default: Any = None) -> Any:
    """Безопасно получает значение из row[key].

    Заменяет повторяющийся паттерн:
        try:
            val = row[key]
        except (KeyError, IndexError, TypeError):
            val = default

    Работает с dict, sqlite3.Row, и любым объектом с __getitem__.
    """
    if row is None:
        return default
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Безопасно конвертирует значение в int."""
    if value is None:
        return default
    try:
        s = str(value).strip()
        return int(s) if s.isdigit() else default
    except (ValueError, TypeError):
        return default


def escape_html(text: str) -> str:
    """Shortcut для html.escape."""
    return html.escape(text) if text else ""


# ═══════════════════════════════════════════════════════════════════════════════
# АУДИТ-ЛОГ МОДЕРАТОРА
# ═══════════════════════════════════════════════════════════════════════════════

def audit_log(moder_id: int, action: str, target_id: Optional[int] = None,
              details: Optional[str] = None) -> None:
    """Записывает действие модератора/админа в аудит-лог.

    action: 'ban', 'unban', 'report_confirm', 'report_reject', 'vip_grant',
            'vip_revoke', 'moder_grant', 'moder_revoke', 'tg_ban',
            'broadcast', 'ad_create', 'ad_delete', 'ad_broadcast'.
    """
    from .db import conn  # lazy import — избегаем circular
    try:
        conn.execute(
            "INSERT INTO moder_log (moder_id, action, target_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (moder_id, action, target_id, details, now_iso()),
        )
        conn.commit()
    except Exception as e:
        log.warning("audit_log: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# АНТИФЛУД (rate-limit)
# ═══════════════════════════════════════════════════════════════════════════════

_THROTTLE_CB: dict[int, float] = {}
_THROTTLE_MSG: dict[int, list[float]] = defaultdict(list)


def throttle_callback(uid: int) -> bool:
    """True если нужно заблокировать (слишком частые callback-нажатия)."""
    now = time.time()
    last = _THROTTLE_CB.get(uid, 0)
    if now - last < CB_COOLDOWN:
        return True
    _THROTTLE_CB[uid] = now
    return False


def throttle_roulette_msg(uid: int) -> bool:
    """True если пользователь превысил лимит сообщений в рулетке (30/мин)."""
    now = time.time()
    ts_list = _THROTTLE_MSG[uid]
    cutoff = now - ROULETTE_MSG_WINDOW
    while ts_list and ts_list[0] < cutoff:
        ts_list.pop(0)
    if len(ts_list) >= ROULETTE_MSG_LIMIT:
        return True
    ts_list.append(now)
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ПЕРЕВОД (Google Translate бесплатный эндпоинт)
# ═══════════════════════════════════════════════════════════════════════════════

def _translate_sync(text: str, target: str) -> str:
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
    except Exception as e:
        log.warning("translate(%s): %s", target, e)
        return text


async def translate_to_all(text: str) -> tuple[str, str, str]:
    """Возвращает (ru, uz, en) для текста на любом языке. Не блокирует event loop."""
    ru = await asyncio.to_thread(_translate_sync, text, "ru")
    uz = await asyncio.to_thread(_translate_sync, text, "uz")
    en = await asyncio.to_thread(_translate_sync, text, "en")
    return ru or text, uz or text, en or text


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОЧИЕ УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def user_mention(user_row: Any) -> str:
    """Кликабельная ссылка на пользователя: @username или ID через tg://."""
    if not user_row:
        return "—"
    name = safe_get(user_row, "first_name") or "пользователь"
    username = safe_get(user_row, "username")
    if username:
        return f"{escape_html(name)} (@{username})"
    tg_id = safe_get(user_row, "tg_id", 0)
    return f'<a href="tg://user?id={tg_id}">{escape_html(name)}</a> (ID: {tg_id})'


def effective_price(price: int, user_row: Any) -> int:
    """Цена с учётом VIP-скидки."""
    from .config import VIP_DISCOUNT_PERCENT
    from .filters import is_vip
    if is_vip(user_row):
        return max(0, round(price * (100 - VIP_DISCOUNT_PERCENT) / 100))
    return price


def is_valid_btn_url(url: str) -> bool:
    """Проверяет, годится ли URL для инлайн-кнопки Telegram."""
    if not url or any(ch.isspace() for ch in url):
        return False
    low = url.lower()
    return low.startswith("https://") or low.startswith("http://") or low.startswith("tg://")


def progress_bar(cur: int, target: int, slots: int = 10) -> str:
    """Текстовый прогресс-бар: 🟩 заполнено, ⬜ осталось."""
    if target <= 0:
        return ""
    filled = max(0, min(slots, round(slots * cur / target)))
    return "🟩" * filled + "⬜" * (slots - filled)
