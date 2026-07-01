"""
Точка входа модульной архитектуры: создание Bot/Dispatcher, регистрация хэндлеров, запуск.

Этот файл заменит монолитный bot.py после полной миграции хэндлеров.
Пока он работает ПАРАЛЛЕЛЬНО — оригинальный bot.py остаётся рабочим.

Использование (после полной миграции):
    from src.app import main
    main()
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from .config import BOT_TOKEN
from .db import init_db

log = logging.getLogger("anon_bot")


def create_bot() -> Bot:
    """Создаёт экземпляр Bot (без side-effects при импорте)."""
    return Bot(BOT_TOKEN, default=DefaultBotProperties())


def create_dispatcher() -> Dispatcher:
    """Создаёт Dispatcher."""
    return Dispatcher()


def _keep_alive_server() -> None:
    """Мини HTTP-сервер для хостингов (Render и т.п.) — нужен открытый порт."""
    port = int(os.getenv("PORT", "8080"))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:
        log.warning("keep-alive server: %s", e)


async def _run() -> None:
    """Основной asyncio-цикл: инициализация БД, регистрация хэндлеров, polling."""
    init_db()

    bot = create_bot()
    dp = create_dispatcher()

    # Регистрируем все хэндлеры из модулей
    from .handlers import register_all
    register_all(dp)

    # Устанавливаем команды бота
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
        ])
    except Exception as e:
        log.warning("set_my_commands: %s", e)

    # Удаляем вебхук (если был) — иначе polling конфликтует
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    # TODO: запустить фоновые задачи (matchmaker, janitor) через asyncio.create_task
    # asyncio.create_task(_matchmaker_loop(bot))
    # asyncio.create_task(_janitor_loop(bot))

    log.info("Бот запущен (модульная архитектура), поллинг...")
    await dp.start_polling(bot)


def main() -> None:
    """Точка входа: keep-alive сервер + asyncio polling."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Keep-alive в отдельном потоке (Render ждёт открытый PORT)
    threading.Thread(target=_keep_alive_server, daemon=True).start()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
