# main.py — точка входа для хостингов (Render, Railway, VPS)
"""
Preflight-проверка окружения ДО импорта bot.py:
если BOT_TOKEN/ADMIN_IDS не заданы — понятное сообщение вместо сухого трейсбека.
"""
import os
import sys


def _preflight() -> None:
    missing = []
    if not (os.getenv("BOT_TOKEN") or "").strip():
        missing.append("BOT_TOKEN")
    if not (os.getenv("ADMIN_IDS") or "").strip():
        missing.append("ADMIN_IDS")
    if missing:
        print("=" * 60)
        print("❌ ОШИБКА: не заданы переменные окружения:", ", ".join(missing))
        print()
        print("Локально:   cp .env.example .env, потом впиши значения")
        print("Render:     Dashboard → Environment → Add Environment Variable")
        print("Railway:    Project → Variables")
        print("VPS/systemd: Environment=BOT_TOKEN=... в .service файле")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    _preflight()
    from bot import main
    main()
