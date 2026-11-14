from django.db.models.signals import pre_delete
from django.dispatch import receiver

from applications.program.models import Program

from .models import FestDay, ScheduleEntry


@receiver(pre_delete, sender=FestDay)
def revert_programs_when_fest_day_deleted(sender, instance, **kwargs):
    """Clear the mirrored ``Program.scheduled_time`` / ``Program.venue`` when a
    fest day is removed through *any* path (the board view, Django admin or a
    bare ORM delete).

    The schedule board treats ``ScheduleEntry`` as the source of truth, but the
    legacy program views (venue PDF, program cards) still read the mirrored
    fields on ``Program``. Without this hook those mirrors would keep a stale
    datetime even after the day (and therefore its entries) were deleted.
    """
    program_ids = list(
        instance.schedule_entries.values_list('program_id', flat=True)
    )
    if program_ids:
        Program.objects.filter(pk__in=program_ids).update(
            scheduled_time=None, venue=None
        )


@receiver(pre_delete, sender=ScheduleEntry)
def revert_program_when_entry_deleted(sender, instance, **kwargs):
    """Same guarantee for removing a single schedule entry directly (admin/ORM
    path), not just through the board's ``delete_schedule`` view."""
    Program.objects.filter(pk=instance.program_id).update(
        scheduled_time=None, venue=None
    )