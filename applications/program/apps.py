from django.apps import AppConfig


class ProgramConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'applications.program'

    def ready(self):
        # Ensure auto-sync of newly created teams into general programs is wired.
        from . import signals  # noqa: F401
