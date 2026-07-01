"""
Хэндлеры: анонимные сообщения (по ссылке).

Функции:
- handle_incoming_link() — обработка deep-link на анонимку
- on_anon_type_text() — выбор типа (вопрос/валентинка)
- process_anon_content() — отправка контента
- deliver_anon() — универсальная доставка (вопрос/валентинка/ответ)
- on_reply_button() — кнопка «Ответить»
- process_reply_content() — отправка ответа
- on_delete_button() — удаление сообщения
- on_report_anon() — жалоба на анонимку
- on_reveal_button() / on_reveal_pay() — раскрытие отправителя за Stars
- process_report_reason() — выбор причины жалобы
- on_report_admin_decision() — решение модера по жалобе
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register(dp: "Dispatcher") -> None:
    """Регистрирует хэндлеры анонимных сообщений."""
    # TODO: перенести из bot.py
    pass
