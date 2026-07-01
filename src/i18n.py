"""
Интернационализация (i18n): языки (ru/uz/en), переводы экранов и кнопок.

ContextVar `_lang_var` — потокобезопасный язык текущего апдейта (aiogram обрабатывает
апдейты конкурентно в asyncio-задачах).
"""

from __future__ import annotations

import contextvars
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# ЯЗЫК ТЕКУЩЕГО АПДЕЙТА (task-safe через ContextVar)
# ═══════════════════════════════════════════════════════════════════════════════

LANGS = ("ru", "uz", "en")

_lang_var = contextvars.ContextVar("cur_lang", default="ru")


def cur_lang() -> str:
    return _lang_var.get()


def set_cur_lang(value: str) -> None:
    _lang_var.set(value)


def get_lang(uid: int) -> str:
    """Получает язык пользователя из БД (с откатом к 'ru')."""
    from .db import get_user
    try:
        u = get_user(uid)
        if u and u["lang"] in LANGS:
            return u["lang"]
    except Exception:
        pass
    return "ru"


def set_lang(uid: int, lang: str) -> None:
    """Устанавливает язык пользователя в БД."""
    from .db import conn
    conn.execute("UPDATE users SET lang=? WHERE tg_id=?", (lang, uid))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# КНОПКИ: каноническая русская метка → перевод (uz, en)
# ═══════════════════════════════════════════════════════════════════════════════

LANG_BUTTONS: dict[str, str] = {"🇷🇺 Русский": "ru", "🇺🇿 O'zbekcha": "uz", "🇬🇧 English": "en"}

BTN: dict[str, tuple[str, str]] = {
    "🔗 Моя ссылка": ("🔗 Havolam", "🔗 My link"),
    "🎲 Чат-рулетка": ("🎲 Chat-ruletka", "🎲 Chat roulette"),
    "👤 Профиль": ("👤 Profil", "👤 Profile"),
    "🛒 Магазин": ("🛒 Do'kon", "🛒 Shop"),
    "👥 Пригласить": ("👥 Taklif qilish", "👥 Invite"),
    "ℹ️ Помощь": ("ℹ️ Yordam", "ℹ️ Help"),
    "🌐 Язык": ("🌐 Til", "🌐 Language"),
    "💎 Купить коины": ("💎 Coin sotib olish", "💎 Buy coins"),
    "🛠 Админка": ("🛠 Admin panel", "🛠 Admin"),
    "🛡 Модерка": ("🛡 Moderator", "🛡 Moderation"),
    "✅ Да": ("✅ Ha", "✅ Yes"),
    "❌ Отмена": ("❌ Bekor qilish", "❌ Cancel"),
    "💎 Коины": ("💎 Coinlar", "💎 Coins"),
    "⏳ VIP": ("⏳ VIP", "⏳ VIP"),
    "🛡 Модер": ("🛡 Moder", "🛡 Moder"),
    "📦 Вручную": ("📦 Qo'lda", "📦 Manual"),
    "📊 Статистика": ("📊 Statistika", "📊 Statistics"),
    "👑 VIP по ID": ("👑 ID bo'yicha VIP", "👑 VIP by ID"),
    "➕ Выдать VIP": ("➕ VIP berish", "➕ Grant VIP"),
    "➖ Забрать VIP": ("➖ VIP olish", "➖ Revoke VIP"),
    "🔞 18+ доступ: ВКЛ": ("🔞 18+ kirish: YONIQ", "🔞 18+ access: ON"),
    "🔞 18+ доступ: ВЫКЛ": ("🔞 18+ kirish: O'CHIQ", "🔞 18+ access: OFF"),
    "📤 Выгрузить пользователей": ("📤 Foydalanuvchilarni yuklash", "📤 Export users"),
    "💰 Начислить коины": ("💰 Coin qo'shish", "💰 Add coins"),
    "📢 Обязательные каналы": ("📢 Majburiy kanallar", "📢 Required channels"),
    "➕ Добавить канал": ("➕ Kanal qo'shish", "➕ Add channel"),
    "🗑 Удалить канал": ("🗑 Kanalni o'chirish", "🗑 Delete channel"),
    "✅ Сохранить": ("✅ Saqlash", "✅ Save"),
    "📣 Реклама": ("📣 Reklama", "📣 Ad"),
    "✉️ Рассылка": ("✉️ Xabar tarqatish", "✉️ Broadcast"),
    "📢 Рассылка": ("📢 Xabar tarqatish", "📢 Broadcast"),
    "🛡 Модеры": ("🛡 Moderatorlar", "🛡 Moderators"),
    "🔒 Отозвать доступ": ("🔒 Kirishni bekor qilish", "🔒 Revoke access"),
    "🔨 Бан / Разбан": ("🔨 Ban / Unban", "🔨 Ban / Unban"),
    "⭐ Коины за Stars": ("⭐ Stars uchun coin", "⭐ Coins for Stars"),
    "⬅️ Назад": ("⬅️ Orqaga", "⬅️ Back"),
    "🏠 Меню": ("🏠 Menyu", "🏠 Menu"),
    "➕ Добавить пакет коинов": ("➕ Coin paket qo'shish", "➕ Add coin package"),
    "🗑 Удалить пакет коинов": ("🗑 Coin paketni o'chirish", "🗑 Delete coin package"),
    "🚩 Жалобы": ("🚩 Shikoyatlar", "🚩 Reports"),
    "👨 Мужской": ("👨 Erkak", "👨 Male"),
    "👩 Женский": ("👩 Ayol", "👩 Female"),
    "🔗 Показать ссылку": ("🔗 Havolani ko'rsatish", "🔗 Show link"),
    "✏️ Сменить ссылку": ("✏️ Havolani o'zgartirish", "✏️ Change link"),
    "👨 Парня": ("👨 Yigit", "👨 A guy"),
    "👩 Девушку": ("👩 Qiz", "👩 A girl"),
    "🤷 Любого": ("🤷 Farqi yo'q", "🤷 Anyone"),
    "❓ Вопрос": ("❓ Savol", "❓ Question"),
    "💌 Валентинка": ("💌 Valentinka", "💌 Valentine"),
    "🤬 Мат": ("🤬 So'kinish", "🤬 Swearing"),
    "💰 Мошенничество": ("💰 Firibgarlik", "💰 Fraud"),
    "😡 Оскорбление": ("😡 Haqorat", "😡 Insult"),
    "🔞 18+ стикеры": ("🔞 18+ stikerlar", "🔞 18+ stickers"),
    "👎 Не нравится": ("👎 Yoqmadi", "👎 Dislike"),
    "✏️ Сменить пол": ("✏️ Jinsni o'zgartirish", "✏️ Change gender"),
    "👥 Всем": ("👥 Hammaga", "👥 Everyone"),
    "👨 Мужчинам": ("👨 Erkaklarga", "👨 To men"),
    "👩 Женщинам": ("👩 Ayollarga", "👩 To women"),
    "➕ Выдать модера": ("➕ Moder berish", "➕ Grant moder"),
    "➖ Забрать модера": ("➖ Moderni olish", "➖ Revoke moder"),
    "✏️ Изменить": ("✏️ O'zgartirish", "✏️ Edit"),
    "➕ Добавить товар": ("➕ Mahsulot qo'shish", "➕ Add item"),
    "🗑 Удалить товар": ("🗑 Mahsulotni o'chirish", "🗑 Delete item"),
    "📝 Название": ("📝 Nomi", "📝 Name"),
    "💰 Цена": ("💰 Narxi", "💰 Price"),
    "⏳ Срок VIP": ("⏳ VIP muddati", "⏳ VIP duration"),
    "💎 Сумма коинов": ("💎 Coin miqdori", "💎 Coin amount"),
    "🏆 Топ пригласивших": ("🏆 Top taklif qilganlar", "🏆 Top inviters"),
    "⛔ Отменить поиск": ("⛔ Qidiruvni bekor qilish", "⛔ Stop search"),
    "➡️ Далее": ("➡️ Keyingi", "➡️ Next"),
    "⏹️ Стоп": ("⏹️ To'xtatish", "⏹️ Stop"),
    "🔍 Новый поиск": ("🔍 Yangi qidiruv", "🔍 New search"),
    "🚩 Пожаловаться": ("🚩 Shikoyat qilish", "🚩 Report"),
    "📤 Отправить всем": ("📤 Hammaga yuborish", "📤 Send to all"),
    "🔞 18+": ("🔞 18+", "🔞 18+"),
    "🔞 18+ рулетка": ("🔞 18+ ruletka", "🔞 18+ roulette"),
    "🔞 Мне нет 18": ("🔞 18 yoshda emasman", "🔞 I'm under 18"),
    "🎁 Подарить 18+": ("🎁 18+ sovg'a qilish", "🎁 Gift 18+"),
    "🎁 Подарить коины": ("🎁 Coin sovg'a qilish", "🎁 Gift coins"),
    "🤷 Любой возраст": ("🤷 Istalgan yosh", "🤷 Any age"),
    "✅ Согласиться": ("✅ Roziman", "✅ I agree"),
    "✅ Подтвердить": ("✅ Tasdiqlash", "✅ Confirm"),
    "❌ Отклонить": ("❌ Rad etish", "❌ Reject"),
    "📷 Отправить фото": ("📷 Foto yuborish", "📷 Send photo"),
    "✏️ Изменить возраст": ("✏️ Yoshni o'zgartirish", "✏️ Change age"),
    "🛒 Обычный товар": ("🛒 Oddiy mahsulot", "🛒 Regular item"),
    "🔞 Товар 18+": ("🔞 18+ mahsulot", "🔞 18+ item"),
    "18+ рулетка": ("18+ ruletka", "18+ roulette"),
    "18+ магазин": ("18+ do'kon", "18+ shop"),
}

# Обратная карта: метка на любом языке → каноническая русская метка
_ALIAS: dict[str, str] = {}
for _ru, (_uz, _en) in BTN.items():
    _ALIAS[_ru] = _ru
    _ALIAS[_uz] = _ru
    _ALIAS[_en] = _ru


def canon(text: Optional[str]) -> Optional[str]:
    """Любая языковая метка кнопки → каноническая русская (для маршрутизации).

    Убирает декоративные обрамления styled() перед поиском.
    """
    if text is None:
        return None
    t = text
    if t.startswith("⟡ ") and t.endswith(" ⟡"):
        t = t[2:-2]
    elif t.startswith("« ") and t.endswith(" »"):
        t = t[2:-2]
    return _ALIAS.get(t, _ALIAS.get(text, text))


def styled(text: str, kind: str = "default") -> str:
    """Добавляет декоративное обрамление к тексту кнопки.

    kind: default — без изменений, premium — ⟡...⟡, accent — «...»
    """
    if kind == "premium":
        return f"⟡ {text} ⟡"
    if kind == "accent":
        return f"« {text} »"
    return text


def tr_btn(ru_label: str, lang: Optional[str] = None, kind: str = "default") -> str:
    """Перевод русской метки кнопки на текущий/заданный язык + стилизация."""
    lang = lang or cur_lang()
    if lang == "ru":
        base = ru_label
    else:
        pair = BTN.get(ru_label)
        if not pair:
            base = ru_label
        else:
            base = pair[0] if lang == "uz" else pair[1]
    return styled(base, kind) if kind != "default" else base


def tr_kb(markup: Any, lang: Optional[str] = None) -> Any:
    """Переводит метки reply-клавиатуры на текущий язык, сохраняя структуру.

    Уже стилизованные кнопки (⟡/«») не переводятся повторно.
    Импортирует типы клавиатур лениво, чтобы не было circular imports.
    """
    lang = lang or cur_lang()
    if lang == "ru":
        return markup
    # Проверяем тип через имя класса (чтобы не импортировать aiogram здесь)
    if not hasattr(markup, "keyboard"):
        return markup
    from aiogram.types import KeyboardButton as _KB, ReplyKeyboardMarkup as _RKM
    new_rows = []
    for row in markup.keyboard:
        new_row = []
        for b in row:
            txt = b.text
            if txt.startswith("⟡ ") or txt.startswith("« "):
                new_row.append(_KB(text=txt))
            else:
                new_row.append(_KB(text=tr_btn(canon(txt) or txt, lang)))
        new_rows.append(new_row)
    return _RKM(
        keyboard=new_rows,
        resize_keyboard=markup.resize_keyboard,
        one_time_keyboard=markup.one_time_keyboard,
    )


def gender_label(code: Optional[str]) -> str:
    """Локализованное название пола."""
    return {
        "m": {"ru": "Мужской", "uz": "Erkak", "en": "Male"},
        "f": {"ru": "Женский", "uz": "Ayol", "en": "Female"},
    }.get(code or "", {}).get(cur_lang(), "—")


def pref_label(code: Optional[str]) -> str:
    """Локализованное название предпочтения поиска."""
    return {
        "m": {"ru": "Парня", "uz": "Yigit", "en": "A guy"},
        "f": {"ru": "Девушку", "uz": "Qiz", "en": "A girl"},
        "any": {"ru": "Любого", "uz": "Farqi yo'q", "en": "Anyone"},
    }.get(code or "", {}).get(cur_lang(), "—")


# ═══════════════════════════════════════════════════════════════════════════════
# ПЕРЕВОДЫ ЭКРАНОВ / СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════════

T: dict[str, dict[str, str]] = {
    "main_menu": {
        "ru": "Главное меню 👇",
        "uz": "Asosiy menyu 👇",
        "en": "Main menu 👇",
    },
    "pick_on_kb": {
        "ru": "Выберите вариант на клавиатуре 👇",
        "uz": "Klaviaturadan variantni tanlang 👇",
        "en": "Please choose an option on the keyboard 👇",
    },
    "not_understood": {
        "ru": "Не понял команду. Воспользуйтесь меню 👇",
        "uz": "Buyruqni tushunmadim. Menyudan foydalaning 👇",
        "en": "I didn't get that. Please use the menu 👇",
    },
    "search_cancelled": {
        "ru": "Поиск отменён. Главное меню 👇",
        "uz": "Qidiruv bekor qilindi. Asosiy menyu 👇",
        "en": "Search cancelled. Main menu 👇",
    },
    "banned": {
        "ru": "🚫 Вы заблокированы и не можете пользоваться ботом.",
        "uz": "🚫 Siz bloklangansiz va botdan foydalana olmaysiz.",
        "en": "🚫 You are blocked and cannot use the bot.",
    },
    "done": {
        "ru": "Готово.",
        "uz": "Tayyor.",
        "en": "Done.",
    },
    "cancelled": {
        "ru": "Отменено.",
        "uz": "Bekor qilindi.",
        "en": "Cancelled.",
    },
    "choose_on_kb": {
        "ru": "Выберите 👇",
        "uz": "Tanlang 👇",
        "en": "Choose 👇",
    },
    "no_contacts": {
        "ru": "🚫 Нельзя отправлять ссылки, @юзернеймы, номера, ID и упоминания соцсетей/каналов. Сообщение не отправлено.",
        "uz": "🚫 Havola, @username, raqam, ID va ijtimoiy tarmoq/kanal nomlarini yuborib bo'lmaydi. Xabar yuborilmadi.",
        "en": "🚫 You can't send links, @usernames, numbers, IDs or social/channel mentions. Message not sent.",
    },
}
# NOTE: Полный словарь T содержит 200+ ключей. Они будут загружены из отдельного
# файла translations.py или добавлены при финальной сборке (этап 8).
# Здесь оставлены только базовые — остальные остаются в bot.py до полной миграции.


def t(key: str, **kw: Any) -> str:
    """Получает перевод по ключу на текущем языке. Подставляет format-аргументы."""
    d = T.get(key, {})
    s = d.get(cur_lang()) or d.get("ru") or key
    return s.format(**kw) if kw else s
