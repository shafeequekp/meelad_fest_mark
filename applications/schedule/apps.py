from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'applications.schedule'
    verbose_name = 'Program Scheduling'

    def ready(self):
        from . import signals  # noqa: F401