"""
Хэндлеры: чат-рулетка (обычная и 18+).

Функции:
- show_roulette_entry() — точка входа в рулетку
- roulette_pref_router() — выбор предпочтения (пол)
- roulette_matchmaker() — фоновый сведение пар (asyncio task)
- relay_roulette_message() — пересылка сообщений между участниками
- rchat_next() / rchat_stop() — кнопки «Далее» / «Стоп»
- rleft_research() / rleft_report() — кнопки после ухода собеседника
- end_roulette_session() — завершение сессии
- force_end_session() — принудительное завершение (бан/блокировка)
- end_dead_sessions() — очистка зависших
- end_inactive_sessions() — авто-закрытие после 2 мин без сообщений
- queue_maintenance() — авто-стоп долгого поиска (1 мин)
- Мониторинг /tg (attach_spectator, relay_to_spectators, tg_start, on_tg_ban)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры рулетки."""
    # TODO: перенести из bot.py
    pass
