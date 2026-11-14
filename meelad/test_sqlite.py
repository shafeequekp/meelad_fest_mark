"""Test-only settings: identical to meelad.settings but running on SQLite.

The developer MySQL user (meelad/local.py) may lack CREATE DATABASE rights
for `test_meelad_db`, which makes Django's test-DB bootstrap fail (error
1044). Pointing the test runner at SQLite removes that dependency entirely:

    MEELAD_ENV= .venv/bin/python manage.py test --settings=meelad.test_sqlite
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.test.sqlite3",
    }
}

# Never call the real Cloudinary API from tests: uploads then depend on an
# external service (and flake when it hiccups / rate-limits). Use local files.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

