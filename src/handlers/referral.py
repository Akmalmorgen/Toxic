"""
Хэндлеры: рефералы (приглашения, топ, награды).

Функции:
- show_referral() — экран «Пригласить» (ссылка, статистика, кнопки наград)
- referral_router() — обработка кнопок
- show_top() — топ пригласивших
- on_claim_vip() / on_claim_moder() — забрать VIP/модерку за друзей
- reward_link_activity() — бонус за активность по ссылке
- show_ref_settings() / ref_settings_router() — настройки (админ)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры рефералов."""
    # TODO: перенести из bot.py
    pass
