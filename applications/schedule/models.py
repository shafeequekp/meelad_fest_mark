from django.db import models

from utils.db import DateBaseModel
from applications.accounts.models import Madrasa
from applications.program.models import Program, Venue


class FestDay(DateBaseModel):
    """A single day of the fest used as the scheduling unit.

    Every fest day belongs to one madrasa so day lists are scoped per
    account and other madrasas' days never leak.
    """

    madrasa = models.ForeignKey(
        Madrasa, on_delete=models.CASCADE, related_name='fest_days'
    )
    name = models.CharField(max_length=120, help_text="e.g. Day 1, Opening Day")
    date = models.DateField()
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive days are hidden from the schedule board.",
    )

    class Meta:
        ordering = ['date', 'id']
        unique_together = (('madrasa', 'date'),)
        verbose_name = 'Fest Day'
        verbose_name_plural = 'Fest Days'

    def __str__(self):
        return f'{self.name} — {self.date}'


class ScheduleEntry(DateBaseModel):
    """Where and when one program takes place on a fest day.

    Kept separate from ``Program.scheduled_time`` / ``Program.venue`` so the
    existing program flows are never disturbed: the board coordinates days,
    durations and venues here, and a small sync helper mirrors the resolved
    datetime + venue back onto the program so legacy views (venue PDF etc.)
    stay consistent.
    """

    program = models.OneToOneField(
        Program, on_delete=models.CASCADE, related_name='schedule_entry'
    )
    fest_day = models.ForeignKey(
        FestDay, on_delete=models.CASCADE, related_name='schedule_entries'
    )
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    venue = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedule_entries',
    )
    notes = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ['start_time', 'id']
        verbose_name = 'Schedule Entry'
        verbose_name_plural = 'Schedule Entries'

    def __str__(self):
        return f'{self.program.title} @ {self.start_time}'