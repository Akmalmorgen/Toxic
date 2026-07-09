"""Tests for pure utility functions in bot.py that require no DB or Telegram API."""
import os
import pytest

# conftest.py sets BOT_TOKEN/ADMIN_IDS/DB_PATH before this import
import bot


# ──────────────────────── has_forbidden_contacts ────────────────────────

class TestHasForbiddenContacts:
    def test_none_input(self):
        assert bot.has_forbidden_contacts(None) is False

    def test_empty_string(self):
        assert bot.has_forbidden_contacts("") is False

    def test_clean_text(self):
        assert bot.has_forbidden_contacts("привет, как дела?") is False

    def test_detects_username(self):
        assert bot.has_forbidden_contacts("напиши мне @username123") is True

    def test_ignores_short_at(self):
        # @ab is too short (min 3 chars after @)
        assert bot.has_forbidden_contacts("@ab") is False

    def test_detects_http_link(self):
        assert bot.has_forbidden_contacts("http://example.com") is True

    def test_detects_https_link(self):
        assert bot.has_forbidden_contacts("https://example.com") is True

    def test_detects_www(self):
        assert bot.has_forbidden_contacts("www.example.com") is True

    def test_detects_telegram_link(self):
        assert bot.has_forbidden_contacts("t.me/somechannel") is True

    def test_detects_telegram_me(self):
        assert bot.has_forbidden_contacts("telegram.me/chat") is True

    def test_detects_domain_com(self):
        assert bot.has_forbidden_contacts("mysite.com") is True

    def test_detects_domain_ru(self):
        assert bot.has_forbidden_contacts("сайт mysite.ru тут") is True

    def test_detects_domain_uz(self):
        assert bot.has_forbidden_contacts("shop.uz") is True

    def test_detects_instagram(self):
        assert bot.has_forbidden_contacts("пишите в instagram") is True

    def test_detects_tiktok(self):
        assert bot.has_forbidden_contacts("мой tiktok") is True

    def test_detects_whatsapp(self):
        assert bot.has_forbidden_contacts("whatsapp 123") is True

    def test_detects_russian_social(self):
        assert bot.has_forbidden_contacts("мой тикток") is True

    def test_detects_long_phone_number(self):
        assert bot.has_forbidden_contacts("+7 999 123 4567") is True

    def test_short_number_ok(self):
        # Less than 7 digits should be fine
        assert bot.has_forbidden_contacts("код 1234") is False

    def test_detects_discord(self):
        assert bot.has_forbidden_contacts("мой discord") is True

    def test_detects_youtube(self):
        assert bot.has_forbidden_contacts("мой youtube канал") is True

    def test_detects_joinchat(self):
        assert bot.has_forbidden_contacts("joinchat/abc123") is True

    def test_detects_tg_protocol(self):
        assert bot.has_forbidden_contacts("tg://resolve?domain=test") is True


# ──────────────────────── styled ────────────────────────

class TestStyled:
    def test_default_no_change(self):
        assert bot.styled("Hello") == "Hello"

    def test_default_explicit(self):
        assert bot.styled("Hello", "default") == "Hello"

    def test_premium(self):
        assert bot.styled("Hello", "premium") == "⟡ Hello ⟡"

    def test_accent(self):
        assert bot.styled("Hello", "accent") == "« Hello »"


# ──────────────────────── canon ────────────────────────

class TestCanon:
    def test_none_input(self):
        assert bot.canon(None) is None

    def test_known_russian_button(self):
        assert bot.canon("🔗 Моя ссылка") == "🔗 Моя ссылка"

    def test_known_english_button(self):
        assert bot.canon("🔗 My link") == "🔗 Моя ссылка"

    def test_known_uzbek_button(self):
        assert bot.canon("🔗 Havolam") == "🔗 Моя ссылка"

    def test_premium_styled_strips(self):
        assert bot.canon("⟡ 🔗 My link ⟡") == "🔗 Моя ссылка"

    def test_accent_styled_strips(self):
        assert bot.canon("« 🔗 My link »") == "🔗 Моя ссылка"

    def test_unknown_text_passthrough(self):
        assert bot.canon("some random text") == "some random text"


# ──────────────────────── progress_bar ────────────────────────

class TestProgressBar:
    def test_zero_target(self):
        assert bot.progress_bar(5, 0) == ""

    def test_negative_target(self):
        assert bot.progress_bar(5, -1) == ""

    def test_zero_progress(self):
        result = bot.progress_bar(0, 10)
        assert result == "▱" * 10

    def test_full_progress(self):
        result = bot.progress_bar(10, 10)
        assert result == "▰" * 10

    def test_half_progress(self):
        result = bot.progress_bar(5, 10)
        assert result == "▰" * 5 + "▱" * 5

    def test_over_target(self):
        result = bot.progress_bar(15, 10)
        # Should cap at 10 filled
        assert result == "▰" * 10

    def test_custom_slots(self):
        result = bot.progress_bar(3, 6, slots=6)
        assert result == "▰" * 3 + "▱" * 3


# ──────────────────────── _is_dead_account ────────────────────────

class TestIsDeadAccount:
    def test_blocked_error(self):
        assert bot._is_dead_account("bot was blocked by the user") is True

    def test_deactivated_error(self):
        assert bot._is_dead_account("user is deactivated") is True

    def test_chat_not_found(self):
        assert bot._is_dead_account("chat not found") is True

    def test_forbidden(self):
        assert bot._is_dead_account("Forbidden: user blocked") is True

    def test_peer_id_invalid(self):
        assert bot._is_dead_account("PEER_ID_INVALID") is True

    def test_unrelated_error(self):
        assert bot._is_dead_account("network timeout") is False

    def test_empty_string(self):
        assert bot._is_dead_account("") is False


# ──────────────────────── is_admin ────────────────────────

class TestIsAdmin:
    def test_admin_id(self):
        assert bot.is_admin(111) is True
        assert bot.is_admin(222) is True

    def test_non_admin_id(self):
        assert bot.is_admin(999) is False


# ──────────────────────── is_banned ────────────────────────

class TestIsBanned:
    def test_none_row(self):
        assert bot.is_banned(None) is False

    def test_not_banned(self):
        assert bot.is_banned({"is_banned": 0}) is False

    def test_banned(self):
        assert bot.is_banned({"is_banned": 1}) is True

    def test_banned_truthy(self):
        assert bot.is_banned({"is_banned": True}) is True


# ──────────────────────── user_age_int ────────────────────────

class TestUserAgeInt:
    def test_none_row(self):
        assert bot.user_age_int(None) is None

    def test_no_age_key(self):
        assert bot.user_age_int({}) is None

    def test_age_none(self):
        assert bot.user_age_int({"age": None}) is None

    def test_age_integer(self):
        assert bot.user_age_int({"age": 25}) == 25

    def test_age_string(self):
        assert bot.user_age_int({"age": "25"}) == 25

    def test_age_non_numeric(self):
        assert bot.user_age_int({"age": "abc"}) is None

    def test_age_string_with_spaces(self):
        assert bot.user_age_int({"age": " 18 "}) == 18


# ──────────────────────── is_adult ────────────────────────

class TestIsAdult:
    def test_adult(self):
        assert bot.is_adult({"age": 18}) is True

    def test_minor(self):
        assert bot.is_adult({"age": 17}) is False

    def test_no_age(self):
        assert bot.is_adult({"age": None}) is False

    def test_edge_case_18(self):
        assert bot.is_adult({"age": "18"}) is True


# ──────────────────────── user_mention ────────────────────────

class TestUserMention:
    def test_none_row(self):
        assert bot.user_mention(None) == "—"

    def test_with_username(self):
        row = {"first_name": "John", "username": "john123", "tg_id": 100}
        result = bot.user_mention(row)
        assert "John" in result
        assert "@john123" in result

    def test_without_username(self):
        row = {"first_name": "John", "username": None, "tg_id": 100}
        result = bot.user_mention(row)
        assert "tg://user?id=100" in result
        assert "John" in result

    def test_no_first_name(self):
        row = {"first_name": None, "username": None, "tg_id": 100}
        result = bot.user_mention(row)
        assert "пользователь" in result

    def test_html_escape(self):
        row = {"first_name": "<b>Bold</b>", "username": None, "tg_id": 100}
        result = bot.user_mention(row)
        assert "&lt;b&gt;" in result


# ──────────────────────── effective_price ────────────────────────

class TestEffectivePrice:
    def test_non_vip_full_price(self):
        row = {"tg_id": 999, "vip_until": None, "is_moder": 0}
        assert bot.effective_price(100, row) == 100

    def test_vip_discount(self):
        # VIP_DISCOUNT_PERCENT = 20, so price = 80% of 100 = 80
        # Admin is always VIP
        row = {"tg_id": 111, "vip_until": None, "is_moder": 0}
        assert bot.effective_price(100, row) == 80

    def test_zero_price(self):
        row = {"tg_id": 999, "vip_until": None, "is_moder": 0}
        assert bot.effective_price(0, row) == 0


# ──────────────────────── is_unlimited ────────────────────────

class TestIsUnlimited:
    def test_none_row(self):
        assert bot.is_unlimited(None) is False

    def test_admin(self):
        assert bot.is_unlimited({"tg_id": 111}) is True

    def test_moder(self):
        assert bot.is_unlimited({"tg_id": 999, "is_moder": 1, "moder_until": None}) is True

    def test_regular_user(self):
        assert bot.is_unlimited({"tg_id": 999, "is_moder": 0, "moder_until": None}) is False


# ──────────────────────── is_moder ────────────────────────

class TestIsModer:
    def test_none_row(self):
        assert bot.is_moder(None) is False

    def test_permanent_moder(self):
        assert bot.is_moder({"is_moder": 1, "moder_until": None}) is True

    def test_not_moder(self):
        assert bot.is_moder({"is_moder": 0, "moder_until": None}) is False

    def test_temp_moder_active(self):
        from datetime import datetime, timedelta
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        assert bot.is_moder({"is_moder": 0, "moder_until": future}) is True

    def test_temp_moder_expired(self):
        from datetime import datetime, timedelta
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        assert bot.is_moder({"is_moder": 0, "moder_until": past}) is False


# ──────────────────────── is_vip ────────────────────────

class TestIsVip:
    def test_none_row(self):
        assert bot.is_vip(None) is False

    def test_admin_always_vip(self):
        row = {"tg_id": 111, "vip_until": None, "is_moder": 0, "moder_until": None}
        assert bot.is_vip(row) is True

    def test_active_vip(self):
        from datetime import datetime, timedelta
        future = (datetime.utcnow() + timedelta(days=7)).isoformat()
        row = {"tg_id": 999, "vip_until": future, "is_moder": 0, "moder_until": None}
        assert bot.is_vip(row) is True

    def test_expired_vip(self):
        from datetime import datetime, timedelta
        past = (datetime.utcnow() - timedelta(days=7)).isoformat()
        row = {"tg_id": 999, "vip_until": past, "is_moder": 0, "moder_until": None}
        assert bot.is_vip(row) is False

    def test_no_vip(self):
        row = {"tg_id": 999, "vip_until": None, "is_moder": 0, "moder_until": None}
        assert bot.is_vip(row) is False

    def test_moder_always_vip(self):
        row = {"tg_id": 999, "vip_until": None, "is_moder": 1, "moder_until": None}
        assert bot.is_vip(row) is True


# ──────────────────────── is_eighteenplus_active ────────────────────────

class TestIsEighteenplusActive:
    def test_none_row(self):
        assert bot.is_eighteenplus_active(None) is False

    def test_admin(self):
        row = {"tg_id": 111, "is_moder": 0, "moder_until": None, "eighteenplus_until": None}
        assert bot.is_eighteenplus_active(row) is True

    def test_active_access(self):
        from datetime import datetime, timedelta
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        row = {"tg_id": 999, "is_moder": 0, "moder_until": None, "eighteenplus_until": future}
        assert bot.is_eighteenplus_active(row) is True

    def test_expired_access(self):
        from datetime import datetime, timedelta
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        row = {"tg_id": 999, "is_moder": 0, "moder_until": None, "eighteenplus_until": past}
        assert bot.is_eighteenplus_active(row) is False

    def test_no_access(self):
        row = {"tg_id": 999, "is_moder": 0, "moder_until": None, "eighteenplus_until": None}
        assert bot.is_eighteenplus_active(row) is False
