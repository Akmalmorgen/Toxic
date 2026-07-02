"""Конфигурация бота: переменные окружения и константы."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# === Основные ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: set[int] = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DATABASE_URL = (
    os.getenv("DATABASE_URL", "").strip()
    or os.getenv("POSTGRES_URL", "").strip()
)
DB_PATH = os.getenv("DB_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")

# === Лимиты и таймеры ===
DAILY_LIMIT = 20
BAN_DAYS = 7
ROULETTE_BAN_DAYS = 30
ANON_BAN_FOREVER = "9999-12-31T23:59:59"
ROULETTE_TICK_SECONDS = 3
SEARCH_TIMEOUT_MIN = 30
SEARCH_REMIND_MIN = 5
LINK_CHANGE_COOLDOWN_DAYS = 7
VIP_DISCOUNT_PERCENT = 20
VIP_DAILY_BONUS = 5

# === Подарок 18+ доступа другу ===
GIFT_18PLUS_PRICE = 567
GIFT_18PLUS_PRICE_VIP = 456
GIFT_18PLUS_DAYS = 30

# === Реферальные награды ===
REF_REWARD_NORMAL = 50
REF_REWARD_VIP = 100
REF_INVITED_BONUS = 100
REF_INVITED_BONUS_VIP = 200
REF_VIP_THRESHOLD = 5
REF_VIP_DAYS = 7
REF_MODER_THRESHOLD = 10
REF_MODER_DAYS = 7
LINK_REWARD_EVERY = 10
LINK_REWARD_COINS = 20

# === Безопасность ===
ADMIN_ACCESS_KEY = os.getenv("ADMIN_ACCESS_KEY", "")
CREATOR_USERNAME = "@ToxIc_0707"

# === Авто-обслуживание (джанитор) ===
INACTIVE_DAYS = 14
JANITOR_WAKE_HOURS = 6
JANITOR_PERIOD_DAYS = 14

# Условный «бесконечный» баланс для отображения у админа/модера
UNLIMITED_COINS = 10 ** 9
