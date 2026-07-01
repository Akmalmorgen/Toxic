"""
Клавиатуры бота: все reply- и inline-клавиатуры в одном месте.

Каждая функция возвращает готовую клавиатуру (уже переведённую на текущий язык).
"""

from __future__ import annotations

from typing import Any, Optional

from aiogram.types import (
    KeyboardButton as _KB,
    ReplyKeyboardMarkup as _RKM,
    InlineKeyboardButton as _IKB,
    InlineKeyboardMarkup as _IKM,
)

from .db import conn, get_user, get_setting
from .filters import is_admin, is_moder, is_vip, is_adult
from .i18n import tr_kb, tr_btn, styled, t


# ═══════════════════════════════════════════════════════════════════════════════
# ФАБРИКИ (сокращения для удобства)
# ═══════════════════════════════════════════════════════════════════════════════

def KB(text: str) -> _KB:
    return _KB(text=text)


def RKM(keyboard: list, resize: bool = True, one_time: bool = False) -> _RKM:
    return _RKM(keyboard=keyboard, resize_keyboard=resize, one_time_keyboard=one_time)


def IKB(text: str, **kw) -> _IKB:
    return _IKB(text=text, **kw)


def IKM(rows: list) -> _IKM:
    return _IKM(inline_keyboard=rows)


# ═══════════════════════════════════════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb(tg_id: int) -> _RKM:
    rows = [
        [KB("🔗 Моя ссылка"), KB("🎲 Чат-рулетка")],
        [KB("👤 Профиль"), KB("🛒 Магазин")],
        [KB("👥 Пригласить"), KB("ℹ️ Помощь")],
        [KB("🌐 Язык")],
    ]
    if conn.execute("SELECT 1 FROM star_packages WHERE active=1 LIMIT 1").fetchone():
        star_label = styled(tr_btn("💎 Купить коины"), "premium")
        rows.append([KB(star_label)])
    if is_adult(get_user(tg_id)):
        rows.append([KB("🔞 18+")])
    if is_admin(tg_id):
        rows.append([KB("🛠 Админка")])
    else:
        u = get_user(tg_id)
        if is_moder(u):
            rows.append([KB("🛡 Модерка")])
    return tr_kb(RKM(rows))


# ═══════════════════════════════════════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════════

def admin_menu_kb() -> _RKM:
    enabled = get_setting("18plus_enabled", "1") == "1"
    toggle_label = "🔞 18+ доступ: ВКЛ" if enabled else "🔞 18+ доступ: ВЫКЛ"
    return tr_kb(RKM([
        [KB("📊 Статистика"), KB("📤 Выгрузить пользователей")],
        [KB("💰 Начислить коины"), KB("👑 VIP по ID")],
        [KB("📢 Обязательные каналы"), KB("📣 Реклама")],
        [KB("✉️ Рассылка"), KB("🛡 Модеры")],
        [KB("🔨 Бан / Разбан"), KB("⭐ Коины за Stars")],
        [KB(toggle_label)],
        [KB("⬅️ Назад")],
    ]))


def admin_vip_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("➕ Выдать VIP"), KB("➖ Забрать VIP")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def admin_moder_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("➕ Выдать модера"), KB("➖ Забрать модера")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def star_admin_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("➕ Добавить пакет коинов")],
        [KB("🗑 Удалить пакет коинов")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def ad_menu_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("➕ Добавить рекламу")],
        [KB("📋 Список реклам"), KB("🗑 Удалить рекламу")],
        [KB("📤 Разослать рекламу")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def adm_channels_kb(uid: Optional[int] = None) -> _RKM:
    rows = [
        [KB("➕ Добавить канал")],
        [KB("🗑 Удалить канал")],
    ]
    if uid is not None and is_admin(uid):
        enabled = get_setting("subgate_enabled", "0") == "1"
        toggle = "🔒 Подписка для входа: ВКЛ" if enabled else "🔓 Подписка для входа: ВЫКЛ"
        rows.append([KB(toggle)])
    rows.append([KB("⬅️ Назад"), KB("🏠 Меню")])
    return tr_kb(RKM(rows))


# ═══════════════════════════════════════════════════════════════════════════════
# МОДЕР-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════════

def moder_menu_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("🚩 Жалобы"), KB("🔨 Бан / Разбан")],
        [KB("📊 Статистика"), KB("📤 Выгрузить пользователей")],
        [KB("📢 Обязательные каналы")],
        [KB("ℹ️ Помощь")],
        [KB("⬅️ Назад")],
    ]))


def moder_decision_kb(app_id: int) -> _IKM:
    return IKM([[
        IKB("✅ Выдать", callback_data=f"modapp:ok:{app_id}"),
        IKB("❌ Отказ", callback_data=f"modapp:no:{app_id}"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════════
# ОБЩИЕ КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════════════════════════

def yes_no_kb() -> _RKM:
    return tr_kb(RKM([[KB("✅ Да"), KB("❌ Отмена")]]))


def cancel_reply_kb() -> _RKM:
    return tr_kb(RKM([[KB("❌ Отмена")]]))


def gender_kb(with_back: bool = False) -> _RKM:
    rows = [[KB("👨 Мужской"), KB("👩 Женский")]]
    if with_back:
        rows.append([KB("⬅️ Назад")])
    return tr_kb(RKM(rows))


def language_menu_kb() -> _RKM:
    return RKM([
        [KB("🇷🇺 Русский"), KB("🇺🇿 O'zbekcha")],
        [KB("🇬🇧 English")],
        [KB("⬅️ Назад")],
    ])


def reward_type_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("💎 Коины"), KB("⏳ VIP")],
        [KB("🛡 Модер"), KB("📦 Вручную")],
        [KB("❌ Отмена")],
    ]))


def bcast_audience_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("👥 Всем")],
        [KB("👨 Мужчинам"), KB("👩 Женщинам")],
        [KB("❌ Отмена")],
    ]))


# ═══════════════════════════════════════════════════════════════════════════════
# ССЫЛКА
# ═══════════════════════════════════════════════════════════════════════════════

def link_menu_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("🔗 Показать ссылку"), KB("✏️ Сменить ссылку")],
        [KB("⬅️ Назад")],
    ]))


def link_code_kb() -> _RKM:
    return tr_kb(RKM([[KB("⬅️ Назад")]]))


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОФИЛЬ
# ═══════════════════════════════════════════════════════════════════════════════

def profile_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("✏️ Сменить пол"), KB("✏️ Изменить возраст")],
        [KB("🎁 Подарить коины")],
        [KB("⬅️ Назад")],
    ]))


def age_back_kb() -> _RKM:
    return tr_kb(RKM([[KB("⬅️ Назад")]]))


# ═══════════════════════════════════════════════════════════════════════════════
# АНОНИМКА
# ═══════════════════════════════════════════════════════════════════════════════

def anon_type_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("❓ Вопрос"), KB("💌 Валентинка")],
        [KB("❌ Отмена")],
    ]))


def report_reason_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("🤬 Мат"), KB("💰 Мошенничество")],
        [KB("😡 Оскорбление"), KB("🔞 18+ стикеры")],
        [KB("👎 Не нравится")],
        [KB("❌ Отмена")],
    ]))


# ═══════════════════════════════════════════════════════════════════════════════
# РУЛЕТКА
# ═══════════════════════════════════════════════════════════════════════════════

def roulette_pref_reply_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("👨 Парня"), KB("👩 Девушку"), KB("🤷 Любого")],
        [KB("⬅️ Назад")],
    ]))


def searching_kb() -> _RKM:
    return tr_kb(RKM([[KB("⛔ Отменить поиск")]]))


def in_chat_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("➡️ Далее"), KB("⏹️ Стоп")],
    ]))


def left_chat_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("🔍 Новый поиск")],
        [KB("🚩 Пожаловаться"), KB("⬅️ Назад")],
    ]))


# ═══════════════════════════════════════════════════════════════════════════════
# 18+
# ═══════════════════════════════════════════════════════════════════════════════

def eighteen_plus_menu_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("18+ рулетка"), KB("18+ магазин")],
        [KB("🎁 Подарить 18+")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def eighteen_plus_consent_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("✅ Согласиться")],
        [KB("⬅️ Назад")],
    ]))


def eighteen_plus_verify_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("📷 Отправить фото")],
        [KB("⬅️ Назад")],
    ]))


def eighteen_plus_age_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("18/20"), KB("20/22"), KB("22/25")],
        [KB("25/30"), KB("30+")],
        [KB("🔞 Мне нет 18")],
        [KB("❌ Отмена")],
    ]))


def eighteen_plus_roulette_pref_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("👨 Парня"), KB("👩 Девушку"), KB("🤷 Любого")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


def eighteen_plus_age_search_kb() -> _RKM:
    return tr_kb(RKM([
        [KB("18/20"), KB("20/22"), KB("22/24")],
        [KB("24/26"), KB("26/28"), KB("28/30")],
        [KB("30+"), KB("🤷 Любой возраст")],
        [KB("⬅️ Назад"), KB("🏠 Меню")],
    ]))


# ═══════════════════════════════════════════════════════════════════════════════
# РЕФЕРАЛЫ
# ═══════════════════════════════════════════════════════════════════════════════

def referral_kb(uid: Optional[int] = None) -> _RKM:
    rows = [[KB("🏆 Топ пригласивших")]]
    if uid is not None and is_admin(uid):
        rows.append([KB("✏️ Изменить")])
    rows.append([KB("⬅️ Назад")])
    return tr_kb(RKM(rows))
