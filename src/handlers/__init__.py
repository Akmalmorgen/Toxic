"""
Handlers package — все хэндлеры бота, разбитые по разделам.

Каждый модуль экспортирует функцию register(dp) для регистрации хэндлеров в Dispatcher.

Модули:
    common   — навигация (nav, clean_screen, go_home), middleware языка
    start    — /start, регистрация, пол, возраст, реферал при первом входе
    roulette — чат-рулетка (поиск, matchmaker, relay, /tg мониторинг)
    anon     — анонимные сообщения (ссылка, отправка, ответы, удаление, раскрытие)
    shop     — магазин (покупка, редактирование, Stars)
    admin    — админ-панель (статистика, бан, VIP, модеры, каналы, рассылка, реклама)
    profile  — профиль, смена пола/возраста, подарки коинов
    referral — рефералы (приглашения, топ, награды)
    eighteen — 18+ раздел (возрастной барьер, рулетка 18+, магазин 18+, подарки)
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register_all(dp: "Dispatcher") -> None:
    """Регистрирует все хэндлеры во всех модулях.

    Вызывается из bot.py при старте.
    Порядок важен: более специфичные хэндлеры регистрируются раньше.
    """
    from . import common, start, roulette, anon, shop, admin, profile, referral, eighteen

    common.register(dp)
    start.register(dp)
    roulette.register(dp)
    anon.register(dp)
    shop.register(dp)
    admin.register(dp)
    profile.register(dp)
    referral.register(dp)
    eighteen.register(dp)
