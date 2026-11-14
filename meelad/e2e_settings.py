# Scratch settings for local test/E2E runs (gitignored, not for commit).
# Mirrors meelad.settings but swaps the DB for a throwaway SQLite file so the
# MySQL user doesn't need CREATE DATABASE privileges.
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "/tmp/meelad_e2e.sqlite3",
    }
}

# Speed up the suite; irrelevant to behaviour under test.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
