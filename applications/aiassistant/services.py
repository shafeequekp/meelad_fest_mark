"""Deterministic business services used by the AI assistant.

The AI layer (FastAPI) must never decide whether these work conflicts, or
whether a venue is available, or how scoring/rankings work. Those are
deterministic Python rules that live here in Django and are exposed through
the AI API.

All helpers here are read/compute only: they never mutate application data and
they never re-implement official scoring (team rankings delegate to
``Prize.get_team_leaderboard``).
"""
from datetime import datetime

from applications.accounts.models import Madrasa
from applications.program.models import Program, Venue, program_section_q


def fest_type_for(madrasa):
    """Fest structure of the madrasa ('both' / 'boys' / 'girls')."""
    return getattr(madrasa, "fest_type", None) or Madrasa.FEST_TYPE_BOTH


def active_sections_for(madrasa):
    """Section ids ('boys'/'girls') active for the madrasa's fest structure."""
    return madrasa.active_fest_sections


def programs_for_madrasa(madrasa):
    """Programs scoped to the given madrasa across all program types.

    Respects the fest structure: in a boys-only (or girls-only) fest,
    programs that belong to the other section are hidden from the AI.
    """
    return (
        Program.objects
        .filter(program_section_q(madrasa, fest_type_for(madrasa)))
        .distinct()
    )


def check_schedule_conflict(program, venue, scheduled_time, madrasa):
    """Return a list of conflict descriptions for a proposed schedule.

    Deterministic: returns [] when the slot is conflict-free. Two programs may
    not share the same venue on the same day.
    """
    conflicts = []
    if venue is None:
        conflicts.append("A venue must be selected.")
    if scheduled_time is None:
        conflicts.append("A scheduled time must be provided.")
    if conflicts:
        return conflicts

    overlapping = (
        programs_for_madrasa(madrasa)
        .filter(
            venue=venue,
            scheduled_time__isnull=False,
            scheduled_time__date=scheduled_time.date(),
        )
        .exclude(id=program.id)
    )
    for other in overlapping:
        conflicts.append(
            f"{other.title} is already scheduled at {venue.name} on "
            f"{scheduled_time.strftime('%Y-%m-%d %H:%M')}."
        )
    return conflicts


def get_recents_schedule(madrasa):
    """Return scheduled programs for a madrasa, most recent first."""
    return (
        programs_for_madrasa(madrasa)
        .filter(scheduled_time__isnull=False)
        .select_related("venue")
        .order_by("-scheduled_time")
    )


def get_unscheduled_programs(madrasa):
    """Programs with no venue/time assigned yet."""
    return programs_for_madrasa(madrasa).filter(scheduled_time__isnull=True)


def get_venue_schedules(madrasa, venue=None):
    """Programs scheduled at a venue (or any venue) for the madrasa."""
    qs = (
        get_recents_schedule(madrasa)
        .filter(venue__isnull=False)
        .select_related("venue")
        .order_by("scheduled_time")
    )
    if venue:
        qs = qs.filter(venue=venue)
    return qs


def find_available_venues(madrasa, at_time=None):
    """Venues owned by ``madrasa`` that are free at ``at_time`` (or all of them when no time given)."""
    venues = list(Venue.objects.filter(madrasa=madrasa).order_by("name"))
    if at_time is None:
        return venues
    busy_ids = set(
        get_recents_schedule(madrasa)
        .filter(scheduled_time__date=at_time.date(), venue__isnull=False)
        .values_list("venue_id", flat=True)
    )
    return [v for v in venues if v.id not in busy_ids]


def suggest_conflict_free_schedule(madrasa, target_date, venues, slots, window_minutes=60):
    """Build a conflict-free proposed schedule for unscheduled programs.

    ``slots`` is a sorted set of ``datetime.time`` candidates. The rule enforced
    here matches ``check_schedule_conflict`` exactly: a venue hosts at most one
    program per day, so proposals created here are guaranteed to pass the write
    path's re-validation. ``window_minutes`` is kept for API compatibility.
    """
    slots = sorted(slots)
    # Venues already booked on the target date are unavailable.
    used_venue_ids = set(
        get_recents_schedule(madrasa)
        .filter(scheduled_time__date=target_date, venue__isnull=False)
        .values_list("venue_id", flat=True)
    )
    proposals = []
    for program in get_unscheduled_programs(madrasa):
        for venue in venues:
            if venue.id in used_venue_ids or not slots:
                continue
            slot = slots[0]
            slots = slots[1:]
            used_venue_ids.add(venue.id)
            start = datetime.combine(target_date, slot)
            proposals.append({
                "program_id": program.id,
                "title": program.title,
                "venue_id": venue.id,
                "venue": venue.name,
                "start": start.isoformat(),
            })
            break
    return proposals