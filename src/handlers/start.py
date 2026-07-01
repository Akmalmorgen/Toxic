"""
Хэндлеры: /start, регистрация (пол, возраст), реферал при первом входе.

Функции:
- cmd_start() — обработка /start (с deep-link аргументами)
- set_gender_from_text() — выбор/смена пола
- set_age_from_text() — ввод возраста числом
- handle_referral() — начисление за реферала
- deliver_start_menu() — показ приветствия/меню после регистрации
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры старта и регистрации."""
    # TODO: перенести cmd_start, set_gender_from_text, set_age_from_text,
    #       handle_referral, deliver_start_menu из bot.py
    pass
