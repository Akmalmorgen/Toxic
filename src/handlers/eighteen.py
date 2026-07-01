"""
Хэндлеры: 18+ раздел (возрастной барьер, рулетка, магазин, подарки).

Функции:
- eighteen_plus_menu() — меню 18+ (с проверками возраста/доступа)
- eighteen_plus_consent_router() — согласие с правилами
- eighteen_plus_age_router() — выбор возраста
- eighteen_plus_menu_router() — обработка кнопок 18+ меню
- show_eighteen_plus_roulette() — рулетка 18+
- eighteen_plus_pref_router() — выбор пола в 18+ рулетке
- eighteen_plus_age_search_router() — выбор возрастного диапазона
- start_gift_18plus() / gift_18plus_router() — подарок 18+ доступа другу
- on_age_verify_decision() — решение по верификации возраста
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры 18+ раздела."""
    # TODO: перенести из bot.py
    pass
