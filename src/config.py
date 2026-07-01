"""
Конфигурация бота: константы, .env-переменные, Enum состояний FSM.

Все захардкоженные значения вынесены сюда.
Секреты читаются из .env (через python-dotenv).
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Set

from dotenv import load_dotenv

load_dotenv()

# ─── Секреты и подключения ───────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: Set[int] = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
ADMIN_ACCESS_KEY: str = os.getenv("ADMIN_ACCESS_KEY", "next_toxic")
DATABASE_URL: str = (
    os.getenv("DATABASE_URL", "").strip()
    or os.getenv("POSTGRES_URL", "").strip()
    or os.getenv("NEON_DATABASE_URL", "").strip()
)
DB_PATH: str = os.getenv("DB_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")
USE_PG: bool = bool(DATABASE_URL)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather")

# ─── Лимиты и таймауты ──────────────────────────────────────────────────────
DAILY_LIMIT: int = 20
BAN_DAYS: int = 7
ROULETTE_BAN_DAYS: int = 30
ANON_BAN_FOREVER: str = "9999-12-31T23:59:59"
ROULETTE_TICK_SECONDS: int = 3
SEARCH_TIMEOUT_MIN: float = 1          # авто-стоп поиска, минут
SEARCH_REMIND_MIN: float = 0.5         # напоминание «ищем», минут
CHAT_INACTIVE_TIMEOUT_SEC: int = 120   # авто-закрытие чата без сообщений, сек
LINK_CHANGE_COOLDOWN_DAYS: int = 7

# ─── VIP / Магазин ───────────────────────────────────────────────────────────
VIP_DISCOUNT_PERCENT: int = 20
VIP_DAILY_BONUS: int = 5

# ─── Подарок 18+ ─────────────────────────────────────────────────────────────
GIFT_18PLUS_PRICE: int = 567
GIFT_18PLUS_PRICE_VIP: int = 456
GIFT_18PLUS_DAYS: int = 30

# ─── Рефералы ────────────────────────────────────────────────────────────────
REF_REWARD_NORMAL: int = 50
REF_REWARD_VIP: int = 100
REF_INVITED_BONUS: int = 100
REF_INVITED_BONUS_VIP: int = 200
REF_VIP_THRESHOLD: int = 5
REF_VIP_DAYS: int = 7
REF_MODER_THRESHOLD: int = 10
REF_MODER_DAYS: int = 7
LINK_REWARD_EVERY: int = 10
LINK_REWARD_COINS: int = 20

# ─── Джанитор (автоочистка) ──────────────────────────────────────────────────
INACTIVE_DAYS: int = 14
JANITOR_WAKE_HOURS: int = 6
JANITOR_PERIOD_DAYS: int = 14

# ─── Антифлуд ────────────────────────────────────────────────────────────────
CB_COOLDOWN: float = 1.0               # сек между callback_query
ROULETTE_MSG_LIMIT: int = 30           # макс сообщений в рулетке
ROULETTE_MSG_WINDOW: int = 60          # за сколько секунд

# ─── Прочее ──────────────────────────────────────────────────────────────────
CREATOR_USERNAME: str = "@ToxIc_0707"
UNLIMITED_COINS: int = 10 ** 9
LINK_FLOW_TTL_HOURS: int = 6
REF_CODE_CHARS: str = "abcdefghijkmnpqrstuvwxyz23456789"


# ─── Enum состояний FSM ──────────────────────────────────────────────────────
class State(str, Enum):
    """Состояния пользователя (FSM). Наследует str для удобства сравнений."""

    # Регистрация
    SET_GENDER_FIRST = "set_gender_first"
    SET_GENDER_PROFILE = "set_gender_profile"
    SET_AGE_FIRST = "set_age_first"
    SET_AGE_PROFILE = "set_age_profile"

    # Ссылка
    LINK_MENU = "link_menu"
    AWAITING_LINK_CODE = "awaiting_link_code"

    # Анонимка
    AWAITING_ANON_TYPE = "awaiting_anon_type"
    AWAITING_ANON_CONTENT = "awaiting_anon_content"
    AWAITING_REPLY = "awaiting_reply"
    AWAITING_REPORT_REASON = "awaiting_report_reason"

    # Рулетка
    ROULETTE_PREF = "roulette_pref"
    RCHAT = "rchat"
    RLEFT = "rleft"

    # 18+
    EIGHTEENPLUS_AGE_SELECT = "18plus_age_select"
    EIGHTEENPLUS_CONSENT = "18plus_consent"
    EIGHTEENPLUS_VERIFY_OFFER = "18plus_verify_offer"
    EIGHTEENPLUS_VERIFY_UPLOAD = "18plus_verify_upload"
    EIGHTEENPLUS_MENU = "18plus_menu"
    EIGHTEENPLUS_PREF = "18plus_pref"
    EIGHTEENPLUS_AGE_SEARCH = "18plus_age_search"
    EIGHTEENPLUS_RCHAT = "18plus_rchat"

    # Подарки
    GIFT18_ID = "gift18_id"
    GIFT18_CONFIRM = "gift18_confirm"
    GIFTCOINS_ID = "giftcoins_id"
    GIFTCOINS_AMOUNT = "giftcoins_amount"

    # Профиль
    PROFILE = "profile"

    # Магазин
    SHOP = "shop"
    SHOP_CONFIRM = "shop_confirm"
    SHOP_ADD_TITLE = "shop_add_title"
    SHOP_ADD_PRICE = "shop_add_price"
    SHOP_ADD_REWARD = "shop_add_reward"
    SHOP_ADD_AMOUNT = "shop_add_amount"
    SHOP_ADD_DAYS = "shop_add_days"
    SHOP_ADD_18PLUS_DAYS = "shop_add_18plus_days"
    SHOP_EDIT_PICK = "shop_edit_pick"
    SHOP_EDIT_MENU = "shop_edit_menu"
    SHOP_EDIT_NAME = "shop_edit_name"
    SHOP_EDIT_PRICE = "shop_edit_price"
    SHOP_EDIT_AMOUNT = "shop_edit_amount"
    SHOP_EDIT_DAYS = "shop_edit_days"
    SHOP_EDIT_18PLUS_DAYS = "shop_edit_18plus_days"

    # Stars (покупка коинов)
    STAR_SHOP = "star_shop"
    STAR_CONFIRM = "star_confirm"
    STAR_ADMIN = "star_admin"
    STAR_ADD_TITLE = "star_add_title"
    STAR_ADD_COINS = "star_add_coins"
    STAR_ADD_PRICE = "star_add_price"
    STAR_DEL = "star_del"

    # Рефералы
    REFERRAL = "referral"
    REF_SETTINGS = "ref_settings"
    REF_SET_VIP_DAYS = "ref_set_vip_days"
    REF_SET_VIP_THRESHOLD = "ref_set_vip_threshold"
    REF_SET_MODER_DAYS = "ref_set_moder_days"
    REF_SET_MODER_THRESHOLD = "ref_set_moder_threshold"
    REF_SET_PHOTO = "ref_set_photo"

    # Язык
    LANGUAGE = "language"

    # Админка
    ADMIN = "admin"
    ADMIN_MODER = "admin_moder"
    ADMIN_VIP = "admin_vip"
    VIP_GIVE_ID = "vip_give_id"
    VIP_GIVE_DAYS = "vip_give_days"
    VIP_TAKE_ID = "vip_take_id"
    ADM_COINS_ID = "adm_coins_id"
    ADM_COINS_AMOUNT = "adm_coins_amount"
    ADM_CHANNELS_MENU = "adm_channels_menu"
    ADM_CH_NAME = "adm_ch_name"
    ADM_CH_LINK = "adm_ch_link"
    ADM_CH_CONFIRM = "adm_ch_confirm"
    ADM_CH_DELETE = "adm_ch_delete"

    # Реклама
    ADM_AD_MENU = "adm_ad_menu"
    ADM_AD_TEXT = "adm_ad_text"
    ADM_AD_BUTTON_TEXT = "adm_ad_button_text"
    ADM_AD_BUTTON_URL = "adm_ad_button_url"
    ADM_AD_DELETE = "adm_ad_delete"
    ADM_AD_SEND_PICK = "adm_ad_send_pick"

    # Рассылка
    ADM_BCAST_AUDIENCE = "adm_bcast_audience"
    ADM_BCAST_CONTENT = "adm_bcast_content"
    ADM_BCAST_BUTTON_ASK = "adm_bcast_button_ask"
    ADM_BCAST_BUTTON_URL = "adm_bcast_button_url"

    # Модерка
    MODER = "moder"
    MODER_GIVE_ID = "moder_give_id"
    MODER_TAKE_ID = "moder_take_id"
    BAN_ID = "ban_id"

    # Модер-анкета (покупка)
    MODER_Q_GENDER = "moder_q_gender"
    MODER_Q_AGE = "moder_q_age"
    MODER_Q_TGTIME = "moder_q_tgtime"
    MODER_Q_AVAIL = "moder_q_avail"

    # Мониторинг рулетки (/tg)
    TG_PICK = "tg_pick"
    TG_WATCH = "tg_watch"

    # Модер-сообщение (/next)
    MODMSG_ID = "modmsg_id"
    MODMSG_TEXT = "modmsg_text"


# Диапазоны поиска по возрасту в 18+ рулетке
AGE_SEARCH_RANGES: dict[str, tuple[int, int]] = {
    "18/20": (18, 20), "20/22": (20, 22), "22/24": (22, 24),
    "24/26": (24, 26), "26/28": (26, 28), "28/30": (28, 30),
    "30+": (30, 200),
}
