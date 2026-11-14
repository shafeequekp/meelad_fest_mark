# Temporary settings override used only to run the test-suite without a MySQL
# server. The base settings module unconditionally imports .local which forces
# MySQL; this module re-overrides the DB to a throw-away SQLite database.
from .settings import *  # noqa

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Keep the test-suite offline and deterministic: use the local filesystem for
# media instead of Cloudinary (which is configured as the default in settings).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
