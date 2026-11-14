"""Views for the fest program-scheduling board."""

import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from applications.accounts.models import Madrasa
from applications.program.models import Program, Venue, program_section_q
from .models import FestDay, ScheduleEntry
from .services import check_schedule_conflicts, compute_day_conflicts


def _fest_section(madrasa):
    """Active fest section mode ('both'/'boys'/'girls') for a madrasa."""
    if madrasa is None:
        return Madrasa.FEST_TYPE_BOTH
    return madrasa.fest_type or Madrasa.FEST_TYPE_BOTH


def _madrasa_for(request):
    """Return the logged-in user's madrasa or None (and flash an error)."""
    madrasa = getattr(request.user, 'madrasa', None)
    if madrasa is None:
        messages.error(request, "You need a Madrasa profile to use scheduling.")
    return madrasa


def _resync_program(entry):
    """Mirror the resolved datetime/venue back onto ``Program`` so the legacy
    views (venue PDF, program cards etc.) stay consistent."""
    dt = timezone.make_aware(
        datetime.combine(entry.fest_day.date, entry.start_time)
    )
    Program.objects.filter(pk=entry.program_id).update(
        scheduled_time=dt,
        venue=entry.venue_id,
    )


def _clear_program(program_id):
    Program.objects.filter(pk=program_id).update(scheduled_time=None, venue=None)


def _fmt_ampm(value):
    time_str = value.strftime('%I:%M %p') if value else ''
    return time_str.lstrip('0') if time_str else ''


def _entry_period(entry):
    """(start_label, end_label) for a schedule entry."""
    start = _fmt_ampm(entry.start_time)
    end_dt = datetime.combine(entry.fest_day.date, entry.start_time) + timedelta(
        minutes=entry.duration_minutes or 0
    )
    end = _fmt_ampm(end_dt.time())
    return start, end


def _conflict_display(c):
    a_start, a_end = _entry_period(c['a'])
    b_start, b_end = _entry_period(c['b'])
    return {
        'kind': c['kind'],
        'a_program': c['a'].program.title,
        'b_program': c['b'].program.title,
        'a_period': f'{a_start} – {a_end}',
        'b_period': f'{b_start} – {b_end}',
        'shared': c.get('shared', []),
        'venue': c['a'].venue.name if c['a'].venue_id else '',
    }


def _pool_by_category(madrasa, pool_programs):
    """Group the program pool by category, stage before non-stage inside each.

    Programs are linked to a madrasa's categories through the ``programs``
    M2M (boys) or ``programs_for_girls`` M2M (girls); team-wise general
    programs usually have no category link and land in their own trailing
    bucket so they never disappear from the board. Already-scheduled
    programs keep their ``scheduled_entry`` attribute so the UI can disable
    their schedule button.
    """
    buckets = {}
    for program in pool_programs:
        category = next(
            (c for c in program.category_set.all() if c.madrasa_id == madrasa.id),
            None,
        ) or next(
            (c for c in program.girls_categories.all() if c.madrasa_id == madrasa.id),
            None,
        )
        if category is not None:
            key = f'cat-{category.pk}'
            name = category.name
            order = (0, category.name.lower(), category.pk)
        else:
            key, name, order = 'general', 'General (Team-wise)', (1, '', 0)
        bucket = buckets.setdefault(key, {
            'key': key, 'name': name, 'order': order, 'stage': [], 'non_stage': [],
        })
        (bucket['non_stage'] if program.non_stage else bucket['stage']).append(program)
    groups = sorted(buckets.values(), key=lambda b: b['order'])
    for bucket in groups:
        bucket['total'] = len(bucket['stage']) + len(bucket['non_stage'])
    return groups


@login_required
def schedule_dashboard(request):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')

    section = _fest_section(madrasa)
    programs = Program.objects.filter(program_section_q(madrasa, section)).distinct()
    fest_days = FestDay.objects.filter(madrasa=madrasa, is_active=True)
    venues = Venue.objects.filter(madrasa=madrasa).order_by('name')
    scheduled_entries = {
        entry.program_id: entry
        for entry in ScheduleEntry.objects.filter(fest_day__madrasa=madrasa)
        .select_related('fest_day', 'venue')
    }
    scheduled_ids = list(scheduled_entries)

    search_query = (request.GET.get('q') or '').strip()
    listed_programs = programs
    if search_query:
        listed_programs = programs.filter(title__icontains=search_query)

    pool_programs = list(
        listed_programs.prefetch_related(
            'participants', 'general_teams', 'category_set', 'girls_categories',
        ).order_by('title')
    )
    for program in pool_programs:
        program.scheduled_entry = scheduled_entries.get(program.pk)
    # Unscheduled programs first inside each section; the stable sort keeps
    # the alphabetical title order within both blocks.
    pool_programs.sort(key=lambda p: p.scheduled_entry is not None)

    needle = search_query.lower()
    days = []
    total_conflicts = 0
    for day in fest_days:
        entries = list(
            day.schedule_entries.select_related('program', 'venue').order_by('start_time', 'id')
        )
        if needle:
            entries = [e for e in entries if needle in e.program.title.lower()]
        conflict_pairs, entry_map = compute_day_conflicts(entries)
        total_conflicts += len(conflict_pairs)
        days.append({
            'day': day,
            'entries': [
                {'entry': e, 'conflict_count': len(entry_map.get(e.pk, []))} for e in entries
            ],
            'conflicts': [_conflict_display(c) for c in conflict_pairs],
            'entry_conflicts': {pk: len(list_) for pk, list_ in entry_map.items()},
        })

    context = {
        'madrasa': madrasa,
        'days': days,
        'venues': venues,
        'pool_categories': _pool_by_category(madrasa, pool_programs),
        'pool_count': sum(1 for p in pool_programs if p.scheduled_entry is None),
        'pool_total': len(pool_programs),
        'total_programs': programs.count(),
        'scheduled_count': len(scheduled_ids),
        'unscheduled_count': programs.exclude(pk__in=scheduled_ids).count(),
        'total_conflicts': total_conflicts,
        'search_query': search_query,
        'meelad_fest_name': madrasa.meelad_fest_name,
        'schedule_consent_confirmed': madrasa.schedule_consent_confirmed,
        'schedule_consent_confirmed_at': madrasa.schedule_consent_confirmed_at,
    }
    return render(request, 'schedule/schedule_dashboard.html', context)


# ---------------------------------------------------------------------------
# Schedule-ready consent (confirmation gate)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def set_schedule_consent(request):
    """Confirm (or revoke) that all programs/participation are final.

    Confirming is what unlocks the scheduling board and simultaneously locks
    the generated program-registration link so no new participants can join
    mid-scheduling. Revoking re-enables the registration link.
    """
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')

    agree = request.POST.get('agree') == '1'
    revoke = request.POST.get('revoke') == '1'

    if revoke:
        madrasa.schedule_consent_confirmed = False
        madrasa.schedule_consent_confirmed_at = None
        madrasa.save(update_fields=['schedule_consent_confirmed', 'schedule_consent_confirmed_at'])
        messages.success(
            request,
            "Schedule-ready consent revoked. The registration link is re-enabled — "
            "update programs / participants, then confirm again before scheduling.",
        )
    elif agree:
        madrasa.schedule_consent_confirmed = True
        madrasa.schedule_consent_confirmed_at = timezone.now()
        madrasa.save(update_fields=['schedule_consent_confirmed', 'schedule_consent_confirmed_at'])
        messages.success(
            request,
            "Thanks — all programs and participation are confirmed. "
            "You can now schedule programs; the registration link is disabled.",
        )
    return redirect('schedule_dashboard')


# ---------------------------------------------------------------------------
# Fest day CRUD
# ---------------------------------------------------------------------------
@login_required
@require_POST
def add_fest_day(request):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    name = request.POST.get('name', '').strip()
    date_str = request.POST.get('date', '').strip()
    if not name or not date_str:
        messages.error(request, 'Fest day name and date are required.')
        return redirect('schedule_dashboard')
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Invalid date format.')
        return redirect('schedule_dashboard')
    FestDay.objects.create(madrasa=madrasa, name=name, date=date)
    messages.success(request, f"Fest day '{name}' added.")
    return redirect('schedule_dashboard')


@login_required
@require_POST
def edit_fest_day(request, pk):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    day = get_object_or_404(FestDay, pk=pk, madrasa=madrasa)
    name = request.POST.get('name', '').strip()
    date_str = request.POST.get('date', '').strip()
    if not name or not date_str:
        messages.error(request, 'Fest day name and date are required.')
        return redirect('schedule_dashboard')
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Invalid date format.')
        return redirect('schedule_dashboard')
    day.name = name
    day.date = date
    day.is_active = request.POST.get('is_active') == 'on'
    day.save()
    for entry in day.schedule_entries.select_related('fest_day'):
        _resync_program(entry)
    messages.success(request, f"Fest day '{name}' updated.")
    return redirect('schedule_dashboard')


@login_required
@require_POST
def delete_fest_day(request, pk):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    day = get_object_or_404(FestDay, pk=pk, madrasa=madrasa)
    for program_id in day.schedule_entries.values_list('program_id', flat=True):
        _clear_program(program_id)
    day.delete()
    messages.success(request, 'Fest day deleted.')
    return redirect('schedule_dashboard')
# ---------------------------------------------------------------------------
# Schedule entry CRUD
# ---------------------------------------------------------------------------
def _parse_schedule_form(request, fixed_program=None):
    """Parse and validate the schedule form fields.

    Returns (program, day, start_time, duration, venue, notes, errors).
    """
    errors = []
    program = None
    if fixed_program:
        program = get_object_or_404(Program, pk=fixed_program, madrasa=request.user.madrasa)
    else:
        program_id = request.POST.get('program')
        try:
            program = Program.objects.get(pk=program_id, madrasa=request.user.madrasa)
        except (Program.DoesNotExist, ValueError, TypeError):
            errors.append('Please choose a valid program.')

    fest_day_id = request.POST.get('fest_day')
    day = None
    try:
        day = FestDay.objects.get(pk=fest_day_id, madrasa=request.user.madrasa)
    except (FestDay.DoesNotExist, ValueError, TypeError):
        errors.append('Please choose a valid fest day.')

    start_time = None
    start_str = request.POST.get('start_time', '').strip()
    if start_str:
        try:
            start_time = datetime.strptime(start_str, '%H:%M').time()
        except ValueError:
            errors.append('Please choose a valid start time.')
    else:
        errors.append('Please choose a start time.')

    duration = request.POST.get('duration_minutes')
    try:
        duration = int(duration)
        if duration <= 0:
            raise ValueError
    except (TypeError, ValueError):
        duration = None
        errors.append('Duration must be a positive number of minutes.')

    venue = None
    venue_id = request.POST.get('venue') or None
    if venue_id:
        try:
            venue = Venue.objects.get(pk=venue_id, madrasa=request.user.madrasa)
        except (Venue.DoesNotExist, ValueError, TypeError):
            errors.append('Please choose a valid venue.')

    notes = request.POST.get('notes', '').strip() or None
    return program, day, start_time, duration, venue, notes, errors
@login_required
@require_POST
def add_schedule(request):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    program, day, start_time, duration, venue, notes, errors = _parse_schedule_form(request)
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('schedule_dashboard')
    if ScheduleEntry.objects.filter(program=program).exists():
        messages.error(request, f"'{program.title}' is already scheduled — edit its existing slot instead.")
        return redirect('schedule_dashboard')

    conflicts = check_schedule_conflicts(program, day, start_time, duration, venue)
    entry = ScheduleEntry.objects.create(
        program=program,
        fest_day=day,
        start_time=start_time,
        duration_minutes=duration,
        venue=venue,
        notes=notes,
    )
    _resync_program(entry)
    if conflicts:
        messages.warning(
            request,
            f"Scheduled '{program.title}' but found {len(conflicts)} conflict(s) — review the warnings panel to fix them.",
        )
    else:
        messages.success(request, f"'{program.title}' scheduled — no conflicts.")
    return redirect('schedule_dashboard')


@login_required
@require_POST
def edit_schedule(request, pk):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    entry = get_object_or_404(ScheduleEntry, pk=pk, fest_day__madrasa=madrasa)

    program, day, start_time, duration, venue, notes, errors = _parse_schedule_form(
        request, fixed_program=entry.program_id
    )
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('schedule_dashboard')

    entry.fest_day = day
    entry.start_time = start_time
    entry.duration_minutes = duration
    entry.venue = venue
    entry.notes = notes
    entry.save()
    _resync_program(entry)
    conflicts = check_schedule_conflicts(
        entry.program, day, start_time, duration, venue, exclude_pk=entry.pk
    )
    if conflicts:
        messages.warning(
            request,
            f"Updated '{program.title}' but still {len(conflicts)} conflict(s) — review the warnings panel.",
        )
    else:
        messages.success(request, f"'{program.title}' updated — no conflicts.")
    return redirect('schedule_dashboard')


@login_required
@require_POST
def delete_schedule(request, pk):
    madrasa = _madrasa_for(request)
    if not madrasa:
        return redirect('home')
    entry = get_object_or_404(ScheduleEntry, pk=pk, fest_day__madrasa=madrasa)

    title = entry.program.title
    _clear_program(entry.program_id)
    entry.delete()
    messages.success(request, f"'{title}' unscheduled.")
    return redirect('schedule_dashboard')
# ---------------------------------------------------------------------------
# Live conflict check (used by the schedule modal before saving)
# ---------------------------------------------------------------------------
@login_required
@csrf_exempt
def check_schedule_conflicts_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        body = {}
    madrasa = _madrasa_for(request)
    if not madrasa:
        return JsonResponse({'ok': False, 'conflicts': [], 'message': 'Profile required.'}, status=400)

    program_id = body.get('program')
    fest_day_id = body.get('fest_day')
    start_str = body.get('start_time')
    duration = body.get('duration_minutes') or 60
    venue_id = body.get('venue') or None
    exclude_pk = body.get('exclude_pk') or None

    program = None
    if program_id:
        try:
            program = Program.objects.get(pk=program_id, madrasa=madrasa)
        except (Program.DoesNotExist, ValueError, TypeError):
            program = None
    day = None
    if fest_day_id:
        try:
            day = FestDay.objects.get(pk=fest_day_id, madrasa=madrasa)
        except (FestDay.DoesNotExist, ValueError, TypeError):
            day = None

    start_time = None
    try:
        start_time = datetime.strptime(start_str, '%H:%M').time() if start_str else None
        duration = int(duration)
        duration = max(duration, 1)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'conflicts': [], 'message': 'Invalid time or duration.'})

    if not program or not day or not start_time:
        return JsonResponse({'ok': True, 'conflicts': [], 'message': ''})

    venue = None
    if venue_id:
        try:
            venue = Venue.objects.get(pk=venue_id, madrasa=madrasa)
        except (Venue.DoesNotExist, ValueError, TypeError):
            venue = None

    exclude_pk_int = int(exclude_pk) if exclude_pk else None
    conflicts = check_schedule_conflicts(
        program, day, start_time, duration, venue, exclude_pk=exclude_pk_int
    )
    payload = []
    for c in conflicts:
        other = c['entry']
        other_start, other_end = _entry_period(other)
        payload.append({
            'kind': c['kind'],
            'program': program.title,
            'other_program': other.program.title,
            'other_period': f'{other_start} – {other_end}',
            'venue': other.venue.name if other.venue_id else '',
            'shared': c.get('shared', []),
        })
    return JsonResponse({'ok': len(payload) == 0, 'conflicts': payload, 'message': ''})