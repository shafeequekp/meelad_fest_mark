# Temporary settings override for LIVE end-to-end checks against a scratch
# copy of the real database (db.test.sqlite3) — same idea as test_settings.py
# but file-backed so separate manage.py invocations share the data.
from .settings import *  # noqa

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.test.sqlite3",
    }
}
