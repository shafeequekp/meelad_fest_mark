from django.contrib import admin

from .models import FestDay, ScheduleEntry


@admin.register(FestDay)
class FestDayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'madrasa', 'is_active')
    list_filter = ('madrasa', 'is_active')
    search_fields = ('name', 'madrasa__name')


@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = ('program', 'fest_day', 'start_time', 'duration_minutes', 'venue')
    list_filter = ('fest_day', 'venue')
    search_fields = ('program__title', 'fest_day__name')