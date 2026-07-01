"""Tests for database-dependent functions (settings, user CRUD, purge, etc.)."""
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import bot


@pytest.fixture(autouse=True)
def fresh_db():
    """Replace the global conn with a fresh in-memory SQLite DB for each test."""
    old_conn = bot.conn
    new_conn = sqlite3.connect(":memory:", check_same_thread=False)
    new_conn.row_factory = sqlite3.Row
    bot.conn = new_conn
    bot.init_db()
    yield new_conn
    new_conn.close()
    bot.conn = old_conn


# ──────────────────────── settings ────────────────────────

class TestSettings:
    def test_get_setting_missing(self):
        assert bot.get_setting("nonexistent") is None

    def test_get_setting_default(self):
        assert bot.get_setting("nonexistent", "fallback") == "fallback"

    def test_set_and_get_setting(self):
        bot.set_setting("foo", "bar")
        assert bot.get_setting("foo") == "bar"

    def test_set_setting_overwrites(self):
        bot.set_setting("foo", "bar")
        bot.set_setting("foo", "baz")
        assert bot.get_setting("foo") == "baz"

    def test_get_setting_int(self):
        bot.set_setting("num", "42")
        assert bot.get_setting_int("num", 0) == 42

    def test_get_setting_int_non_numeric(self):
        bot.set_setting("num", "abc")
        assert bot.get_setting_int("num", 99) == 99

    def test_get_setting_int_missing(self):
        assert bot.get_setting_int("missing_key", 7) == 7


# ──────────────────────── ensure_user / get_user ────────────────────────

class TestEnsureUser:
    def test_creates_new_user(self):
        u = bot.ensure_user(1001, "alice", "Alice")
        assert u is not None
        assert u["tg_id"] == 1001
        assert u["username"] == "alice"
        assert u["first_name"] == "Alice"
        assert u["coins"] == 0

    def test_returns_existing_user(self):
        bot.ensure_user(1001, "alice", "Alice")
        u = bot.ensure_user(1001, "alice", "Alice")
        assert u["tg_id"] == 1001

    def test_updates_username(self):
        bot.ensure_user(1001, "alice", "Alice")
        u = bot.ensure_user(1001, "alice2", "Alice")
        assert u["username"] == "alice2"

    def test_updates_first_name(self):
        bot.ensure_user(1001, "alice", "Alice")
        u = bot.ensure_user(1001, "alice", "Alicia")
        assert u["first_name"] == "Alicia"

    def test_get_user_not_found(self):
        assert bot.get_user(9999) is None


# ──────────────────────── resolve_user_ref ────────────────────────

class TestResolveUserRef:
    def test_none_input(self):
        assert bot.resolve_user_ref(None) is None

    def test_empty_string(self):
        assert bot.resolve_user_ref("") is None

    def test_by_numeric_id(self):
        bot.ensure_user(1001, "alice", "Alice")
        assert bot.resolve_user_ref("1001") == 1001

    def test_by_numeric_id_not_found(self):
        assert bot.resolve_user_ref("9999") is None

    def test_by_username(self):
        bot.ensure_user(1001, "alice", "Alice")
        assert bot.resolve_user_ref("@alice") == 1001

    def test_by_username_case_insensitive(self):
        bot.ensure_user(1001, "Alice", "Alice")
        assert bot.resolve_user_ref("@alice") == 1001

    def test_by_username_without_at(self):
        bot.ensure_user(1001, "alice", "Alice")
        # lstrip("@") still works without @, so "alice" resolves too
        assert bot.resolve_user_ref("alice") == 1001

    def test_empty_at(self):
        assert bot.resolve_user_ref("@") is None


# ──────────────────────── purge_user ────────────────────────

class TestPurgeUser:
    def test_purge_regular_user(self):
        bot.ensure_user(1001, "alice", "Alice")
        result = bot.purge_user(1001)
        assert result is True
        assert bot.get_user(1001) is None

    def test_purge_admin_blocked(self):
        bot.ensure_user(111, "admin", "Admin")
        result = bot.purge_user(111)
        assert result is False
        assert bot.get_user(111) is not None

    def test_purge_moder_blocked(self):
        bot.ensure_user(1001, "mod", "Mod")
        bot.conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=1001")
        bot.conn.commit()
        result = bot.purge_user(1001)
        assert result is False

    def test_purge_cleans_referrals(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.ensure_user(1002, "bob", "Bob")
        bot.conn.execute(
            "INSERT INTO referrals (referrer_id, referred_id, coins_awarded, created_at) VALUES (1002, 1001, 50, ?)",
            (bot.now_iso(),),
        )
        bot.conn.commit()
        bot.purge_user(1001)
        refs = bot.conn.execute("SELECT * FROM referrals WHERE referred_id=1001").fetchall()
        assert len(refs) == 0

    def test_purge_cleans_link_flow(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.conn.execute(
            "INSERT INTO link_flow (user_id, target_id, state, updated_at) VALUES (1001, 1002, 'type', ?)",
            (bot.now_iso(),),
        )
        bot.conn.commit()
        bot.purge_user(1001)
        flows = bot.conn.execute("SELECT * FROM link_flow WHERE user_id=1001").fetchall()
        assert len(flows) == 0

    def test_purge_ends_active_sessions(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.conn.execute(
            "INSERT INTO roulette_sessions (user1_id, user2_id, active, started_at) VALUES (1001, 1002, 1, ?)",
            (bot.now_iso(),),
        )
        bot.conn.commit()
        bot.purge_user(1001)
        sessions = bot.conn.execute(
            "SELECT * FROM roulette_sessions WHERE active=1 AND (user1_id=1001 OR user2_id=1001)"
        ).fetchall()
        assert len(sessions) == 0


# ──────────────────────── user_is_disposable ────────────────────────

class TestUserIsDisposable:
    def test_admin_not_disposable(self):
        bot.ensure_user(111, "admin", "Admin")
        assert bot.user_is_disposable(111) is False

    def test_moder_not_disposable(self):
        bot.ensure_user(1001, "mod", "Mod")
        bot.conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=1001")
        bot.conn.commit()
        assert bot.user_is_disposable(1001) is False

    def test_vip_not_disposable(self):
        bot.ensure_user(1001, "vip", "Vip")
        future = (datetime.utcnow() + timedelta(days=7)).isoformat()
        bot.conn.execute("UPDATE users SET vip_until=? WHERE tg_id=1001", (future,))
        bot.conn.commit()
        assert bot.user_is_disposable(1001) is False

    def test_coins_not_disposable(self):
        bot.ensure_user(1001, "rich", "Rich")
        bot.conn.execute("UPDATE users SET coins=100 WHERE tg_id=1001")
        bot.conn.commit()
        assert bot.user_is_disposable(1001) is False

    def test_star_purchase_not_disposable(self):
        bot.ensure_user(1001, "star", "Star")
        bot.conn.execute(
            "INSERT INTO star_purchases (user_id, coins, stars, created_at) VALUES (1001, 100, 10, ?)",
            (bot.now_iso(),),
        )
        bot.conn.commit()
        assert bot.user_is_disposable(1001) is False

    def test_empty_user_is_disposable(self):
        bot.ensure_user(1001, "empty", "Empty")
        assert bot.user_is_disposable(1001) is True

    def test_nonexistent_user(self):
        assert bot.user_is_disposable(9999) is False


# ──────────────────────── safe_purge_dead ────────────────────────

class TestSafePurgeDead:
    def test_purges_disposable(self):
        bot.ensure_user(1001, "empty", "Empty")
        assert bot.safe_purge_dead(1001) is True
        assert bot.get_user(1001) is None

    def test_keeps_non_disposable(self):
        bot.ensure_user(1001, "rich", "Rich")
        bot.conn.execute("UPDATE users SET coins=100 WHERE tg_id=1001")
        bot.conn.commit()
        assert bot.safe_purge_dead(1001) is False
        assert bot.get_user(1001) is not None


# ──────────────────────── grant_18plus_access ────────────────────────

class TestGrant18PlusAccess:
    def test_grants_access(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.grant_18plus_access(1001, 30)
        u = bot.get_user(1001)
        until = datetime.fromisoformat(u["eighteenplus_until"])
        # Should be roughly 30 days from now
        assert until > datetime.utcnow() + timedelta(days=29)
        assert until < datetime.utcnow() + timedelta(days=31)

    def test_extends_existing_access(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.grant_18plus_access(1001, 10)
        bot.grant_18plus_access(1001, 10)
        u = bot.get_user(1001)
        until = datetime.fromisoformat(u["eighteenplus_until"])
        # Should be roughly 20 days from now (10+10)
        assert until > datetime.utcnow() + timedelta(days=19)

    def test_grants_forever_with_zero(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.grant_18plus_access(1001, 0)
        u = bot.get_user(1001)
        assert u["eighteenplus_until"] == "9999-12-31T23:59:59"


# ──────────────────────── touch_user ────────────────────────

class TestTouchUser:
    def test_touch_sets_last_active(self):
        bot.ensure_user(1001, "alice", "Alice")
        bot.touch_user(1001)
        u = bot.get_user(1001)
        assert u["last_active"] is not None

    def test_touch_nonexistent_user(self):
        # Should not raise
        bot.touch_user(9999)

    def test_touch_throttled(self):
        """Second touch within an hour should not update last_active."""
        bot.ensure_user(1001, "alice", "Alice")
        bot.touch_user(1001)
        u1 = bot.get_user(1001)
        ts1 = u1["last_active"]
        bot.touch_user(1001)
        u2 = bot.get_user(1001)
        assert u2["last_active"] == ts1  # unchanged


# ──────────────────────── init_db / migrate / ensure_indexes ────────────────────────

class TestInitDb:
    def test_all_tables_created(self):
        tables = bot.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        expected = {
            "users", "anon_messages", "reports", "bans",
            "roulette_queue", "roulette_sessions", "shop_items",
            "purchases", "mandatory_channels", "ad_config",
            "moder_apps", "star_packages", "star_purchases",
            "referrals", "link_flow", "eighteen_plus_items",
            "age_verification_requests", "settings",
        }
        assert expected.issubset(table_names)

    def test_indexes_created(self):
        indexes = bot.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        assert len(indexes) >= 10  # We expect many indexes


# ──────────────────────── has_admin_access ────────────────────────

class TestHasAdminAccess:
    def test_admin_always_has_access(self):
        bot.ensure_user(111, "admin", "Admin")
        assert bot.has_admin_access(111) is True

    def test_moder_without_key(self):
        bot.ensure_user(1001, "mod", "Mod")
        bot.conn.execute("UPDATE users SET is_moder=1 WHERE tg_id=1001")
        bot.conn.commit()
        assert bot.has_admin_access(1001) is False

    def test_moder_with_key(self):
        bot.ensure_user(1001, "mod", "Mod")
        bot.conn.execute("UPDATE users SET is_moder=1, admin_unlocked=1 WHERE tg_id=1001")
        bot.conn.commit()
        assert bot.has_admin_access(1001) is True

    def test_regular_user(self):
        bot.ensure_user(1001, "user", "User")
        assert bot.has_admin_access(1001) is False
