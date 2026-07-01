"""
Хэндлеры: профиль пользователя.

Функции:
- show_profile() — отображение профиля (статистика, VIP, коины)
- profile_router() — обработка кнопок профиля
- gift_coins_router() — подарок коинов другу
- show_language_menu() / language_router() — смена языка
- show_help() — экран помощи
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры профиля."""
    # TODO: перенести из bot.py
    pass
