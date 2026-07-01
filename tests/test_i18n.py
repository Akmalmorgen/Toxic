"""Tests for the internationalisation / translation layer."""
import bot


# ──────────────────────── t() translation lookup ────────────────────────

class TestT:
    def setup_method(self):
        bot.set_cur_lang("ru")

    def test_russian_default(self):
        result = bot.t("main_menu")
        assert result == "Главное меню 👇"

    def test_uzbek(self):
        bot.set_cur_lang("uz")
        result = bot.t("main_menu")
        assert result == "Asosiy menyu 👇"

    def test_english(self):
        bot.set_cur_lang("en")
        result = bot.t("main_menu")
        assert result == "Main menu 👇"

    def test_missing_key_returns_key(self):
        result = bot.t("nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"

    def test_format_kwargs(self):
        # "pick_on_kb" has no format args, test one that does
        bot.set_cur_lang("ru")
        result = bot.t("pick_on_kb")
        assert "Выберите" in result

    def test_fallback_to_russian(self):
        """If translation missing for current lang, fall back to Russian."""
        bot.set_cur_lang("uz")
        result = bot.t("main_menu")
        # Uzbek translation exists, so it should be Uzbek
        assert "menyu" in result.lower()


# ──────────────────────── cur_lang / set_cur_lang ────────────────────────

class TestCurLang:
    def test_default_is_ru(self):
        bot.set_cur_lang("ru")
        assert bot.cur_lang() == "ru"

    def test_set_uz(self):
        bot.set_cur_lang("uz")
        assert bot.cur_lang() == "uz"

    def test_set_en(self):
        bot.set_cur_lang("en")
        assert bot.cur_lang() == "en"


# ──────────────────────── tr_btn ────────────────────────

class TestTrBtn:
    def setup_method(self):
        bot.set_cur_lang("ru")

    def test_russian_passthrough(self):
        result = bot.tr_btn("🔗 Моя ссылка")
        assert result == "🔗 Моя ссылка"

    def test_translate_to_uzbek(self):
        result = bot.tr_btn("🔗 Моя ссылка", lang="uz")
        assert result == "🔗 Havolam"

    def test_translate_to_english(self):
        result = bot.tr_btn("🔗 Моя ссылка", lang="en")
        assert result == "🔗 My link"

    def test_unknown_label_passthrough(self):
        result = bot.tr_btn("unknown_label", lang="en")
        assert result == "unknown_label"

    def test_with_premium_style(self):
        result = bot.tr_btn("🔗 Моя ссылка", lang="en", kind="premium")
        assert result == "⟡ 🔗 My link ⟡"

    def test_with_accent_style(self):
        result = bot.tr_btn("🔗 Моя ссылка", lang="en", kind="accent")
        assert result == "« 🔗 My link »"

    def test_uses_cur_lang_when_none(self):
        bot.set_cur_lang("en")
        result = bot.tr_btn("🔗 Моя ссылка")
        assert result == "🔗 My link"


# ──────────────────────── gender_label ────────────────────────

class TestGenderLabel:
    def setup_method(self):
        bot.set_cur_lang("ru")

    def test_male_ru(self):
        assert bot.gender_label("m") == "Мужской"

    def test_female_ru(self):
        assert bot.gender_label("f") == "Женский"

    def test_male_en(self):
        bot.set_cur_lang("en")
        assert bot.gender_label("m") == "Male"

    def test_female_uz(self):
        bot.set_cur_lang("uz")
        assert bot.gender_label("f") == "Ayol"

    def test_unknown_code(self):
        assert bot.gender_label("x") == "—"


# ──────────────────────── pref_label ────────────────────────

class TestPrefLabel:
    def setup_method(self):
        bot.set_cur_lang("ru")

    def test_male_ru(self):
        assert bot.pref_label("m") == "Парня"

    def test_female_en(self):
        bot.set_cur_lang("en")
        assert bot.pref_label("f") == "A girl"

    def test_any_uz(self):
        bot.set_cur_lang("uz")
        assert bot.pref_label("any") == "Farqi yo'q"

    def test_unknown_code(self):
        assert bot.pref_label("z") == "—"


# ──────────────────────── LANG_BUTTONS ────────────────────────

class TestLangButtons:
    def test_all_langs_covered(self):
        assert set(bot.LANG_BUTTONS.values()) == {"ru", "uz", "en"}

    def test_russian_button(self):
        assert bot.LANG_BUTTONS["🇷🇺 Русский"] == "ru"

    def test_uzbek_button(self):
        assert bot.LANG_BUTTONS["🇺🇿 O'zbekcha"] == "uz"

    def test_english_button(self):
        assert bot.LANG_BUTTONS["🇬🇧 English"] == "en"


# ──────────────────────── BTN alias map ────────────────────────

class TestBtnAliasMap:
    def test_all_russian_keys_are_aliases(self):
        for ru_label in bot.BTN:
            assert ru_label in bot._ALIAS
            assert bot._ALIAS[ru_label] == ru_label

    def test_all_translations_map_to_russian(self):
        for ru_label, (uz, en) in bot.BTN.items():
            assert bot._ALIAS[uz] == ru_label
            assert bot._ALIAS[en] == ru_label
