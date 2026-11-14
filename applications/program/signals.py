from django.db.models.signals import post_save
from django.dispatch import receiver

from applications.program.models import Program
from applications.scoreboard.models import Team


@receiver(post_save, sender=Team)
def sync_new_team_to_general_programs(sender, instance, created, **kwargs):
    """When a new team is created for a madrasa, automatically add it as a
    participating team in *all* of that madrasa's existing general programs.

    General programs are team-wise: every team of the madrasa participates in the
    program by default, so a team created later in the flow must also appear in
    the already-created general programs. Without this auto-sync, a team created
    after the program would be missing from it.
    """
    if not created:
        return
    madrasa = instance.madrasa
    if madrasa is None:
        return
    programs = Program.objects.filter(is_general=True, madrasa=madrasa)
    for program in programs:
        program.general_teams.add(instance)