"""
Хэндлеры: магазин (покупка товаров, редактирование, Stars).

Функции:
- show_shop() / show_eighteen_plus_shop() — отображение магазина
- shop_router() — обработка выбора товара
- shop_confirm_router() — подтверждение покупки
- do_purchase() — выполнение покупки (коины/VIP/модер/18+/manual)
- process_shop_add() — добавление товара (админ)
- shop_edit_router() / process_shop_edit_value() — редактирование товара
- show_star_shop() / star_shop_router() / star_confirm_router() — покупка за Stars
- on_precheckout() / on_successful_payment() — обработка оплаты Telegram Stars
- show_star_admin() / star_admin_router() / process_star_wizard() — управление пакетами
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры магазина."""
    # TODO: перенести из bot.py
    pass
