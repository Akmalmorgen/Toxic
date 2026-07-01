"""
Хэндлеры: админ-панель (статистика, бан, VIP, модеры, каналы, рассылка, реклама).

Функции:
- show_admin_menu() — отображение админ-панели
- admin_vip_router() — выдать/забрать VIP
- show_admin_moder() / admin_moder_router() — управление модерами
- start_ban() / process_ban() — бан/разбан
- adm_stats_msg() — статистика
- adm_export_msg() — выгрузка пользователей
- adm_channels_msg() / adm_channels_router() — обязательные каналы
- process_bcast_audience_text() / process_bcast_content() — рассылка
- process_adm_ad_wizard() — управление рекламой (CRUD)
- janitor_heavy() / janitor_unreachable_sweep() — автоочистка
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры админ-панели."""
    # TODO: перенести из bot.py
    pass
