"""
Общие утилиты хэндлеров: навигация, middleware, try_delete_message.

Содержит функции, используемые ВСЕМИ хэндлерами:
- nav() — единый «экран» (удаляет нажатие + прошлое меню, показывает новое)
- clean_screen() — удаляет нажатую кнопку и доп. сообщения
- send_menu() — отправляет меню и запоминает id для очистки
- go_home() — возврат в главное меню
- track_extra() — запоминает доп. сообщение для удаления
- try_delete_message() — безопасное удаление
- lang_middleware() — middleware для установки языка перед каждым апдейтом
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ..config import State
from ..db import get_user, touch_user
from ..filters import is_banned, is_admin
from ..i18n import set_cur_lang, get_lang, t, cur_lang
from ..keyboards import main_menu_kb

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher


# ═══════════════════════════════════════════════════════════════════════════════
# НАВИГАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

async def try_delete_message(bot: "Bot", chat_id: int, message_id: int) -> None:
    """Безопасное удаление сообщения (не падает при ошибке)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def clean_screen(message: Message, user_data: dict) -> None:
    """Удаляет нажатую пользователем кнопку, доп. сообщения и предыдущее меню."""
    try:
        await message.delete()
    except Exception:
        pass
    bot = message.bot
    chat_id = message.chat.id
    for mid in user_data.pop("extra_msg_ids", []):
        await try_delete_message(bot, chat_id, mid)
    mid = user_data.pop("last_menu_msg_id", None)
    if mid:
        await try_delete_message(bot, chat_id, mid)


def track_extra(user_data: dict, msg: Message) -> None:
    """Запоминает доп. сообщение для удаления при следующей навигации."""
    user_data.setdefault("extra_msg_ids", []).append(msg.message_id)


async def send_menu(bot: "Bot", chat_id: int, user_data: dict,
                    text: str, reply_markup: Any = None, parse_mode: str | None = None) -> Message:
    """Отправляет новое меню и запоминает его id для последующей очистки."""
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    user_data["last_menu_msg_id"] = msg.message_id
    return msg


async def nav(message: Message, user_data: dict,
              text: str, reply_markup: Any = None, parse_mode: str | None = None) -> Message:
    """Единый «экран»: удаляет нажатие и прошлое меню, показывает одно новое сообщение."""
    await clean_screen(message, user_data)
    return await send_menu(message.bot, message.chat.id, user_data, text, reply_markup, parse_mode)


async def go_home(message: Message, user_data: dict) -> None:
    """Возврат в главное меню из любой глубины + очистка."""
    user_data["state"] = None
    await nav(message, user_data, t("main_menu"), main_menu_kb(message.from_user.id))


# ═══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARE: язык + touch_user
# ═══════════════════════════════════════════════════════════════════════════════

class LangMiddleware(BaseMiddleware):
    """Перед каждым апдейтом устанавливает язык пользователя в ContextVar."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            set_cur_lang(get_lang(user.id))
            touch_user(user.id)
        else:
            set_cur_lang("ru")
        return await handler(event, data)


# ═══════════════════════════════════════════════════════════════════════════════
# РЕГИСТРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

def register(dp: "Dispatcher") -> None:
    """Регистрирует middleware и общие обработчики."""
    dp.update.outer_middleware(LangMiddleware())
