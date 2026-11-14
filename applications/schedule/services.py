"""Conflict detection for the fest schedule board.

The scheduling model is simple: each ``ScheduleEntry`` pins one program to a
fest day / start time / duration / (optional) venue.  A conflict happens when
two entries overlap in time and one of them needs:

* the **same participant** in both slots (a student enrolled in two
  individual/group programs at the same time, or the same team in two general
  programs at the same time) — ``kind="participant"``
* the **same venue** at the same time — ``kind="venue"``

Everything here is pure/deterministic (no DB writes) so it is used both by the
board while rendering the current schedule and by the AJAX endpoint that gives
live feedback before the coordinator saves a new/edited slot.
"""

from datetime import datetime, timedelta


def program_units(program):
    """Return the set of participant units of a program.

    A unit is a (kind, pk, label) tuple:

    - individual / group programs participate per **student**
      (``Program.participants``)
    - group / general programs additionally compete per **team**
      (``Program.general_teams``)

    Two schedules conflict when their unit sets intersect and their time
    windows overlap on the same day.
    """

    units = set()
    if not program.is_general:
        for student in program.participants.all():
            units.add(('student', student.pk, student.full_name))
    if program.is_general or program.is_group:
        for team in program.general_teams.all():
            units.add(('team', team.pk, team.name))
    return units


def schedule_time_range(entry):
    """Return (start_datetime, end_datetime) for a schedule entry on its day."""
    start = datetime.combine(entry.fest_day.date, entry.start_time)
    end = start + timedelta(minutes=entry.duration_minutes or 0)
    return start, end


def interval_overlaps(start_a, duration_a, start_b, duration_b):
    """True when two time ranges [start, start+duration) overlap."""
    end_a = start_a + timedelta(minutes=duration_a or 0)
    end_b = start_b + timedelta(minutes=duration_b or 0)
    return start_a < end_b and start_b < end_a


def check_schedule_conflicts(program, fest_day, start_time, duration_minutes,
                             venue=None, exclude_pk=None):
    """Return a list of conflict dicts for a *proposed* schedule slot.



    ``exclude_pk`` can be a schedule PK to ignore while validating an edit
    (the entry being edited is not its own conflict).
    """
    conflicts = []
    candidate_units = program_units(program)
    candidate_start = datetime.combine(fest_day.date, start_time)
    candidate_end = candidate_start + timedelta(minutes=duration_minutes or 0)

    qs = (
        fest_day.schedule_entries
        .exclude(pk=exclude_pk)
        .exclude(program=program)
        .select_related('program', 'venue')
    )
    for entry in qs:
        entry_start, entry_end = schedule_time_range(entry)
        if not (candidate_start < entry_end and entry_start < candidate_end):
            continue

        # 1) Participant double-booking — the core conflict the coordinator
        #    must resolve (same student / same team in two things at once).
        shared_units = candidate_units & program_units(entry.program)
        if shared_units:
            conflicts.append({
                'kind': 'participant',
                'entry': entry,
                'shared': sorted(
                    {label for _, _, label in shared_units},
                    key=lambda s: s.lower(),
                ),
            })

        # 2) Venue double-booking — same hall used twice at one time.
        if venue and entry.venue_id and venue.id == entry.venue_id:
            conflicts.append({
                'kind': 'venue',
                'entry': entry,
            })

    return conflicts


def compute_day_conflicts(entries):
    """Build the conflict report for an already-scheduled day..


    Returns ``(conflict_pairs, entry_map)`` where ``conflict_pairs`` is a flat
    list of pair-conflict dicts (for the warnings panel)and ``entry_map``
    lists each entry's conflicts (for per-card badges)..
    """
    conflicts = []
    entry_map = {e.pk: [] for e in entries}
    seen = set()

    for a in entries:
        for b in entries:
            if a.pk == b.pk:
                continue
            key = tuple(sorted((a.pk, b.pk)))  # type: ignore
            if key in seen:
                continue
            seen.add(key)
            a_start, a_end = schedule_time_range(a)
            b_start, b_end = schedule_time_range(b)
            if not (a_start < b_end and b_start < a_end):
                continue

            shared = program_units(a.program) & program_units(b.program)

            if shared:
                conflict = {
                    'kind': 'participant',
                    'a': a,
                    'b': b,
                    'shared': sorted(
                        {label for _, _, label in shared},
                        key=str.lower,
                    ),
                }
                conflicts.append(conflict)
                entry_map[a.pk].append(conflict)
                entry_map[b.pk].append(conflict)

            if a.venue_id and b.venue_id and a.venue_id == b.venue_id:
                conflict = {
                    'kind': 'venue',
                    'a': a,
                    'b': b,
                }
                conflicts.append(conflict)
                entry_map[a.pk].append(conflict)
                entry_map[b.pk].append(conflict)

    return conflicts, entry_map