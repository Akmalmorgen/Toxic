"""Переводы и метки кнопок (BTN, T)."""

# Реестр кнопок: каноническая русская метка -> перевод (uz, en).
BTN = {
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


# Реестр переводов экранов/сообщений
T = {
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
    # === Общие ===
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
    "enter_number": {
        "ru": "Введите число:",
        "uz": "Raqam kiriting:",
        "en": "Enter a number:",
    },
    "enter_days": {
        "ru": "Введите число дней:",
        "uz": "Kunlar sonini kiriting:",
        "en": "Enter the number of days:",
    },
    "choose_on_kb": {
        "ru": "Выберите 👇",
        "uz": "Tanlang 👇",
        "en": "Choose 👇",
    },
    # === Ссылка (доп.) ===
    "link_section": {
        "ru": "🔗 <b>Раздел «Моя ссылка»</b>\n\nВыберите действие 👇",
        "uz": "🔗 <b>«Havolam» bo'limi</b>\n\nAmalni tanlang 👇",
        "en": "🔗 <b>«My link» section</b>\n\nChoose an action 👇",
    },
    "link_show": {
        "ru": "✦ <b>Ваша персональная ссылка</b> ✦\n<blockquote>{link}</blockquote>\n📤 Нажми «Поделиться» — выбери, кому отправить, и тебе будут писать анонимно 💌",
        "uz": "✦ <b>Shaxsiy havolangiz</b> ✦\n<blockquote>{link}</blockquote>\n📤 «Ulashish» tugmasini bosing — kimga yuborishni tanlang, sizga anonim yozishadi 💌",
        "en": "✦ <b>Your personal link</b> ✦\n<blockquote>{link}</blockquote>\n📤 Tap «Share» — pick who to send it to, and people will message you anonymously 💌",
    },
    "link_done": {
        "ru": "✅ <b>Готово! Ваша ссылка</b> ✦\n<blockquote>{link}</blockquote>\n📤 Нажми «Поделиться», чтобы отправить её 💌",
        "uz": "✅ <b>Tayyor! Havolangiz</b> ✦\n<blockquote>{link}</blockquote>\n📤 Uni yuborish uchun «Ulashish» tugmasini bosing 💌",
        "en": "✅ <b>Done! Your link</b> ✦\n<blockquote>{link}</blockquote>\n📤 Tap «Share» to send it 💌",
    },
    "btn_share": {
        "ru": "✦ Поделиться",
        "uz": "✦ Ulashish",
        "en": "✦ Share",
    },
    "share_text": {
        "ru": "Напиши мне что-нибудь анонимно 👀",
        "uz": "Menga anonim biror narsa yozing 👀",
        "en": "Send me something anonymously 👀",
    },
    # === Анонимка (доп.) ===
    "anon_cancelled_menu": {
        "ru": "Отменено. Главное меню 👇",
        "uz": "Bekor qilindi. Asosiy menyu 👇",
        "en": "Cancelled. Main menu 👇",
    },
    # === Подписка (доп.) ===
    "sub_to_delete": {
        "ru": "Чтобы удалить сообщение, подпишись на канал(ы):\n\n",
        "uz": "Xabarni o'chirish uchun kanal(lar)ga obuna bo'ling:\n\n",
        "en": "To delete the message, subscribe to the channel(s):\n\n",
    },
    "sub_to_delete_short": {
        "ru": (
            "🔒 <b>Чтобы удалить сообщение — подпишись 👇</b>\n"
            "<i>Нажми на кнопки ниже, подпишись, вернись и нажми «✅ Проверить».</i>"
        ),
        "uz": (
            "🔒 <b>Xabarni o'chirish uchun — obuna bo'ling 👇</b>\n"
            "<i>Quyidagi tugmalarni bosing, obuna bo'ling, qayting va «✅ Tekshirish» ni bosing.</i>"
        ),
        "en": (
            "🔒 <b>To delete the message — subscribe 👇</b>\n"
            "<i>Tap the buttons below, subscribe, come back and press «✅ Check».</i>"
        ),
    },
    "btn_check_sub": {
        "ru": "✅ Проверить",
        "uz": "✅ Tekshirish",
        "en": "✅ Check",
    },
    "subgate_start": {
        "ru": (
            "🔒 <b>Чтобы пользоваться ботом — подпишись 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Нажми на кнопки ниже, подпишись, затем вернись и нажми «✅ Проверить».</i>"
        ),
        "uz": (
            "🔒 <b>Botdan foydalanish uchun — obuna bo'ling 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Quyidagi tugmalarni bosing, obuna bo'ling, keyin qaytib «✅ Tekshirish» ni bosing.</i>"
        ),
        "en": (
            "🔒 <b>To use the bot — subscribe 👇</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Tap the buttons below, subscribe, then come back and press «✅ Check».</i>"
        ),
    },
    "link_limit_sub": {
        "ru": (
            "⏳ Менять ссылку можно раз в неделю (осталось {days} дн.).\n\n"
            "🔥 <b>Не хочешь ждать?</b> Подпишись на каналы ниже — и меняй ссылку <b>сколько хочешь, даже без VIP</b> 👇\n"
            "<i>После подписки снова нажми «✏️ Сменить ссылку».</i>"
        ),
        "uz": (
            "⏳ Havolani haftada bir marta o'zgartirish mumkin ({days} kun qoldi).\n\n"
            "🔥 <b>Kutishni xohlamaysizmi?</b> Quyidagi kanallarga obuna bo'ling — va havolani <b>xohlagancha, hatto VIPsiz</b> o'zgartiring 👇\n"
            "<i>Obunadan keyin yana «✏️ Havolani o'zgartirish» ni bosing.</i>"
        ),
        "en": (
            "⏳ You can change your link once a week ({days} days left).\n\n"
            "🔥 <b>Don't want to wait?</b> Subscribe to the channels below — and change your link <b>as often as you want, even without VIP</b> 👇\n"
            "<i>After subscribing, tap «✏️ Change link» again.</i>"
        ),
    },
    # === Профиль (доп.) ===
    "profile_full": {
        "ru": (
            "👤 <b>Ваш профиль</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Имя: <b>{name}</b>\n"
            "🚻 Пол: <b>{gender}</b>\n"
            "🎂 Возраст: <b>{age}</b>\n"
            "🎲 В чат-рулетке: <b>{roulette_time}</b>\n"
            "📤 Отправлено по ссылке: <b>{sent}</b>\n"
            "📥 Получено по ссылке: <b>{received}</b>\n"
            "👥 Приглашено друзей: <b>{invited}</b>\n"
            "🏆 Место в топе: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Коины: <b>{coins}</b>\n"
            "⭐ Потрачено звёзд (покупка коинов): <b>{stars}</b>\n"
            "📅 Регистрация: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "uz": (
            "👤 <b>Profilingiz</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Ism: <b>{name}</b>\n"
            "🚻 Jins: <b>{gender}</b>\n"
            "🎂 Yosh: <b>{age}</b>\n"
            "🎲 Chat-ruletkada: <b>{roulette_time}</b>\n"
            "📤 Havola orqali yuborilgan: <b>{sent}</b>\n"
            "📥 Havola orqali kelgan: <b>{received}</b>\n"
            "👥 Taklif qilingan do'stlar: <b>{invited}</b>\n"
            "🏆 Topdagi o'rin: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Coinlar: <b>{coins}</b>\n"
            "⭐ Sarflangan yulduzlar (coin xaridi): <b>{stars}</b>\n"
            "📅 Ro'yxatdan o'tgan: <b>{reg_date}</b>"
            "</blockquote>"
        ),
        "en": (
            "👤 <b>Your profile</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>"
            "🆔 ID: <code>{id}</code>\n"
            "👤 Name: <b>{name}</b>\n"
            "🚻 Gender: <b>{gender}</b>\n"
            "🎂 Age: <b>{age}</b>\n"
            "🎲 In chat roulette: <b>{roulette_time}</b>\n"
            "📤 Sent via link: <b>{sent}</b>\n"
            "📥 Received via link: <b>{received}</b>\n"
            "👥 Friends invited: <b>{invited}</b>\n"
            "🏆 Leaderboard place: <b>{rank}</b>\n"
            "👑 VIP: <b>{vip}</b>\n"
            "💎 Coins: <b>{coins}</b>\n"
            "⭐ Stars spent (buying coins): <b>{stars}</b>\n"
            "📅 Registered: <b>{reg_date}</b>"
            "</blockquote>"
        ),
    },
    "vip_none": {"ru": "—", "uz": "—", "en": "—"},
    "profile_18plus_line": {
        "ru": "🔞 В 18+ чате: <b>{time}</b>",
        "uz": "🔞 18+ chatda: <b>{time}</b>",
        "en": "🔞 In 18+ chat: <b>{time}</b>",
    },
    "vip_until": {
        "ru": "до {date} 👑",
        "uz": "{date} gacha 👑",
        "en": "until {date} 👑",
    },
    "vip_forever": {
        "ru": "навсегда 👑",
        "uz": "abadiy 👑",
        "en": "forever 👑",
    },
    "you_were_banned": {
        "ru": "🚫 На вас поступила жалоба — на {days} дн. вы не сможете попасть к этому собеседнику в рулетке.",
        "uz": "🚫 Sizga shikoyat tushdi — {days} kun davomida ruletkada bu suhbatdoshga tusha olmaysiz.",
        "en": "🚫 You were reported — for {days} days you won't be matched with this person in roulette.",
    },
    "you_were_banned_forever": {
        "ru": "🚫 На вас поступила жалоба. Вы <b>навсегда</b> заблокированы для этого пользователя: писать ему нельзя. Другим — можно.",
        "uz": "🚫 Sizga shikoyat tushdi. Siz bu foydalanuvchi uchun <b>abadiy</b> bloklandingiz: unga yoza olmaysiz. Boshqalarga — mumkin.",
        "en": "🚫 You were reported. You are <b>permanently</b> blocked for this user: you can't message them. Others are fine.",
    },
    "anon_deleted_notice": {
        "ru": "🗑 Собеседник удалил своё анонимное сообщение.",
        "uz": "🗑 Suhbatdosh o'zining anonim xabarini o'chirdi.",
        "en": "🗑 The sender deleted their anonymous message.",
    },
    "no_contacts": {
        "ru": "🚫 Нельзя отправлять ссылки, @юзернеймы, номера, ID и упоминания соцсетей/каналов. Сообщение не отправлено.",
        "uz": "🚫 Havola, @username, raqam, ID va ijtimoiy tarmoq/kanal nomlarini yuborib bo'lmaydi. Xabar yuborilmadi.",
        "en": "🚫 You can't send links, @usernames, numbers, IDs or social/channel mentions. Message not sent.",
    },
    "cant_ban_staff": {
        "ru": "Нельзя забанить администратора или модератора. Жалоба отклонена.",
        "uz": "Administrator yoki moderatorni bloklab bo'lmaydi. Shikoyat rad etildi.",
        "en": "You can't ban an admin or moderator. The report was rejected.",
    },
    # === Рулетка (доп.) ===
    "roulette_who": {
        "ru": "🎲 Кого вы хотите найти?",
        "uz": "🎲 Kimni topmoqchisiz?",
        "en": "🎲 Who do you want to find?",
    },
    "roulette_chat_ended": {
        "ru": "Чат завершён ✅",
        "uz": "Chat yakunlandi ✅",
        "en": "Chat ended ✅",
    },
    "roulette_chat_stopped": {
        "ru": "Чат завершён.",
        "uz": "Chat yakunlandi.",
        "en": "Chat ended.",
    },
    "roulette_finding_new": {
        "ru": "Ищем нового собеседника… ⏳",
        "uz": "Yangi suhbatdosh qidirilmoqda… ⏳",
        "en": "Looking for a new partner… ⏳",
    },
    "roulette_already_short": {
        "ru": "Вы уже в чате.",
        "uz": "Siz allaqachon chatdasiz.",
        "en": "You are already in a chat.",
    },
    "roulette_finding_partner": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "session_not_found": {
        "ru": "Сессия не найдена.",
        "uz": "Sessiya topilmadi.",
        "en": "Session not found.",
    },
    "roulette_searching_new": {
        "ru": "Ищем нового собеседника...",
        "uz": "Yangi suhbatdosh qidirilmoqda...",
        "en": "Looking for a new partner...",
    },
    "btn_next": {
        "ru": "➡️ Далее",
        "uz": "➡️ Keyingi",
        "en": "➡️ Next",
    },
    "btn_stop": {
        "ru": "⏹️ Стоп",
        "uz": "⏹️ To'xtatish",
        "en": "⏹️ Stop",
    },
    "btn_new_search": {
        "ru": "🔍 Новый поиск",
        "uz": "🔍 Yangi qidiruv",
        "en": "🔍 New search",
    },
    "btn_complain": {
        "ru": "🚩 Пожаловаться",
        "uz": "🚩 Shikoyat qilish",
        "en": "🚩 Report",
    },

    # === Магазин (доп.) ===
    "shop_pick_item": {
        "ru": "Выберите товар на клавиатуре 👇",
        "uz": "Klaviaturadan mahsulotni tanlang 👇",
        "en": "Choose an item on the keyboard 👇",
    },
    "18plus_shop_pick_item": {
        "ru": "Выберите товар 18+ на клавиатуре 👇",
        "uz": "18+ mahsulotini klaviaturadan tanlang 👇",
        "en": "Choose a 18+ item on the keyboard 👇",
    },
    "item_unavailable": {
        "ru": "Товар недоступен.",
        "uz": "Mahsulot mavjud emas.",
        "en": "Item unavailable.",
    },
    "not_enough_coins": {
        "ru": "Недостаточно коинов 💎",
        "uz": "Coinlar yetarli emas 💎",
        "en": "Not enough coins 💎",
    },
    "shop_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» за {price}?",
        "uz": "«<b>{title}</b>»ni {price} ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» for {price}?",
    },
    "price_plain": {
        "ru": "<b>{price}</b> 💎",
        "uz": "<b>{price}</b> 💎",
        "en": "<b>{price}</b> 💎",
    },
    "price_vip": {
        "ru": "<b>{price}</b> 💎 (VIP-скидка, обычно {orig})",
        "uz": "<b>{price}</b> 💎 (VIP chegirma, odatda {orig})",
        "en": "<b>{price}</b> 💎 (VIP discount, usually {orig})",
    },
    "purchase_coins": {
        "ru": "✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b> 💎",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> <b>{amt}</b> 💎 qo'shildi",
        "en": "✅ <b>Purchase complete!</b> <b>{amt}</b> 💎 added",
    },
    "purchase_vip": {
        "ru": "✅ <b>Покупка совершена!</b> VIP активен на <b>{days}</b> дн. 👑",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> VIP <b>{days}</b> kun faol 👑",
        "en": "✅ <b>Purchase complete!</b> VIP active for <b>{days}</b> days 👑",
    },
    "purchase_manual": {
        "ru": "✅ <b>Покупка совершена!</b> Админ свяжется с вами и выдаст товар.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> Admin siz bilan bog'lanib, mahsulotni beradi.",
        "en": "✅ <b>Purchase complete!</b> The admin will contact you and deliver the item.",
    },
    "purchase_18plus": {
        "ru": "🔞 <b>Доступ к 18+ чату открыт на {days} дн.!</b> 🔥\nЗаходи в «🔞 18+ → 18+ рулетка» и общайся.",
        "uz": "🔞 <b>18+ chatga {days} kunga kirish ochildi!</b> 🔥\n«🔞 18+ → 18+ ruletka» ga kiring.",
        "en": "🔞 <b>18+ chat access granted for {days} days!</b> 🔥\nOpen «🔞 18+ → 18+ roulette» and chat.",
    },
    "purchase_18plus_forever": {
        "ru": "🔞 <b>Доступ к 18+ чату открыт навсегда!</b> 🔥\nЗаходи в «🔞 18+ → 18+ рулетка» и общайся.",
        "uz": "🔞 <b>18+ chatga abadiy kirish ochildi!</b> 🔥\n«🔞 18+ → 18+ ruletka» ga kiring.",
        "en": "🔞 <b>18+ chat access granted forever!</b> 🔥\nOpen «🔞 18+ → 18+ roulette» and chat.",
    },
    "eighteenplus_need_access": {
        "ru": (
            "🔒 <b>Нет доступа к 18+ чату</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Чтобы общаться в 18+ рулетке, купи доступ в <b>🔞 18+ магазине</b> 👇\n"
            "<i>Выбери товар с нужным сроком — доступ откроется сразу после покупки.</i>"
        ),
        "uz": (
            "🔒 <b>18+ chatga kirish yo'q</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "18+ ruletkada suhbatlashish uchun <b>🔞 18+ do'kondan</b> kirish sotib oling 👇\n"
            "<i>Kerakli muddatli mahsulotni tanlang — kirish darrov ochiladi.</i>"
        ),
        "en": (
            "🔒 <b>No access to the 18+ chat</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "To chat in the 18+ roulette, buy access in the <b>🔞 18+ shop</b> 👇\n"
            "<i>Pick an item with the duration you want — access opens right after purchase.</i>"
        ),
    },
    # === Подарки (18+ и коины) ===
    "gift18_ask_id": {
        "ru": (
            "🎁 <b>Подарить доступ 18+ другу</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Цена подарка: <b>{price}</b> 💎\n"
            "Срок доступа другу: <b>{days} дн.</b>\n\n"
            "Введите <b>Telegram ID</b> или <b>@username</b> друга, которому хотите подарить 👇\n"
            "<i>(друг должен быть запущен в боте)</i>"
        ),
        "uz": (
            "🎁 <b>Do'stga 18+ kirish sovg'a qilish</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Sovg'a narxi: <b>{price}</b> 💎\n"
            "Do'st uchun muddat: <b>{days} kun</b>\n\n"
            "Do'stning <b>Telegram ID</b> yoki <b>@username</b> ini kiriting 👇"
        ),
        "en": (
            "🎁 <b>Gift 18+ access to a friend</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Gift price: <b>{price}</b> 💎\n"
            "Access for friend: <b>{days} days</b>\n\n"
            "Enter the friend's <b>Telegram ID</b> or <b>@username</b> 👇"
        ),
    },
    "gift18_confirm": {
        "ru": "🎁 Подарить пользователю <code>{id}</code> доступ 18+ на <b>{days} дн.</b> за <b>{price}</b> 💎?",
        "uz": "🎁 <code>{id}</code> foydalanuvchiga <b>{days} kun</b>lik 18+ kirishni <b>{price}</b> 💎 ga sovg'a qilasizmi?",
        "en": "🎁 Gift user <code>{id}</code> 18+ access for <b>{days} days</b> for <b>{price}</b> 💎?",
    },
    "gift18_sent": {
        "ru": "✅ <b>Подарок отправлен!</b>\nПользователю <code>{id}</code> открыт доступ 18+ на {days} дн. 🎉",
        "uz": "✅ <b>Sovg'a yuborildi!</b>\n<code>{id}</code> ga 18+ {days} kunga ochildi 🎉",
        "en": "✅ <b>Gift sent!</b>\nUser <code>{id}</code> got 18+ access for {days} days 🎉",
    },
    "gift18_received": {
        "ru": "🎁 <b>Вам подарили доступ 18+!</b> 🔥\nОткрыт на <b>{days} дн.</b>\nЗаходи в «🔞 18+ → 18+ рулетка» 💋",
        "uz": "🎁 <b>Sizga 18+ kirish sovg'a qilindi!</b> 🔥\n<b>{days} kun</b>ga ochildi.\n«🔞 18+ → 18+ ruletka» ga kiring 💋",
        "en": "🎁 <b>You received 18+ access as a gift!</b> 🔥\nGranted for <b>{days} days</b>.\nOpen «🔞 18+ → 18+ roulette» 💋",
    },
    "gift_id_number": {
        "ru": "ID должен быть числом. Введите Telegram ID друга:",
        "uz": "ID raqam bo'lishi kerak. Do'stning Telegram ID sini kiriting:",
        "en": "ID must be a number. Enter the friend's Telegram ID:",
    },
    "gift_not_self": {
        "ru": "Нельзя подарить самому себе 🙂 Введите ID друга:",
        "uz": "O'zingizga sovg'a qila olmaysiz 🙂 Do'stning ID sini kiriting:",
        "en": "You can't gift yourself 🙂 Enter a friend's ID:",
    },
    "gift_user_not_found": {
        "ru": "Пользователь не найден (он должен быть запущен в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi (u botda bo'lishi kerak). ID yoki @username kiriting:",
        "en": "User not found (they must be in the bot). Enter ID or @username:",
    },
    "giftcoins_ask_id": {
        "ru": (
            "🎁 <b>Подарить коины другу</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Коины спишутся с твоего баланса и придут другу.\n\n"
            "Введите <b>Telegram ID</b> или <b>@username</b> друга 👇\n"
            "<i>(друг должен быть запущен в боте)</i>"
        ),
        "uz": (
            "🎁 <b>Do'stga coin sovg'a qilish</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coinlar balansingizdan yechiladi va do'stga o'tadi.\n\n"
            "Do'stning <b>Telegram ID</b> yoki <b>@username</b> ini kiriting 👇"
        ),
        "en": (
            "🎁 <b>Gift coins to a friend</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Coins are deducted from your balance and go to your friend.\n\n"
            "Enter the friend's <b>Telegram ID</b> or <b>@username</b> 👇"
        ),
    },
    "giftcoins_ask_amount": {
        "ru": "💎 Сколько коинов подарить? (твой баланс: <b>{balance}</b> 💎)",
        "uz": "💎 Qancha coin sovg'a qilasiz? (balansingiz: <b>{balance}</b> 💎)",
        "en": "💎 How many coins to gift? (your balance: <b>{balance}</b> 💎)",
    },
    "giftcoins_amount_number": {
        "ru": "Введите положительное число коинов:",
        "uz": "Musbat coin sonini kiriting:",
        "en": "Enter a positive number of coins:",
    },
    "giftcoins_not_enough": {
        "ru": "Недостаточно коинов. Твой баланс: <b>{balance}</b> 💎. Введите меньшую сумму:",
        "uz": "Coin yetarli emas. Balansingiz: <b>{balance}</b> 💎. Kamroq summa kiriting:",
        "en": "Not enough coins. Your balance: <b>{balance}</b> 💎. Enter a smaller amount:",
    },
    "giftcoins_sent": {
        "ru": "✅ <b>Готово!</b> Подарено <b>{amount}</b> 💎 пользователю <code>{id}</code> 🎉",
        "uz": "✅ <b>Tayyor!</b> <code>{id}</code> ga <b>{amount}</b> 💎 sovg'a qilindi 🎉",
        "en": "✅ <b>Done!</b> Gifted <b>{amount}</b> 💎 to user <code>{id}</code> 🎉",
    },
    "giftcoins_received": {
        "ru": "🎁 <b>Вам подарили {amount} 💎!</b>\nКто-то перевёл тебе коины. Трать в магазине 🛒",
        "uz": "🎁 <b>Sizga {amount} 💎 sovg'a qilindi!</b>\nKimdir coin yubordi. Do'konda sarflang 🛒",
        "en": "🎁 <b>You received {amount} 💎 as a gift!</b>\nSomeone sent you coins. Spend in the shop 🛒",
    },
    # === Жалоба (доп., для пользователя) ===
    "report_confirmed_user": {
        "ru": "✅ Жалоба подтверждена. Этот пользователь не сможет беспокоить вас {days} дн.",
        "uz": "✅ Shikoyat tasdiqlandi. Bu foydalanuvchi sizni {days} kun bezovta qila olmaydi.",
        "en": "✅ Report confirmed. This user can't bother you for {days} days.",
    },
    "report_confirmed_forever": {
        "ru": "✅ Жалоба подтверждена. Этот пользователь больше <b>никогда</b> не сможет писать вам.",
        "uz": "✅ Shikoyat tasdiqlandi. Bu foydalanuvchi endi sizga <b>hech qachon</b> yoza olmaydi.",
        "en": "✅ Report confirmed. This user can <b>never</b> message you again.",
    },
    "report_rejected_user": {
        "ru": "Жалоба отклонена администратором.",
        "uz": "Shikoyat administrator tomonidan rad etildi.",
        "en": "The report was rejected by the administrator.",
    },
    "report_already_handled": {
        "ru": "Жалоба уже обработана.",
        "uz": "Shikoyat allaqachon ko'rib chiqilgan.",
        "en": "The report has already been handled.",
    },
    "report_confirmed_staff": {
        "ru": "Жалоба подтверждена, бан выдан ✅",
        "uz": "Shikoyat tasdiqlandi, ban berildi ✅",
        "en": "Report confirmed, ban issued ✅",
    },
    "report_rejected_staff": {
        "ru": "Жалоба отклонена ❌",
        "uz": "Shikoyat rad etildi ❌",
        "en": "Report rejected ❌",
    },
    "staff_only": {
        "ru": "Только для модерации.",
        "uz": "Faqat moderatorlar uchun.",
        "en": "Moderation only.",
    },
    "moder_form_gender": {
        "ru": "📝 <b>Анкета на модератора.</b>\n\nВаш пол?",
        "uz": "📝 <b>Moderatorlik anketasi.</b>\n\nJinsingiz?",
        "en": "📝 <b>Moderator application.</b>\n\nYour gender?",
    },
    "moder_form_age": {
        "ru": "Сколько вам лет?",
        "uz": "Yoshingiz nechada?",
        "en": "How old are you?",
    },
    "moder_form_tg": {
        "ru": "Сколько времени проводите в Telegram в день?",
        "uz": "Kuniga Telegramda qancha vaqt o'tkazasiz?",
        "en": "How much time do you spend on Telegram per day?",
    },
    "moder_form_avail": {
        "ru": "Сколько готовы уделять боту? Когда вы онлайн?",
        "uz": "Botga qancha vaqt ajrata olasiz? Qachon onlaynsiz?",
        "en": "How much time can you give the bot? When are you online?",
    },
    "moder_form_cancelled": {
        "ru": "Анкета отменена. Коины ({price} 💎) возвращены.",
        "uz": "Anketa bekor qilindi. Coinlar ({price} 💎) qaytarildi.",
        "en": "Application cancelled. Coins ({price} 💎) refunded.",
    },
    "moder_form_sent": {
        "ru": "✅ Анкета отправлена администратору. Ожидайте решения!",
        "uz": "✅ Anketa administratorga yuborildi. Qarorni kuting!",
        "en": "✅ Application sent to the administrator. Please wait for a decision!",
    },
    "moder_granted_user": {
        "ru": "🎉 Вам выдана роль модератора! В меню появилась кнопка «🛡 Модерка».",
        "uz": "🎉 Sizga moderator roli berildi! Menyuda «🛡 Moderator» tugmasi paydo bo'ldi.",
        "en": "🎉 You've been granted the moderator role! A «🛡 Moderation» button appeared in the menu.",
    },
    "moder_granted_shop": {
        "ru": "🎉 <b>Вы теперь Модер!</b> Добро пожаловать в команду.\nЗа бонусом напишите админу @ToxIc_0707 — он всё выдаст.",
        "uz": "🎉 <b>Endi siz Modersiz!</b> Jamoaga xush kelibsiz.\nBonus uchun @ToxIc_0707 adminiga yozing — u hammasini beradi.",
        "en": "🎉 <b>You're a Moder now!</b> Welcome to the team.\nFor a bonus, message the admin @ToxIc_0707 — he'll provide everything.",
    },
    "moder_rejected_user": {
        "ru": "К сожалению, заявка на модера отклонена. Коины ({coins} 💎) возвращены.",
        "uz": "Afsuski, moderlik arizasi rad etildi. Coinlar ({coins} 💎) qaytarildi.",
        "en": "Unfortunately, your moder application was rejected. Coins ({coins} 💎) refunded.",
    },
    "moder_taken_user": {
        "ru": "Роль модератора снята.",
        "uz": "Moderator roli olib tashlandi.",
        "en": "The moderator role has been removed.",
    },
    "admin_only": {
        "ru": "Только для админа.",
        "uz": "Faqat admin uchun.",
        "en": "Admin only.",
    },
    "cleanup_started": {
        "ru": "🧹 Очистка…",
        "uz": "🧹 Tozalash…",
        "en": "🧹 Cleanup…",
    },
    "cleanup_done": {
        "ru": "✅ Готово. Проверено: {checked}, удалено: {removed}",
        "uz": "✅ Tayyor. Tekshirildi: {checked}, o'chirildi: {removed}",
        "en": "✅ Done. Checked: {checked}, removed: {removed}",
    },
    "admin_vip_menu": {
        "ru": "👑 <b>Управление VIP по ID</b>\n\nВыдать или забрать VIP у пользователя 👇",
        "uz": "👑 <b>ID bo'yicha VIP boshqaruvi</b>\n\nFoydalanuvchiga VIP berish yoki olish 👇",
        "en": "👑 <b>VIP management by ID</b>\n\nGrant or revoke VIP for a user 👇",
    },
    "vip_ask_id": {
        "ru": "Введите <b>tg_id</b> или <b>@username</b> пользователя:",
        "uz": "Foydalanuvchining <b>tg_id</b> yoki <b>@username</b> ini kiriting:",
        "en": "Enter the user's <b>tg_id</b> or <b>@username</b>:",
    },
    "vip_ask_days": {
        "ru": "На сколько дней выдать VIP? (число)",
        "uz": "VIP necha kunga berilsin? (raqam)",
        "en": "For how many days to grant VIP? (number)",
    },
    "vip_id_number": {
        "ru": "ID должен быть числом. Попробуйте снова:",
        "uz": "ID raqam bo'lishi kerak. Qaytadan urinib ko'ring:",
        "en": "ID must be a number. Try again:",
    },
    "vip_days_number": {
        "ru": "Введите положительное число дней:",
        "uz": "Musbat kunlar sonini kiriting:",
        "en": "Enter a positive number of days:",
    },
    "vip_user_not_found": {
        "ru": "Пользователь не найден (он должен быть в боте). Введите ID или @username:",
        "uz": "Foydalanuvchi topilmadi (u botda bo'lishi kerak). ID yoki @username kiriting:",
        "en": "User not found (they must be in the bot). Enter ID or @username:",
    },
    "vip_granted_admin": {
        "ru": "✅ VIP выдан пользователю <code>{id}</code> на <b>{days}</b> дн.",
        "uz": "✅ <code>{id}</code> foydalanuvchiga VIP <b>{days}</b> kunga berildi.",
        "en": "✅ VIP granted to user <code>{id}</code> for <b>{days}</b> days.",
    },
    "vip_taken_admin": {
        "ru": "✅ VIP снят у пользователя <code>{id}</code>.",
        "uz": "✅ <code>{id}</code> foydalanuvchidan VIP olib tashlandi.",
        "en": "✅ VIP revoked from user <code>{id}</code>.",
    },
    "vip_granted_user": {
        "ru": "🎉 <b>Вам выдан VIP на {days} дней!</b> 👑\nНаслаждайтесь привилегиями.",
        "uz": "🎉 <b>Sizga {days} kunga VIP berildi!</b> 👑\nImtiyozlardan bahramand bo'ling.",
        "en": "🎉 <b>You've been granted VIP for {days} days!</b> 👑\nEnjoy the perks.",
    },
    "vip_taken_user": {
        "ru": "Ваш VIP-статус был снят администратором.",
        "uz": "VIP holatingiz administrator tomonidan olib tashlandi.",
        "en": "Your VIP status was revoked by the administrator.",
    },
    "adm_18plus_on": {
        "ru": "✅ <b>18+ доступ включён.</b> Раздел снова работает для всех совершеннолетних.",
        "uz": "✅ <b>18+ kirish yoqildi.</b> Bo'lim barcha kattalar uchun yana ishlaydi.",
        "en": "✅ <b>18+ access enabled.</b> The section works again for all adults.",
    },
    "adm_18plus_off": {
        "ru": "🚫 <b>18+ доступ выключен.</b> Кнопка остаётся видимой, но при входе пользователи увидят уведомление о недоступности.",
        "uz": "🚫 <b>18+ kirish o'chirildi.</b> Tugma ko'rinadi, lekin kirishda foydalanuvchilar mavjud emasligi haqida xabar ko'radi.",
        "en": "🚫 <b>18+ access disabled.</b> The button stays visible, but on entry users will see an unavailability notice.",
    },
    "18plus_disabled_notice": {
        "ru": "🔞 <b>Раздел 18+ временно недоступен</b>\n\nАдминистратор приостановил работу 18+ чата. Загляни позже 🙏",
        "uz": "🔞 <b>18+ bo'limi vaqtincha mavjud emas</b>\n\nAdministrator 18+ chatni to'xtatib qo'ydi. Keyinroq kiring 🙏",
        "en": "🔞 <b>The 18+ section is temporarily unavailable</b>\n\nThe administrator paused the 18+ chat. Check back later 🙏",
    },
    "moder_app_already": {
        "ru": "Заявка уже обработана.",
        "uz": "Ariza allaqachon ko'rib chiqilgan.",
        "en": "The application has already been handled.",
    },
    "moder_granted_staff": {
        "ru": "✅ Модерка выдана.",
        "uz": "✅ Moderlik berildi.",
        "en": "✅ Moderation granted.",
    },
    "moder_rejected_staff": {
        "ru": "❌ Заявка отклонена, коины возвращены.",
        "uz": "❌ Ariza rad etildi, coinlar qaytarildi.",
        "en": "❌ Application rejected, coins refunded.",
    },
    "gender_set_short": {
        "ru": "Пол сохранён: {g} ✅",
        "uz": "Jins saqlandi: {g} ✅",
        "en": "Gender saved: {g} ✅",
    },
    "ref_friend_joined": {
        "ru": "🎉 По твоей ссылке пришёл друг! Тебе начислено <b>+{reward}</b> 💎",
        "uz": "🎉 Havolangiz orqali do'st keldi! Sizga <b>+{reward}</b> 💎 qo'shildi",
        "en": "🎉 A friend joined via your link! You earned <b>+{reward}</b> 💎",
    },
    "ref_welcome_bonus": {
        "ru": "🎁 <b>Добро пожаловать!</b> Ты пришёл по ссылке друга — лови подарок <b>+{n}</b> 💎",
        "uz": "🎁 <b>Xush kelibsiz!</b> Do'st havolasi orqali keldingiz — sovg'a <b>+{n}</b> 💎",
        "en": "🎁 <b>Welcome!</b> You joined via a friend's link — here's a gift <b>+{n}</b> 💎",
    },
    "ref_progress_title": {
        "ru": "📊 <b>Прогресс до наград:</b>",
        "uz": "📊 <b>Mukofotlargacha progress:</b>",
        "en": "📊 <b>Progress to rewards:</b>",
    },
    "ref_friends_word": {
        "ru": "друзей",
        "uz": "do'st",
        "en": "friends",
    },
    "referral_screen": {
        "ru": (
            "👥 <b>Приглашай друзей — зарабатывай коины!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "За каждого друга: <b>{reward}</b> 💎{bonus}\n"
            "Приглашено: <b>{total}</b>\n"
            "Заработано: <b>{earned}</b> 💎\n\n"
            "🔗 Твоя ссылка:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ Если друг заблокирует бота — коины за него спишутся обратно."
        ),
        "uz": (
            "👥 <b>Do'stlarni taklif qiling — coin ishlang!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Har bir do'st uchun: <b>{reward}</b> 💎{bonus}\n"
            "Taklif qilindi: <b>{total}</b>\n"
            "Ishlab topildi: <b>{earned}</b> 💎\n\n"
            "🔗 Havolangiz:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ Agar do'st botni bloklasa — uning coinlari qaytarib olinadi."
        ),
        "en": (
            "👥 <b>Invite friends — earn coins!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "For each friend: <b>{reward}</b> 💎{bonus}\n"
            "Invited: <b>{total}</b>\n"
            "Earned: <b>{earned}</b> 💎\n\n"
            "🔗 Your link:\n"
            "<blockquote>{link}</blockquote>\n"
            "⚠️ If a friend blocks the bot — their coins will be deducted back."
        ),
    },
    "referral_bonus_vip": {
        "ru": " 👑 (VIP-бонус)",
        "uz": " 👑 (VIP bonus)",
        "en": " 👑 (VIP bonus)",
    },
    "referral_bonus_normal": {
        "ru": " (у VIP — 100 💎)",
        "uz": " (VIP uchun — 100 💎)",
        "en": " (VIP gets 100 💎)",
    },
    "ref_rewards_title": {
        "ru": (
            "✦ <b>Награды за друзей</b> ✦\n"
            "Приведи друзей по ссылке (чтобы они создали свою ссылку) и забери:\n"
            "🎁 <b>VIP бесплатно</b> — за {vip_n} друзей ({vip_d} дн.)\n"
            "🛡 <b>Модерка на неделю</b> — за {mod_n} друзей ({mod_d} дн.)\n"
            "Жми кнопку, когда наберёшь 💕"
        ),
        "uz": (
            "✦ <b>Do'stlar uchun mukofotlar</b> ✦\n"
            "Havola orqali do'st taklif qiling (ular ham havola yaratsin) va oling:\n"
            "🎁 <b>Bepul VIP</b> — {vip_n} do'st uchun ({vip_d} kun)\n"
            "🛡 <b>Bir haftalik moder</b> — {mod_n} do'st uchun ({mod_d} kun)\n"
            "Yetkazganda tugmani bosing 💕"
        ),
        "en": (
            "✦ <b>Rewards for friends</b> ✦\n"
            "Invite friends via your link (they must create their own link) and claim:\n"
            "🎁 <b>Free VIP</b> — for {vip_n} friends ({vip_d} days)\n"
            "🛡 <b>Moderator for a week</b> — for {mod_n} friends ({mod_d} days)\n"
            "Tap a button once you reach it 💕"
        ),
    },
    "ref_claim_coins_btn": {
        "ru": "💎 {n} за друга · VIP {v} 💎",
        "uz": "💎 do'st uchun {n} · VIP {v} 💎",
        "en": "💎 {n} per friend · VIP {v} 💎",
    },
    "btn_share_ref": {
        "ru": "📤 Поделиться ссылкой",
        "uz": "📤 Havolani ulashish",
        "en": "📤 Share the link",
    },
    "ref_share_text": {
        "ru": "🔥 Залетай в анонимный бот! Тебе пишут тайно, чат-рулетка, подарки 🎁 Жми 👇",
        "uz": "🔥 Anonim botga kir! Sizga yashirin yozishadi, chat-ruletka, sovg'alar 🎁 Bosing 👇",
        "en": "🔥 Join the anonymous bot! Get secret messages, chat roulette, gifts 🎁 Tap 👇",
    },
    "ref_claim_vip_btn": {
        "ru": "🎁 VIP бесплатно ({have}/{need})",
        "uz": "🎁 Bepul VIP ({have}/{need})",
        "en": "🎁 Free VIP ({have}/{need})",
    },
    "ref_claim_moder_btn": {
        "ru": "🛡 Модерка на неделю ({have}/{need})",
        "uz": "🛡 Bir haftalik moder ({have}/{need})",
        "en": "🛡 Moderator for a week ({have}/{need})",
    },
    "ref_need_more": {
        "ru": "Нужно ещё {n} друзей (которые создали свою ссылку). Приглашено подходящих: {have}.",
        "uz": "Yana {n} ta do'st kerak (ular havola yaratgan bo'lishi kerak). Mos: {have}.",
        "en": "Need {n} more friends (who created their own link). Qualified: {have}.",
    },
    "ref_vip_granted": {
        "ru": "🎉 <b>VIP активирован на {days} дней</b> за приглашённых друзей! 👑",
        "uz": "🎉 <b>VIP {days} kunga faollashtirildi</b> — do'stlar uchun! 👑",
        "en": "🎉 <b>VIP activated for {days} days</b> for your invited friends! 👑",
    },
    "ref_moder_granted": {
        "ru": "🛡 <b>Модерка выдана на {days} дней</b> за {need} приглашённых друзей!\nПрочувствуй власть модератора 😎",
        "uz": "🛡 <b>Moderlik {days} kunga berildi</b> — {need} ta do'st uchun!\nModer kuchini his qiling 😎",
        "en": "🛡 <b>Moderator granted for {days} days</b> for {need} invited friends!\nFeel the power 😎",
    },
    "ref_info_alert": {
        "ru": "За каждого приглашённого друга: {n} 💎 (а если ты VIP — {v} 💎). Коины приходят автоматически, когда друг запускает бота.",
        "uz": "Har bir taklif qilingan do'st uchun: {n} 💎 (VIP bo'lsangiz — {v} 💎). Coinlar do'st botni ishga tushirganda avtomatik keladi.",
        "en": "For each invited friend: {n} 💎 (VIP gets {v} 💎). Coins arrive automatically when the friend starts the bot.",
    },
    "link_reward": {
        "ru": "🎁 <b>Бонус за активность по ссылке:</b> +{coins} 💎\nВсего действий: {n}. Так держать! 💕",
        "uz": "🎁 <b>Havola faolligi uchun bonus:</b> +{coins} 💎\nJami: {n}. Davom eting! 💕",
        "en": "🎁 <b>Activity bonus for your link:</b> +{coins} 💎\nTotal actions: {n}. Keep it up! 💕",
    },
    "ref_menu_hint": {
        "ru": "Меню «Пригласить» 👇",
        "uz": "«Taklif qilish» menyusi 👇",
        "en": "Invite menu 👇",
    },
    "mod_message": {
        "ru": "✉️ <b>Сообщение от модератора {name}</b>:\n{text}",
        "uz": "✉️ <b>{name} moderatordan xabar</b>:\n{text}",
        "en": "✉️ <b>Message from moderator {name}</b>:\n{text}",
    },
    "moder_help": {
        "ru": (
            "🛡 <b>Помощь по модерке</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Кнопки панели:</b>\n"
            "<blockquote>"
            "🚩 <b>Жалобы</b> — список жалоб, бан/отклонение\n"
            "🔨 <b>Бан / Разбан</b> — блок/разблок по ID\n"
            "📊 <b>Статистика</b> — цифры по боту\n"
            "📤 <b>Выгрузить пользователей</b> — список в .txt\n"
            "📢 <b>Обязательные каналы</b> — каналы для удаления сообщений: добавить/удалить (вкл/выкл подписки на вход — только у админа)"
            "</blockquote>\n"
            "<b>Скрытые команды</b> (просто напиши в чат):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — мониторинг рулетки (обычной 🎲 и 18+ 🔞).\n"
            "Показывает активные сессии (🔞 — это 18+ чат) → введи ID участника → видишь их переписку вживую.\n"
            "Кнопки «🚫 Бан 1️⃣/2️⃣» — забанить. Когда сессия завершится — авто-переход к другой; «🚪 Выйти» — выйти.\n\n"
            "✉️ <b>/next</b> — написать любому пользователю.\n"
            "Введи ID → текст. Юзеру придёт «Сообщение от модератора <i>твоё имя</i>»."
            "</blockquote>\n"
            "ℹ️ <i>Сообщения и чаты могут проверяться для безопасности.</i>"
        ),
        "uz": (
            "🛡 <b>Moderator yordami</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel tugmalari:</b>\n"
            "<blockquote>"
            "🚩 <b>Shikoyatlar</b> — shikoyatlar ro'yxati\n"
            "🔨 <b>Ban / Unban</b> — ID bo'yicha blok/blokdan chiqarish\n"
            "📊 <b>Statistika</b> — bot raqamlari\n"
            "📤 <b>Foydalanuvchilarni yuklash</b> — .txt ro'yxat\n"
            "📢 <b>Majburiy kanallar</b> — xabarni o'chirish uchun kanallar: qo'shish/o'chirish"
            "</blockquote>\n"
            "<b>Maxfiy buyruqlar</b> (chatga yozing):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — ruletka monitoringi (oddiy 🎲 va 18+ 🔞). Faol sessiyalar (🔞 — bu 18+ chat) → ishtirokchi ID sini kiriting → suhbatni jonli ko'rasiz. «🚫 Ban 1️⃣/2️⃣». «🚪 Chiqish».\n\n"
            "✉️ <b>/next</b> — istalgan foydalanuvchiga yozish. ID → matn."
            "</blockquote>\n"
            "ℹ️ <i>Xabarlar xavfsizlik uchun tekshirilishi mumkin.</i>"
        ),
        "en": (
            "🛡 <b>Moderator help</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Panel buttons:</b>\n"
            "<blockquote>"
            "🚩 <b>Reports</b> — review reports\n"
            "🔨 <b>Ban / Unban</b> — by ID\n"
            "📊 <b>Statistics</b> — bot numbers\n"
            "📤 <b>Export users</b> — .txt list\n"
            "📢 <b>Required channels</b> — channels for message deletion: add/remove"
            "</blockquote>\n"
            "<b>Hidden commands</b> (type in chat):\n"
            "<blockquote>"
            "🎲 <b>/tg</b> — roulette monitor (normal 🎲 and 18+ 🔞). Active sessions (🔞 = 18+ chat) → enter a participant ID → watch live. «🚫 Ban 1️⃣/2️⃣». «🚪 Exit».\n\n"
            "✉️ <b>/next</b> — message any user. ID → text."
            "</blockquote>\n"
            "ℹ️ <i>Messages and chats may be reviewed for safety.</i>"
        ),
    },
    "inactive_nudge": {
        "ru": (
            "👋 <b>Давно тебя не было в 𐌽ꤕ𐌗ተ!</b>\n"
            "⚠️ Чтобы не потерять свои данные (💎 коины, 👑 VIP, 🔗 ссылку) — "
            "просто нажми /start и загляни 🙂"
        ),
        "uz": (
            "👋 <b>Sizni 𐌽ꤕ𐌗ተ da ko'rmaganimizga ancha bo'ldi!</b>\n"
            "⚠️ Ma'lumotlaringizni (💎 coin, 👑 VIP, 🔗 havola) yo'qotmaslik uchun — "
            "/start ni bosing va kiring 🙂"
        ),
        "en": (
            "👋 <b>Haven't seen you in 𐌽ꤕ𐌗ተ for a while!</b>\n"
            "⚠️ So you don't lose your data (💎 coins, 👑 VIP, 🔗 link) — "
            "just tap /start and drop by 🙂"
        ),
    },
    "top_empty": {
        "ru": "Пока никто никого не пригласил. Будь первым! 🚀",
        "uz": "Hozircha hech kim hech kimni taklif qilmagan. Birinchi bo'ling! 🚀",
        "en": "No one has invited anyone yet. Be the first! 🚀",
    },
    "top_title": {
        "ru": "🏆 <b>Топ пригласивших</b>",
        "uz": "🏆 <b>Eng ko'p taklif qilganlar</b>",
        "en": "🏆 <b>Top inviters</b>",
    },
    "ref_coins_refunded": {
        "ru": "⚠️ Приглашённый друг заблокировал бота — <b>{n}</b> 💎 списаны обратно.",
        "uz": "⚠️ Taklif qilingan do'st botni blokladi — <b>{n}</b> 💎 qaytarib olindi.",
        "en": "⚠️ Your invited friend blocked the bot — <b>{n}</b> 💎 deducted back.",
    },
    "stars_unavailable": {
        "ru": "Покупка коинов пока недоступна.",
        "uz": "Coin sotib olish hozircha mavjud emas.",
        "en": "Buying coins is not available yet.",
    },
    "stars_pick_pkg": {
        "ru": "Выбери пакет на клавиатуре 👇",
        "uz": "Klaviaturadan paketni tanlang 👇",
        "en": "Choose a package on the keyboard 👇",
    },
    "pkg_unavailable": {
        "ru": "Пакет недоступен.",
        "uz": "Paket mavjud emas.",
        "en": "Package unavailable.",
    },
    "stars_buy_confirm": {
        "ru": "Купить «<b>{title}</b>» ({coins} 💎) за <b>⭐{stars}</b>?",
        "uz": "«<b>{title}</b>» ({coins} 💎) ni <b>⭐{stars}</b> ga sotib olasizmi?",
        "en": "Buy «<b>{title}</b>» ({coins} 💎) for <b>⭐{stars}</b>?",
    },
    "stars_invoice_sent": {
        "ru": "💳 Счёт выставлен ниже. Оплати кнопкой или вернись в меню 👇",
        "uz": "💳 Hisob-faktura quyida. Tugma orqali to'lang yoki menyuga qayting 👇",
        "en": "💳 The invoice is below. Pay with the button or return to the menu 👇",
    },
    "stars_pkg_desc": {
        "ru": "{coins} коинов для бота",
        "uz": "Bot uchun {coins} coin",
        "en": "{coins} coins for the bot",
    },
    "stars_paid": {
        "ru": "✅ <b>Оплата прошла!</b> Начислено <b>{coins}</b> 💎",
        "uz": "✅ <b>To'lov amalga oshdi!</b> <b>{coins}</b> 💎 qo'shildi",
        "en": "✅ <b>Payment successful!</b> <b>{coins}</b> 💎 added",
    },
    "msg_not_found": {
        "ru": "Сообщение не найдено 😕",
        "uz": "Xabar topilmadi 😕",
        "en": "Message not found 😕",
    },
    "reveal_profile_link": {
        "ru": "профиль",
        "uz": "profil",
        "en": "profile",
    },
    "btn_reveal_yes": {
        "ru": "✦ Да, раскрыть · 1⭐",
        "uz": "✦ Ha, aniqlash · 1⭐",
        "en": "✦ Yes, reveal · 1⭐",
    },
    "btn_cancel_accent": {
        "ru": "✦ Отмена",
        "uz": "✦ Bekor",
        "en": "✦ Cancel",
    },






    "vip_daily_bonus": {
        "ru": "🎁 Ежедневный VIP-бонус: <b>+{n}</b> 💎",
        "uz": "🎁 Kunlik VIP bonus: <b>+{n}</b> 💎",
        "en": "🎁 Daily VIP bonus: <b>+{n}</b> 💎",
    },
    "anon_write_prompt": {
        "ru": "Напишите ваш {label} текстом или отправьте голосовое сообщение:",
        "uz": "{label}ni matn bilan yozing yoki ovozli xabar yuboring:",
        "en": "Write your {label} as text or send a voice message:",
    },
    "anon_hdr_question": {
        "ru": "📩 <b>Вам пришёл анонимный вопрос</b>",
        "uz": "📩 <b>Sizga anonim savol keldi</b>",
        "en": "📩 <b>You received an anonymous question</b>",
    },
    "anon_hdr_valentine": {
        "ru": "💌 <b>Вам пришла анонимная валентинка</b>",
        "uz": "💌 <b>Sizga anonim valentinka keldi</b>",
        "en": "💌 <b>You received an anonymous valentine</b>",
    },
    "anon_hdr_reply": {
        "ru": "💬 <b>Вам ответили</b>",
        "uz": "💬 <b>Sizga javob berishdi</b>",
        "en": "💬 <b>You got a reply</b>",
    },
    "anon_hdr_new": {
        "ru": "📩 <b>Новое анонимное сообщение</b>",
        "uz": "📩 <b>Yangi anonim xabar</b>",
        "en": "📩 <b>New anonymous message</b>",
    },
    "anon_quote_reply": {
        "ru": "↩️ <i>в ответ на:</i>",
        "uz": "↩️ <i>javoban:</i>",
        "en": "↩️ <i>in reply to:</i>",
    },
    "preview_voice": {
        "ru": "🎤 голосовое сообщение",
        "uz": "🎤 ovozli xabar",
        "en": "🎤 voice message",
    },
    "preview_media": {
        "ru": "📎 медиа",
        "uz": "📎 media",
        "en": "📎 media",
    },
    "btn_reply": {
        "ru": "✦ Ответить",
        "uz": "✦ Javob",
        "en": "✦ Reply",
    },
    "btn_report": {
        "ru": "✦ Жалоба",
        "uz": "✦ Shikoyat",
        "en": "✦ Report",
    },
    "btn_reveal": {
        "ru": "✦ Узнать кто · 1⭐",
        "uz": "✦ Kim ekan · 1⭐",
        "en": "✦ Reveal who · 1⭐",
    },
    "btn_delete": {
        "ru": "✦ Удалить",
        "uz": "✦ O'chirish",
        "en": "✦ Delete",
    },
    "btn_subscribed": {
        "ru": "✅ Я подписался",
        "uz": "✅ Obuna bo'ldim",
        "en": "✅ I subscribed",
    },
    "anon_formats_vip": {
        "ru": ", фото, стикеры, гиф, видео",
        "uz": ", foto, stikerlar, gif, video",
        "en": ", photos, stickers, gifs, videos",
    },





    "gender_saved": {
        "ru": "✅ Готово! Ваш пол: <b>{g}</b>\n\nГлавное меню 👇",
        "uz": "✅ Tayyor! Jinsingiz: <b>{g}</b>\n\nAsosiy menyu 👇",
        "en": "✅ Done! Your gender: <b>{g}</b>\n\nMain menu 👇",
    },
    "lang_choose": {
        "ru": "🌐 Выберите язык интерфейса:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Choose the interface language:",
    },
    "lang_set": {
        "ru": "✅ Язык изменён на Русский 🇷🇺\n\nГлавное меню 👇",
        "uz": "✅ Til O'zbekchaga o'zgartirildi 🇺🇿\n\nAsosiy menyu 👇",
        "en": "✅ Language changed to English 🇬🇧\n\nMain menu 👇",
    },
    "welcome": {
        "ru": (
            "👋 <b>Привет, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — это анонимность без границ.\n"
            "<i>Тебе пишут тайно, а ты отвечаешь кому угодно.</i>\n\n"
            "<blockquote>🔗 Личная ссылка для анонимок\n"
            "🎲 Чат-рулетка по интересам\n"
            "🕵️ Никто не узнает, кто ты</blockquote>\n"
            "✨ Поехали — выбери свой пол 👇"
        ),
        "uz": (
            "👋 <b>Salom, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — chegarasiz anonimlik.\n"
            "<i>Sizga yashirin yozishadi, siz esa istalgan kishiga javob berasiz.</i>\n\n"
            "<blockquote>🔗 Anonim xabarlar uchun shaxsiy havola\n"
            "🎲 Qiziqish bo'yicha chat-ruletka\n"
            "🕵️ Hech kim siz kimligingizni bilmaydi</blockquote>\n"
            "✨ Boshladik — jinsingizni tanlang 👇"
        ),
        "en": (
            "👋 <b>Hi, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>𐌽ꤕ𐌗ተ</b> — anonymity without limits.\n"
            "<i>People message you secretly, and you reply to anyone.</i>\n\n"
            "<blockquote>🔗 Personal link for anonymous messages\n"
            "🎲 Chat roulette by interest\n"
            "🕵️ No one will know who you are</blockquote>\n"
            "✨ Let's go — choose your gender 👇"
        ),
    },
    "welcome_back": {
        "ru": (
            "✨ <b>С возвращением, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Рады видеть тебя снова в</i> <b>𐌽ꤕ𐌗ተ</b> 💙\n"
            "<blockquote>🔗 Делись ссылкой — лови анонимки\n"
            "🎲 Заходи в чат-рулетку\n"
            "👥 Зови друзей — забирай награды</blockquote>\n"
            "Главное меню 👇"
        ),
        "uz": (
            "✨ <b>Qaytganingiz bilan, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Sizni</i> <b>𐌽ꤕ𐌗ተ</b> <i>da yana ko'rganimizdan xursandmiz</i> 💙\n"
            "<blockquote>🔗 Havolani ulashing — anonim xabarlar oling\n"
            "🎲 Chat-ruletkaga kiring\n"
            "👥 Do'stlarni chaqiring — mukofot oling</blockquote>\n"
            "Asosiy menyu 👇"
        ),
        "en": (
            "✨ <b>Welcome back, {name}!</b> ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Glad to see you again in</i> <b>𐌽ꤕ𐌗ተ</b> 💙\n"
            "<blockquote>🔗 Share your link — get anonymous messages\n"
            "🎲 Jump into chat roulette\n"
            "👥 Invite friends — claim rewards</blockquote>\n"
            "Main menu 👇"
        ),
    },
    "help": {
        "ru": (
            "ℹ️ <b>Как пользоваться ботом 𐌽ꤕ𐌗ተ</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Здесь тебе пишут анонимно, и ты можешь общаться с незнакомцами. Всё просто 👇</i>\n\n"
            "📲 <b>Кнопки меню — что делают:</b>\n"
            "<blockquote>"
            "🔗 <b>Моя ссылка</b> — твоя личная ссылка. Кинь её в сторис или другу — и тебе будут писать анонимные сообщения. Ты не узнаешь кто (если не откроешь за ⭐).\n\n"
            "🎲 <b>Чат-рулетка</b> — нажми, выбери кого ищешь (парня/девушку) и бот соединит тебя со случайным собеседником. Не понравился — жми «Далее».\n\n"
            "👤 <b>Профиль</b> — тут твои данные: пол, возраст, коины 💎, статус VIP, сколько друзей пригласил. Здесь же 🎁 <b>Подарить коины</b> — перевести коины другу по его ID.\n\n"
            "🛒 <b>Магазин</b> — здесь тратишь коины 💎 на VIP и другие штуки.\n\n"
            "👥 <b>Пригласить</b> — зови друзей по ссылке. За каждого друга <b>+50</b> 💎 (а если ты VIP — <b>+100</b> 💎). Твой друг тоже получит <b>+100</b> 💎 за вход (а по ссылке VIP — <b>+200</b> 💎). Внизу 🏆 <b>Топ пригласивших</b>.\n\n"
            "💎 <b>Купить коины</b> — пополнить баланс коинов через Telegram Stars ⭐.\n\n"
            "🔞 <b>18+</b> — зона для взрослых (откроется <b>только если тебе есть 18</b>). Внутри: 🔞 рулетка с поиском по возрасту, 🛒 18+ магазин (купить доступ за коины) и 🎁 <b>Подарить 18+</b> — подарить другу доступ по его ID.\n\n"
            "🌐 <b>Язык</b> — поменять язык: русский, узбекский, английский."
            "</blockquote>\n"
            "💎 <b>Что такое коины?</b>\n"
            "<i>Это внутренняя валюта бота. Зарабатывай их за друзей и активность или покупай за ⭐, а трать в магазине.</i>\n\n"
            "👑 <b>Что даёт VIP (премиум):</b>\n"
            "<blockquote>"
            "• пишешь анонимки <b>без ограничений</b> (у обычных — лимит 20 в день)\n"
            "• <b>−20%</b> на всё в магазине (цены сразу ниже)\n"
            "• <b>+5</b> 💎 в подарок каждый день\n"
            "• тебя находят в рулетке <b>быстрее</b> (приоритет)\n"
            "• можно слать фото, видео, гиф и стикеры в анонимках + корона 👑\n"
            "• меняй свою ссылку <b>сколько хочешь</b> (у обычных — раз в неделю)"
            "</blockquote>\n"
            "🛡 <i>Для безопасности переписки могут проверяться модераторами.</i>\n"
            "💬 <i>Выбери нужную кнопку в меню снизу 👇</i>"
        ),
        "uz": (
            "ℹ️ <b>𐌽ꤕ𐌗ተ botidan qanday foydalanish</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Bu yerda sizga anonim yozishadi va notanishlar bilan suhbatlashasiz. Hammasi oddiy 👇</i>\n\n"
            "📲 <b>Menyu tugmalari — nima qiladi:</b>\n"
            "<blockquote>"
            "🔗 <b>Havolam</b> — shaxsiy havolangiz. Uni storis yoki do'stga tashlang — sizga anonim xabar yozishadi. Kimligini bilmaysiz (⭐ evaziga ochmasangiz).\n\n"
            "🎲 <b>Chat-ruletka</b> — bosing, kimni qidirayotganingizni tanlang (yigit/qiz) va bot sizni tasodifiy suhbatdosh bilan bog'laydi. Yoqmasa — «Keyingi».\n\n"
            "👤 <b>Profil</b> — ma'lumotlaringiz: jins, yosh, coinlar 💎, VIP holati, nechta do'st taklif qilgansiz. Shu yerda 🎁 <b>Coin sovg'a qilish</b> — do'stga ID bo'yicha coin o'tkazish.\n\n"
            "🛒 <b>Do'kon</b> — bu yerda coinlarni 💎 VIP va boshqa narsalarga sarflaysiz.\n\n"
            "👥 <b>Taklif qilish</b> — do'stlarni havola orqali chaqiring. Har bir do'st uchun <b>+50</b> 💎 (VIP bo'lsangiz — <b>+100</b> 💎). Do'stingiz ham kirgani uchun <b>+100</b> 💎 oladi (VIP havola orqali — <b>+200</b> 💎). Pastda 🏆 <b>Top taklif qilganlar</b>.\n\n"
            "💎 <b>Coin sotib olish</b> — Telegram Stars ⭐ orqali coin balansini to'ldirish.\n\n"
            "🔞 <b>18+</b> — kattalar zonasi (faqat <b>18 yoshdan</b> ochiladi). Ichida: 🔞 yosh bo'yicha ruletka, 🛒 18+ do'kon (coinga kirish sotib olish) va 🎁 <b>18+ sovg'a qilish</b> — do'stga ID bo'yicha kirish sovg'a qilish.\n\n"
            "🌐 <b>Til</b> — tilni o'zgartirish: rus, o'zbek, ingliz."
            "</blockquote>\n"
            "💎 <b>Coin nima?</b>\n"
            "<i>Bu botning ichki valyutasi. Do'stlar va faollik uchun ishlang yoki ⭐ ga sotib oling, do'konda sarflang.</i>\n\n"
            "👑 <b>VIP (premium) nima beradi:</b>\n"
            "<blockquote>"
            "• anonim xabarlarni <b>cheksiz</b> yozasiz (oddiylarda — kuniga 20 ta)\n"
            "• do'konda hammasiga <b>−20%</b> (narxlar darrov pastroq)\n"
            "• har kuni <b>+5</b> 💎 sovg'a\n"
            "• ruletkada sizni <b>tezroq</b> topishadi (ustunlik)\n"
            "• anonimlarda foto, video, gif, stiker + toj 👑\n"
            "• havolangizni <b>xohlagancha</b> o'zgartirasiz (oddiylarda — haftada bir)"
            "</blockquote>\n"
            "🛡 <i>Xavfsizlik uchun yozishmalar moderatorlar tomonidan tekshirilishi mumkin.</i>\n"
            "💬 <i>Pastdagi menyudan kerakli tugmani tanlang 👇</i>"
        ),
        "en": (
            "ℹ️ <b>How to use the 𐌽ꤕ𐌗ተ bot</b> 💙\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>People message you anonymously here, and you can chat with strangers. It's simple 👇</i>\n\n"
            "📲 <b>Menu buttons — what they do:</b>\n"
            "<blockquote>"
            "🔗 <b>My link</b> — your personal link. Post it in stories or send to a friend — people will message you anonymously. You won't know who (unless you reveal for ⭐).\n\n"
            "🎲 <b>Chat roulette</b> — tap it, choose who you want (a guy/a girl) and the bot connects you with a random partner. Don't like them — tap «Next».\n\n"
            "👤 <b>Profile</b> — your info: gender, age, coins 💎, VIP status, how many friends you invited. Also 🎁 <b>Gift coins</b> — send coins to a friend by their ID.\n\n"
            "🛒 <b>Shop</b> — spend your coins 💎 on VIP and other items here.\n\n"
            "👥 <b>Invite</b> — invite friends via your link. <b>+50</b> 💎 per friend (VIP gets <b>+100</b> 💎). Your friend also gets <b>+100</b> 💎 for joining (via a VIP link — <b>+200</b> 💎). Below: 🏆 <b>Top inviters</b>.\n\n"
            "💎 <b>Buy coins</b> — top up your coin balance with Telegram Stars ⭐.\n\n"
            "🔞 <b>18+</b> — an adult zone (opens <b>only if you're 18+</b>). Inside: 🔞 roulette with age search, 🛒 18+ shop (buy access with coins) and 🎁 <b>Gift 18+</b> — gift a friend access by their ID.\n\n"
            "🌐 <b>Language</b> — change language: Russian, Uzbek, English."
            "</blockquote>\n"
            "💎 <b>What are coins?</b>\n"
            "<i>It's the bot's in-app currency. Earn them for friends and activity or buy with ⭐, and spend in the shop.</i>\n\n"
            "👑 <b>What VIP (premium) gives:</b>\n"
            "<blockquote>"
            "• send anonymous messages <b>with no limit</b> (regular users — 20 per day)\n"
            "• <b>−20%</b> off everything in the shop (prices shown lower right away)\n"
            "• <b>+5</b> 💎 gift every day\n"
            "• you get matched <b>faster</b> in roulette (priority)\n"
            "• send photos, videos, gifs and stickers in anon messages + crown 👑\n"
            "• change your link <b>as often as you want</b> (regular — once a week)"
            "</blockquote>\n"
            "🛡 <i>For safety, conversations may be reviewed by moderators.</i>\n"
            "💬 <i>Pick the button you need in the menu below 👇</i>"
        ),
    },
    # === Профиль ===
    "profile_text": {
        "ru": "👤 <b>Ваш профиль</b>\n\nПол: <b>{gender}</b>\nПоиск в рулетке: <b>{pref}</b>\nКоины: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
        "uz": "👤 <b>Profilingiz</b>\n\nJins: <b>{gender}</b>\nRuletkada qidiruv: <b>{pref}</b>\nCoinlar: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
        "en": "👤 <b>Your profile</b>\n\nGender: <b>{gender}</b>\nRoulette search: <b>{pref}</b>\nCoins: <b>{coins}</b> 💎\nVIP: <b>{vip}</b>",
    },
    "choose_action": {
        "ru": "Выберите действие на клавиатуре 👇",
        "uz": "Klaviaturadan amalni tanlang 👇",
        "en": "Choose an action on the keyboard 👇",
    },
    "choose_new_gender": {
        "ru": "Выберите новый пол:",
        "uz": "Yangi jinsni tanlang:",
        "en": "Choose new gender:",
    },
    # === Ссылка ===
    "link_menu": {
        "ru": "Выберите действие на клавиатуре 👇",
        "uz": "Klaviaturadan amalni tanlang 👇",
        "en": "Choose an action on the keyboard 👇",
    },
    "link_no_link": {
        "ru": "У вас ещё нет ссылки.\nПридумайте код (до 10 символов: латиница, цифры, «-», «_»):",
        "uz": "Sizda hali havola yo'q.\nKod kiriting (10 ta belgigacha: lotin, raqam, «-», «_»):",
        "en": "You don't have a link yet.\nCreate a code (up to 10 characters: latin, digits, «-», «_»):",
    },
    "link_change": {
        "ru": "Придумайте новый код (до 10 символов: латиница, цифры, «-», «_»).\nСтарая ссылка сразу перестанет работать.",
        "uz": "Yangi kod kiriting (10 ta belgigacha: lotin, raqam, «-», «_»).\nEski havola darhol ishlamay qoladi.",
        "en": "Enter a new code (up to 10 characters: latin, digits, «-», «_»).\nThe old link will stop working immediately.",
    },
    "link_invalid": {
        "ru": "Код должен быть до 10 символов (латиница, цифры, «-», «_»). Попробуйте ещё раз:",
        "uz": "Kod 10 ta belgigacha bo'lishi kerak (lotin, raqam, «-», «_»). Qayta urinib ko'ring:",
        "en": "Code must be up to 10 characters (latin, digits, «-», «_»). Try again:",
    },
    "link_taken": {
        "ru": "Этот код уже занят, попробуйте другой:",
        "uz": "Bu kod band, boshqasini kiriting:",
        "en": "This code is already taken, try another one:",
    },
    "link_limit": {
        "ru": "Ссылку можно сменить через {days} дн. Или купи VIP для снятия ограничения 👑",
        "uz": "Havolani {days} kundan keyin o'zgartirish mumkin. Yoki cheklovni olib tashlash uchun VIP sotib oling 👑",
        "en": "You can change the link in {days} days. Or buy VIP to remove the limit 👑",
    },
    "cancelled": {
        "ru": "Отменено.",
        "uz": "Bekor qilindi.",
        "en": "Cancelled.",
    },
    # === Анонимка ===
    "anon_what_send": {
        "ru": "Что хотите отправить?",
        "uz": "Nima yubormoqchisiz?",
        "en": "What would you like to send?",
    },
    "anon_write": {
        "ru": "Напишите ваш {label} текстом или отправьте голосовое сообщение:",
        "uz": "{label}ni matn yoki ovozli xabar sifatida yuboring:",
        "en": "Write your {label} as text or send a voice message:",
    },
    "anon_label_question": {
        "ru": "вопрос",
        "uz": "savol",
        "en": "question",
    },
    "anon_label_valentine": {
        "ru": "валентинку",
        "uz": "valentinka",
        "en": "valentine",
    },
    "anon_sent": {
        "ru": "✅ Отправлено",
        "uz": "✅ Yuborildi",
        "en": "✅ Sent",
    },
    "anon_failed": {
        "ru": "Не удалось доставить сообщение получателю 😕",
        "uz": "Xabarni yetkazib bo'lmadi 😕",
        "en": "Failed to deliver the message 😕",
    },
    "anon_reply_prompt": {
        "ru": "Напиши ответ (текст или голосовое):",
        "uz": "Javob yozing (matn yoki ovozli):",
        "en": "Write your reply (text or voice):",
    },
    "anon_reply_sent": {
        "ru": "Ответ отправлен ✅",
        "uz": "Javob yuborildi ✅",
        "en": "Reply sent ✅",
    },
    "anon_reply_failed": {
        "ru": "Не удалось доставить ответ 😕",
        "uz": "Javobni yetkazib bo'lmadi 😕",
        "en": "Failed to deliver the reply 😕",
    },
    "anon_not_found": {
        "ru": "Сообщение не найдено.",
        "uz": "Xabar topilmadi.",
        "en": "Message not found.",
    },
    "anon_limit": {
        "ru": "Лимит {n} сообщений в сутки исчерпан. VIP снимает это ограничение 👑 (см. Магазин).",
        "uz": "Kuniga {n} ta xabar limiti tugadi. VIP bu cheklovni olib tashlaydi 👑 (Do'konga qarang).",
        "en": "Daily limit of {n} messages reached. VIP removes this limit 👑 (see Shop).",
    },
    "anon_vip_media": {
        "ru": "📷 Фото/стикеры/гиф/видео могут отправлять только VIP 👑 (см. Магазин).\nОтправь текст или голосовое.",
        "uz": "📷 Foto/stikerlar/gif/video faqat VIP 👑 yuborishi mumkin (Do'konga qarang).\nMatn yoki ovozli yuboring.",
        "en": "📷 Photos/stickers/gifs/videos can only be sent by VIP 👑 (see Shop).\nSend text or voice.",
    },
    "anon_formats": {
        "ru": "Поддерживается текст, голосовое{vip}.",
        "uz": "Matn, ovozli{vip} qo'llab-quvvatlanadi.",
        "en": "Supported: text, voice{vip}.",
    },
    "anon_invalid_link": {
        "ru": "Эта ссылка недействительна 😕",
        "uz": "Bu havola yaroqsiz 😕",
        "en": "This link is invalid 😕",
    },
    "anon_own_link": {
        "ru": "Это ваша собственная ссылка 🙂 Самому себе писать нельзя.",
        "uz": "Bu sizning shaxsiy havolangiz 🙂 O'zingizga yozib bo'lmaydi.",
        "en": "This is your own link 🙂 You can't write to yourself.",
    },
    "anon_banned": {
        "ru": "Вы временно не можете писать этому пользователю 🚫",
        "uz": "Siz bu foydalanuvchiga vaqtincha yoza olmaysiz 🚫",
        "en": "You are temporarily unable to write to this user 🚫",
    },
    # === Удаление ===
    "del_both": {
        "ru": "Удалено у обоих ✅",
        "uz": "Ikkalasida ham o'chirildi ✅",
        "en": "Deleted for both ✅",
    },
    "del_only_me": {
        "ru": "Удалено у тебя. У собеседника не вышло (старше 48ч?).",
        "uz": "Sizda o'chirildi. Suhbatdoshda iloji bo'lmadi (48 soatdan eski?).",
        "en": "Deleted for you. Couldn't delete for the other (older than 48h?).",
    },
    "del_stale": {
        "ru": "Сообщение устарело (нет в базе) — удалено только у тебя.",
        "uz": "Xabar eskirgan (bazada yo'q) — faqat sizda o'chirildi.",
        "en": "Message is stale (not in DB) — deleted only for you.",
    },
    # === Рулетка ===
    "roulette_searching": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "search_still": {
        "ru": "🔎 Всё ещё ищем тебе собеседника… ⏳\nТы в поиске уже <b>{min}</b> мин. Подожди или нажми «⛔ Отменить поиск».",
        "uz": "🔎 Hali ham suhbatdosh qidirilmoqda… ⏳\nSiz <b>{min}</b> daqiqadan beri qidiruvdasiz. Kuting yoki «⛔ Qidiruvni bekor qilish».",
        "en": "🔎 Still looking for a partner… ⏳\nYou've been searching for <b>{min}</b> min. Wait or tap «⛔ Stop search».",
    },
    "search_timeout": {
        "ru": "🔍 <b>Поиск остановлен</b> — за {min} мин подходящий собеседник не нашёлся 😕\nПопробуй ещё раз чуть позже!",
        "uz": "🔍 <b>Qidiruv to'xtatildi</b> — {min} daqiqada mos suhbatdosh topilmadi 😕\nBiroz keyin yana urinib ko'ring!",
        "en": "🔍 <b>Search stopped</b> — no match found in {min} min 😕\nTry again a bit later!",
    },
    "roulette_found": {
        "ru": (
            "🎲✨ <b>СОБЕСЕДНИК НАЙДЕН</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Пиши первым — не стесняйся!</i>\n"
            "<blockquote>"
            "🙈 Полная анонимность\n"
            "📎 Можно слать фото, голосовые и стикеры"
            "</blockquote>\n"
            "<i>«➡️ Далее» — другой собеседник · «⏹️ Стоп» — выйти</i>"
        ),
        "uz": (
            "🎲✨ <b>SUHBATDOSH TOPILDI</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Birinchi bo'lib yozing — uyalmang!</i>\n"
            "<blockquote>"
            "🙈 To'liq anonimlik\n"
            "📎 Foto, ovozli xabar va stikerlar yuborish mumkin"
            "</blockquote>\n"
            "<i>«➡️ Keyingi» — boshqa suhbatdosh · «⏹️ To'xtatish» — chiqish</i>"
        ),
        "en": (
            "🎲✨ <b>A PARTNER IS FOUND</b> ✨🎲\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <i>Write first — don't be shy!</i>\n"
            "<blockquote>"
            "🙈 Full anonymity\n"
            "📎 You can send photos, voice and stickers"
            "</blockquote>\n"
            "<i>«➡️ Next» — another partner · «⏹️ Stop» — exit</i>"
        ),
    },
    "roulette_left": {
        "ru": "Собеседник покинул чат.",
        "uz": "Suhbatdosh chatni tark etdi.",
        "en": "Partner left the chat.",
    },
    "roulette_already_chat": {
        "ru": "Вы уже в чате. Пишите собеседнику или используйте кнопки ниже 👇",
        "uz": "Siz allaqachon chatsiz. Suhbatdoshga yozing yoki pastdagi tugmalardan foydalaning 👇",
        "en": "You are already in a chat. Write to your partner or use the buttons below 👇",
    },
    "roulette_already_searching": {
        "ru": "Идёт поиск собеседника… ⏳",
        "uz": "Suhbatdosh qidirilmoqda… ⏳",
        "en": "Searching for a partner… ⏳",
    },
    "roulette_stop": {
        "ru": "Поиск отменён.",
        "uz": "Qidiruv bekor qilindi.",
        "en": "Search cancelled.",
    },
    # === Жалоба ===
    "report_choose": {
        "ru": "Выбери причину жалобы:",
        "uz": "Shikoyat sababini tanlang:",
        "en": "Choose the report reason:",
    },
    "report_sent": {
        "ru": "Жалоба отправлена админу на рассмотрение 🚩",
        "uz": "Shikoyat adminга ko'rib chiqish uchun yuborildi 🚩",
        "en": "Report sent to admin for review 🚩",
    },
    "report_cancelled": {
        "ru": "Жалоба отменена.",
        "uz": "Shikoyat bekor qilindi.",
        "en": "Report cancelled.",
    },
    # === Подписка ===
    "sub_required": {
        "ru": "Чтобы продолжить, подпишись на канал(ы):\n\n",
        "uz": "Davom etish uchun kanal(lar)ga obuna bo'ling:\n\n",
        "en": "To continue, subscribe to the channel(s):\n\n",
    },
    "sub_not_found": {
        "ru": "Подписка не найдена, проверь ещё раз 🙏",
        "uz": "Obuna topilmadi, qayta tekshiring 🙏",
        "en": "Subscription not found, check again 🙏",
    },
    # === Магазин ===
    "shop_title": {
        "ru": "🛒 <b>Магазин</b>\nВыберите товар 👇",
        "uz": "🛒 <b>Do'kon</b>\nMahsulotni tanlang 👇",
        "en": "🛒 <b>Shop</b>\nChoose an item 👇",
    },
    "shop_empty": {
        "ru": "🛒 <b>Магазин пока пуст.</b>",
        "uz": "🛒 <b>Do'kon hali bo'sh.</b>",
        "en": "🛒 <b>The shop is empty.</b>",
    },
    "shop_vip_note": {
        "ru": "👑 <i>Цены показаны с твоей VIP-скидкой −20%.</i>",
        "uz": "👑 <i>Narxlar VIP chegirmangiz −20% bilan ko'rsatilgan.</i>",
        "en": "👑 <i>Prices shown with your VIP −20% discount.</i>",
    },
    "18plus_shop_title": {
        "ru": "🔞 <b>18+ Магазин</b>\nВыберите товар 👇",
        "uz": "🔞 <b>18+ Do'kon</b>\nMahsulotni tanlang 👇",
        "en": "🔞 <b>18+ Shop</b>\nChoose an item 👇",
    },
    "18plus_shop_empty": {
        "ru": "🔞 <b>Магазин 18+ пока пуст.</b>",
        "uz": "🔞 <b>18+ do'kon hali bo'sh.</b>",
        "en": "🔞 <b>The 18+ shop is empty.</b>",
    },
    "stars_title": {
        "ru": "💎 <b>Покупка коинов за Telegram Stars</b>\nВыбери пакет 👇",
        "uz": "💎 <b>Telegram Stars uchun coin sotib olish</b>\nPaketni tanlang 👇",
        "en": "💎 <b>Buy coins with Telegram Stars</b>\nChoose a package 👇",
    },
    # === Рефералы ===
    "reveal_title": {
        "ru": "👁 Раскрыть отправителя",
        "uz": "👁 Yuboruvchini aniqlash",
        "en": "👁 Reveal sender",
    },
    "reveal_desc": {
        "ru": "Узнай, кто отправил тебе это анонимное сообщение",
        "uz": "Sizga bu anonim xabarni kim yuborganini biling",
        "en": "Find out who sent you this anonymous message",
    },
    "reveal_result": {
        "ru": "👁 <b>Отправитель раскрыт!</b>\n\nИмя: <b>{name}</b>\nНик: {uname}\nID: <code>{tid}</code>",
        "uz": "👁 <b>Yuboruvchi aniqlandi!</b>\n\nIsm: <b>{name}</b>\nNik: {uname}\nID: <code>{tid}</code>",
        "en": "👁 <b>Sender revealed!</b>\n\nName: <b>{name}</b>\nUsername: {uname}\nID: <code>{tid}</code>",
    },
    "reveal_confirm": {
        "ru": "👁 Раскрыть отправителя этого сообщения за <b>1 ⭐ Star</b>?",
        "uz": "👁 Ushbu xabar yuboruvchini <b>1 ⭐ Star</b> uchun aniqlaysizmi?",
        "en": "👁 Reveal the sender of this message for <b>1 ⭐ Star</b>?",
    },
    "reveal_paying": {
        "ru": "⏳ Оплатите инвойс ниже...",
        "uz": "⏳ Quyidagi hisob-fakturani to'lang...",
        "en": "⏳ Pay the invoice below...",
    },
    "reveal_only_recipient": {
        "ru": "Только получатель может раскрыть отправителя.",
        "uz": "Faqat qabul qiluvchi yuboruvchini aniqlay oladi.",
        "en": "Only the recipient can reveal the sender.",
    },
    "invite_text": {
        "ru": "👥 <b>Пригласи друзей и получи коины!</b>\n\n🔗 Твоя реф-ссылка:\n{link}\n\n+{bonus} 💎 за каждого друга.",
        "uz": "👥 <b>Do'stlarni taklif qiling va coin oling!</b>\n\n🔗 Ref-havolangiz:\n{link}\n\n+{bonus} 💎 har bir do'st uchun.",
        "en": "👥 <b>Invite friends and earn coins!</b>\n\n🔗 Your referral link:\n{link}\n\n+{bonus} 💎 for each friend.",
    },
    # === 18+ ===
    "age_gate_title": {
        "ru": "🔞 <b>Возрастной портал</b> 🔞\n\nЭтот раздел доступен только пользователям 18+",
        "uz": "🔞 <b>Yosh portali</b> 🔞\n\nBu bo'lim faqat 18+ yoshdagi foydalanuvchilar uchun",
        "en": "🔞 <b>Age Gate</b> 🔞\n\nThis section is only for users 18+",
    },
    "age_gate_intro": {
        "ru": (
            "Добро пожаловать в 18+ зону! 🎉\n"
            "Здесь только взрослые собеседники и контент.\n"
            "Перед входом подтвердите свой возраст."
        ),
        "uz": (
            "18+ zonaga xush kelibsiz! 🎉\n"
            "Bu yerda faqat kattalar suhbatdoshlari va kontent bor.\n"
            "Kirishdan oldin yoshingizni tasdiqlang."
        ),
        "en": (
            "Welcome to the 18+ zone! 🎉\n"
            "Here you'll find only adult partners and content.\n"
            "Please verify your age before entering."
        ),
    },
    "age_consent_text": {
        "ru": (
            "🔞 <b>18+ ЧАТ ДЛЯ ВЗРОСЛЫХ</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Добро пожаловать! Это <b>не обычный Next</b> — это зона для взрослых 18+.\n\n"
            "<b>✅ Здесь можно:</b>\n"
            "<blockquote>"
            "• общаться свободно на любые темы для взрослых\n"
            "• отправлять фото, видео, стикеры, голосовые\n"
            "• быть откровенным — это чат для взрослых"
            "</blockquote>\n"
            "<b>🚫 Здесь нельзя:</b>\n"
            "<blockquote>"
            "• контент с несовершеннолетними (строгий бан)\n"
            "• насилие, угрозы, шантаж\n"
            "• мошенничество и спам\n"
            "• продажа запрещённых веществ"
            "</blockquote>\n"
            "🛡 <i>Чаты могут проверяться модераторами. За нарушения — вечный бан.</i>\n\n"
            "Нажимая «Согласиться», вы подтверждаете, что вам <b>18+</b> и принимаете правила 👇"
        ),
        "uz": (
            "🔞 <b>18+ KATTALAR CHATI</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Xush kelibsiz! Bu <b>oddiy Next emas</b> — bu 18+ kattalar zonasi.\n\n"
            "<b>✅ Bu yerda mumkin:</b>\n"
            "<blockquote>"
            "• kattalar uchun istalgan mavzuda erkin muloqot\n"
            "• foto, video, stiker, ovozli xabar yuborish\n"
            "• ochiq bo'lish — bu kattalar chati"
            "</blockquote>\n"
            "<b>🚫 Bu yerda mumkin emas:</b>\n"
            "<blockquote>"
            "• voyaga yetmaganlar bilan kontent (qattiq ban)\n"
            "• zo'ravonlik, tahdid, shantaj\n"
            "• firibgarlik va spam\n"
            "• taqiqlangan moddalar savdosi"
            "</blockquote>\n"
            "🛡 <i>Chatlar moderatorlar tomonidan tekshirilishi mumkin. Buzilish uchun — abadiy ban.</i>\n\n"
            "«Roziman» tugmasini bosib, siz <b>18+</b> ekanligingizni tasdiqlaysiz 👇"
        ),
        "en": (
            "🔞 <b>18+ ADULT CHAT</b> 🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome! This is <b>not the usual Next</b> — it's an adult 18+ zone.\n\n"
            "<b>✅ Here you can:</b>\n"
            "<blockquote>"
            "• chat freely on any adult topics\n"
            "• send photos, videos, stickers, voice\n"
            "• be open — it's an adult chat"
            "</blockquote>\n"
            "<b>🚫 Here you cannot:</b>\n"
            "<blockquote>"
            "• content with minors (strict ban)\n"
            "• violence, threats, blackmail\n"
            "• fraud and spam\n"
            "• selling illegal substances"
            "</blockquote>\n"
            "🛡 <i>Chats may be reviewed by moderators. Violations = permanent ban.</i>\n\n"
            "By tapping «I agree» you confirm you are <b>18+</b> and accept the rules 👇"
        ),
    },
    "age_verify_ask_photo": {
        "ru": (
            "📷 <b>Подтверждение возраста</b>\n\n"
            "Отправьте фото документа, подтверждающего ваш возраст (можно прикрыть личные данные, оставьте дату рождения).\n"
            "Администратор проверит и откроет доступ."
        ),
        "uz": (
            "📷 <b>Yoshni tasdiqlash</b>\n\n"
            "Yoshingizni tasdiqlovchi hujjat fotosini yuboring (shaxsiy ma'lumotlarni yoping, tug'ilgan sanani qoldiring).\n"
            "Administrator tekshirib, kirishni ochadi."
        ),
        "en": (
            "📷 <b>Age verification</b>\n\n"
            "Send a photo of a document confirming your age (you may hide personal data, leave the birth date).\n"
            "The administrator will review and grant access."
        ),
    },
    "roulette_found_18plus": {
        "ru": (
            "🔞✨ <b>СОБЕСЕДНИК 18+ НАЙДЕН</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>Это закрытый чат для взрослых.</i>\n"
            "<blockquote>"
            "✅ Можно: общаться свободно, слать фото, видео, голосовые\n"
            "🚫 Нельзя: то, что запрещено правилами"
            "</blockquote>\n"
            "🔥 <b>Приятного общения!</b>\n"
            "<i>«➡️ Далее» — сменить собеседника · «⏹️ Стоп» — выйти</i>"
        ),
        "uz": (
            "🔞✨ <b>18+ SUHBATDOSH TOPILDI</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>Bu kattalar uchun yopiq chat.</i>\n"
            "<blockquote>"
            "✅ Mumkin: erkin muloqot, foto, video, ovozli xabar\n"
            "🚫 Mumkin emas: qoidalar bilan taqiqlangan narsalar"
            "</blockquote>\n"
            "🔥 <b>Yoqimli muloqot!</b>\n"
            "<i>«➡️ Keyingi» — suhbatdoshni almashtirish · «⏹️ To'xtatish» — chiqish</i>"
        ),
        "en": (
            "🔞✨ <b>AN 18+ PARTNER IS FOUND</b> ✨🔞\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💋 <i>This is a private adult chat.</i>\n"
            "<blockquote>"
            "✅ Allowed: chat freely, send photos, videos, voice\n"
            "🚫 Forbidden: anything against the rules"
            "</blockquote>\n"
            "🔥 <b>Enjoy!</b>\n"
            "<i>«➡️ Next» — change partner · «⏹️ Stop» — exit</i>"
        ),
    },
    "age_select_title": {
        "ru": "📅 <b>Ваш возраст?</b>",
        "uz": "📅 <b>Sizning yoshingiz?</b>",
        "en": "📅 <b>How old are you?</b>",
    },
    "age_search_title": {
        "ru": "🔎 <b>Кого ищем по возрасту?</b>\nВыберите диапазон 👇",
        "uz": "🔎 <b>Qaysi yoshdagini qidiramiz?</b>\nDiapazonni tanlang 👇",
        "en": "🔎 <b>What age are you looking for?</b>\nChoose a range 👇",
    },
    "age_register_ask": {
        "ru": "📅 <b>Сколько вам лет?</b>\n\nНапишите ваш возраст числом (например: 21).\nЭто нужно для доступа к разделу 🔞 18+. Если меньше 18 — раздел будет недоступен.",
        "uz": "📅 <b>Yoshingiz nechada?</b>\n\nYoshingizni raqam bilan yozing (masalan: 21).\nBu 🔞 18+ bo'limiga kirish uchun kerak. 18 dan kichik bo'lsa — bo'lim yopiq bo'ladi.",
        "en": "📅 <b>How old are you?</b>\n\nType your age as a number (e.g. 21).\nNeeded for access to the 🔞 18+ section. If under 18 — the section will be unavailable.",
    },
    "age_enter_number": {
        "ru": "Введите ваш возраст числом (например: 21):",
        "uz": "Yoshingizni raqam bilan kiriting (masalan: 21):",
        "en": "Enter your age as a number (e.g. 21):",
    },
    "age_saved": {
        "ru": "✅ Возраст сохранён: <b>{age}</b>\n\nГлавное меню 👇",
        "uz": "✅ Yosh saqlandi: <b>{age}</b>\n\nAsosiy menyu 👇",
        "en": "✅ Age saved: <b>{age}</b>\n\nMain menu 👇",
    },
    "age_under18_saved": {
        "ru": "Понятно. Раздел 🔞 18+ будет недоступен.\nЕсли вам исполнилось 18 — измените возраст в Профиле и подтвердите его.\n\nГлавное меню 👇",
        "uz": "Tushunarli. 🔞 18+ bo'limi yopiq bo'ladi.\nAgar 18 yoshga to'lgan bo'lsangiz — Profilda yoshni o'zgartiring va tasdiqlang.\n\nAsosiy menyu 👇",
        "en": "Got it. The 🔞 18+ section will be unavailable.\nIf you've turned 18 — change your age in Profile and verify it.\n\nMain menu 👇",
    },
    "age_18_20": {
        "ru": "18/20",
        "uz": "18/20",
        "en": "18/20",
    },
    "age_20_22": {
        "ru": "20/22",
        "uz": "20/22",
        "en": "20/22",
    },
    "age_22_25": {
        "ru": "22/25",
        "uz": "22/25",
        "en": "22/25",
    },
    "age_25_30": {
        "ru": "25/30",
        "uz": "25/30",
        "en": "25/30",
    },
    "age_30_plus": {
        "ru": "30+",
        "uz": "30+",
        "en": "30+",
    },
    "age_under_18": {
        "ru": "Менее 18",
        "uz": "18 dan kichik",
        "en": "Under 18",
    },
    "age_gate_button": {
        "ru": "🔞 18+ контент",
        "uz": "🔞 18+ kontent",
        "en": "🔞 18+ content",
    },
    "age_verification_required": {
        "ru": (
            "⏳ <b>Ваш возраст: {age}</b>\n\n"
            "Этот контент доступен только пользователям 18+.\n"
            "Если вам меньше 18, вы можете запросить подтверждение возраста, загрузив фото."
        ),
        "uz": (
            "⏳ <b>Sizning yoshingiz: {age}</b>\n\n"
            "Bu kontent faqat 18+ foydalanuvchilar uchun.\n"
            "Agar siz 18 yoshdan kichik bo'lsangiz, foto yuklab yoshingizni tasdiqlash so'rovi yubora olasiz."
        ),
        "en": (
            "⏳ <b>Your age: {age}</b>\n\n"
            "This content is only for users 18+.\n"
            "If you're under 18, you can request age verification by uploading a photo."
        ),
    },
    "age_under_18_deny": {
        "ru": (
            "🚫 <b>Доступ закрыт</b>\n\n"
            "К сожалению, вы не можете использовать 18+ контент.\n"
            "Вам должно быть минимум 18 лет."
        ),
        "uz": (
            "🚫 <b>Kirish mumkin emas</b>\n\n"
            "Afsuski, 18+ kontentdan foydalana olmaysiz.\n"
            "Sizda kamida 18 yosh bo'lishi kerak."
        ),
        "en": (
            "🚫 <b>Access Denied</b>\n\n"
            "Unfortunately, you cannot access 18+ content.\n"
            "You must be at least 18 years old."
        ),
    },
    "age_verification_sent": {
        "ru": (
            "✅ <b>Заявка отправлена!</b>\n\n"
            "Администратор рассмотрит ваш запрос.\n"
            "Пожалуйста, подождите ответа."
        ),
        "uz": (
            "✅ <b>So'rov yuborildi!</b>\n\n"
            "Administrator so'rovingizni ko'rib chiqadi.\n"
            "Iltimos, javobni kuting."
        ),
        "en": (
            "✅ <b>Request sent!</b>\n\n"
            "The administrator will review your request.\n"
            "Please wait for a response."
        ),
    },
    "age_verification_pending": {
        "ru": "⏳ <b>Ваш запрос на подтверждение возраста находится на рассмотрении</b>",
        "uz": "⏳ <b>Yoshingizni tasdiqlash so'rovingiz ko'rib chiqilmoqda</b>",
        "en": "⏳ <b>Your age verification request is being reviewed</b>",
    },
    "age_verification_approved": {
        "ru": (
            "✅ <b>Ваш возраст подтверждён!</b>\n"
            "Теперь у вас есть доступ к 18+ контенту."
        ),
        "uz": (
            "✅ <b>Yoshingiz tasdiqlandi!</b>\n"
            "Endi 18+ kontentdan foydalana olasiz."
        ),
        "en": (
            "✅ <b>Your age has been verified!</b>\n"
            "You now have access to 18+ content."
        ),
    },
    "age_verification_rejected": {
        "ru": (
            "❌ <b>Ваш запрос на подтверждение возраста отклонён</b>\n\n"
            "{reason}"
        ),
        "uz": (
            "❌ <b>Yoshingizni tasdiqlash so'rovi rad etildi</b>\n\n"
            "{reason}"
        ),
        "en": (
            "❌ <b>Your age verification request was rejected</b>\n\n"
            "{reason}"
        ),
    },
    "age_verify_already": {
        "ru": "Заявка уже обработана.",
        "uz": "Ariza allaqachon ko'rib chiqilgan.",
        "en": "The request has already been handled.",
    },
    "age_verify_approved_staff": {
        "ru": "✅ Возраст подтверждён, доступ к 18+ открыт.",
        "uz": "✅ Yosh tasdiqlandi, 18+ ochildi.",
        "en": "✅ Age verified, 18+ access granted.",
    },
    "age_verify_rejected_staff": {
        "ru": "❌ Заявка на 18+ отклонена.",
        "uz": "❌ 18+ arizasi rad etildi.",
        "en": "❌ 18+ request rejected.",
    },
    "age_18_plus_item": {
        "ru": "🔞 18+ товар",
        "uz": "🔞 18+ mahsulot",
        "en": "🔞 18+ item",
    },
    "18plus_purchase_coins": {
        "ru": "✅ <b>Покупка совершена!</b> Начислено <b>{amt}</b> 💎",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> <b>{amt}</b> 💎 qo'shildi",
        "en": "✅ <b>Purchase complete!</b> <b>{amt}</b> 💎 added",
    },
    "18plus_purchase_manual": {
        "ru": "✅ <b>Покупка совершена!</b> Админ свяжется с вами.",
        "uz": "✅ <b>Xarid amalga oshirildi!</b> Admin siz bilan bog'lanadi.",
        "en": "✅ <b>Purchase complete!</b> The admin will contact you.",
    },
    "18plus_admin_menu": {
        "ru": "🔞 <b>Админка: 18+ магазин</b>\n\nВыберите действие 👇",
        "uz": "🔞 <b>Admin: 18+ do'kon</b>\n\nAmalni tanlang 👇",
        "en": "🔞 <b>Admin: 18+ shop</b>\n\nChoose an action 👇",
    },
    "18plus_add_item": {
        "ru": "➕ Добавить товар 18+",
        "uz": "➕ 18+ mahsulot qo'shish",
        "en": "➕ Add 18+ item",
    },
    "18plus_list_items": {
        "ru": "📋 Список товаров 18+",
        "uz": "📋 18+ mahsulotlar ro'yxati",
        "en": "📋 18+ items list",
    },
    "18plus_item_added": {
        "ru": "✅ Товар добавлен!",
        "uz": "✅ Mahsulot qo'shildi!",
        "en": "✅ Item added!",
    },
    "18plus_item_deleted": {
        "ru": "✅ Товар удалён!",
        "uz": "✅ Mahsulot o'chirildi!",
        "en": "✅ Item deleted!",
    },
    "18plus_confirm_delete": {
        "ru": "Вы уверены, что хотите удалить товар «<b>{title}</b>»?",
        "uz": "«<b>{title}</b>» mahsulotini o'chirmoqchimisiz?",
        "en": "Are you sure you want to delete item «<b>{title}</b>»?",
    },
}
