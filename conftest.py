"""Root conftest: set env vars BEFORE importing bot so module-level init succeeds."""
import os

os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ.setdefault("ADMIN_IDS", "111,222")
os.environ.setdefault("DB_PATH", ":memory:")
