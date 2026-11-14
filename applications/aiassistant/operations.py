"""AI-initiated write operations.

Every write the assistant can trigger funnels through here so Django remains
the system of record and the final validator. Each operation:
  * requires the trusted service token AND a resolvable actor user,
  * is scoped to the acting user's madrasa,
  * re-validates existing business rules (participant existence, min group
    size, same-team rule, schedule conflicts, ...),
  * supports an idempotency key to avoid double application,
  * writes an audit row.
"""
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from applications.program.models import Program, Prize, Student, Venue
from applications.schedule.models import ScheduleEntry, FestDay
from . import services
from .auth import require_service, resolve_actor
from .models import AIOperationAuditLog

from applications.schedule.views import _resync_program


def _deny(message, status=403):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _actor_or_deny(request):
    actor = resolve_actor(request)
    if actor is None or actor.madrasa_id is None:
        return None, _deny("Authenticated user with a madrasa is required.")
    return actor, None


def _get_program(request, program_id, actor):
    if not program_id:
        return None, _deny("program_id is required.", 400)
    program = services.programs_for_madrasa(actor.madrasa).filter(id=program_id).first()
    if program is None:
        return None, _deny("Program not found.", 404)
    return program, None


def _log(actor, action, target_type, target_id, payload,
         idempotency_key="", success=False, message=""):
    return AIOperationAuditLog.objects.create(
        user=actor, action=action, target_type=target_type, target_id=target_id,
        payload=payload, idempotency_key=idempotency_key,
        approved=True, success=success, message=message,
    )


@require_service
@transaction.atomic
def op_schedule(request):
    """Create a program's slot via FestDay + ScheduleEntry (like add_schedule)."""
    actor, err = _actor_or_deny(request)
    if err:
        return err
    if request.method != "POST":
        return _deny("POST required.", 405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _deny("Invalid JSON body.", 400)

    program_id = payload.get("program_id")
    venue_id = payload.get("venue_id")
    scheduled_time_raw = payload.get("scheduled_time")  # legacy fallback only
    idem = payload.get("idempotency_key", "") or ""

    program, err = _get_program(request, program_id, actor)
    if err:
        return err

    venue = Venue.objects.filter(id=venue_id, madrasa=actor.madrasa).first() if venue_id else None
    if venue_id and venue is None:
        return _deny("Venue not found.", 404)

    # Fest-day strategy (same as add_schedule): fest_day id + HH:MM start +
    # duration. Legacy scheduled_time ISO still maps onto its FestDay.
    from datetime import datetime as _dt
    from applications.schedule.services import check_schedule_conflicts as _check
    _day = None
    _fd = payload.get("fest_day") or payload.get("fest_day_id")
    if _fd:
        try:
            _day = FestDay.objects.get(pk=_fd, madrasa=actor.madrasa)
        except (FestDay.DoesNotExist, ValueError, TypeError):
            return _deny("Please choose a valid fest day.", 400)
    _start = None
    _st = str(payload.get("start_time") or "").strip()
    if _st:
        try:
            _start = _dt.strptime(_st, "%H:%M").time()
        except ValueError:
            return _deny("start_time must be HH:MM.", 400)
    if scheduled_time_raw and (_day is None or _start is None):
        try:
            _sched = timezone.datetime.fromisoformat(scheduled_time_raw)
        except ValueError:
            return _deny("scheduled_time must be ISO-8601.", 400)
        if timezone.is_naive(_sched):
            _sched = timezone.make_aware(_sched)
        if _day is None:
            _day = FestDay.objects.filter(
                madrasa=actor.madrasa, date=_sched.date()).first()
            if _day is None:
                return _deny("No fest day exists for that date.", 400)
        if _start is None:
            _start = _sched.timetz()
    if _day is None:
        return _deny("fest_day is required.", 400)
    if _start is None:
        return _deny("start_time (HH:MM) is required.", 400)
    try:
        _dur = int(payload.get("duration_minutes", 60))
        if _dur <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _deny("duration_minutes must be positive.", 400)
    _notes = str(payload.get("notes") or "").strip() or None

    # Idempotency guard first: same key + success means replay, even though
    # the program now has an entry from the first apply.
    if idem:
        existing = AIOperationAuditLog.objects.filter(
            action="schedule", idempotency_key=idem, success=True).first()
        if existing:
            return JsonResponse({"ok": True, "message": "Already applied (idempotent).", "idempotent": True})
    if ScheduleEntry.objects.filter(program=program).exists():
        return _deny("Already scheduled — edit its slot instead.", 409)

    # program.venue = venue (legacy mirror handled by _resync_program below)


    entry = ScheduleEntry.objects.create(
        program=program, fest_day=_day, start_time=_start,
        duration_minutes=_dur, venue=venue, notes=_notes
    )
    _resync_program(entry)
    _warns = []
    for _c in _check(program, _day, _start, _dur, venue):
        _o = _c["entry"]
        _warns.append({"kind": _c["kind"], "other_program": _o.program.title,
                       "other_time": _o.start_time.strftime("%H:%M"),
                       "venue": _o.venue.name if _o.venue_id else "",
                       "shared": _c.get("shared", [])})
    _log(actor, "schedule", "program", program.id,
         {"fest_day_id": _day.id, "start_time": _start.strftime("%H:%M"),
          "duration_minutes": _dur,
          "venue_id": venue.id if venue else None},
         idem, success=True,
         message=("Scheduled with %d conflict(s)." % len(_warns)
                  if _warns else "Program scheduled."))
    _out = {"ok": True, "message": "Program scheduled.",
            "entry_id": entry.id, "fest_day": _day.name,
            "date": _day.date.isoformat(),
            "start_time": _start.strftime("%H:%M")}
    if _warns:
        _out["message"] = "Program scheduled with conflicts."
        _out["warnings"] = _warns
    return JsonResponse(_out)


@require_service
@transaction.atomic
def op_create_group(request):
    """Create a group for a group program (mirrors the existing group flow)."""
    actor, err = _actor_or_deny(request)
    if err:
        return err
    if request.method != "POST":
        return _deny("POST required.", 405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _deny("Invalid JSON body.", 400)

    program_id = payload.get("program_id")
    participant_ids = payload.get("participant_ids") or []
    idem = payload.get("idempotency_key", "") or ""

    program, err = _get_program(request, program_id, actor)
    if err:
        return err
    if not program.is_group:
        return _deny("Group creation requires a group program.", 400)

    participant_ids = [int(p) for p in participant_ids if str(p or "").strip()]
    if len(participant_ids) < 2:
        return _deny("A group must contain at least two members.", 400)

    # --- Existing business rules (mirror of the group-program workflow) ---
    students = list(Student.objects.filter(
        id__in=participant_ids, program__id=program.id, team__madrasa=actor.madrasa))
    if len(students) != len(set(participant_ids)):
        return _deny("Some selected participants are not registered for this program.", 400)
    teams = {s.team_id for s in students}
    if len(teams) != 1:
        return _deny("All group members must belong to the same team.", 400)

    assigned = set(Prize.objects.filter(
        program=program, participants__in=students).values_list("participants__id", flat=True))
    if assigned & set(participant_ids):
        return _deny("One or more selected participants are already in a group.", 400)

    if idem:
        existing = AIOperationAuditLog.objects.filter(
            action="create_group", idempotency_key=idem, success=True,
            target_id=program.id).first()
        if existing:
            return JsonResponse({"ok": True, "message": "Already applied (idempotent key).", "idempotent": True})

    team = students[0].team
    group = Prize.objects.create(program=program, team=team)
    group.participants.set(students)

    _log(actor, "create_group", "program", program.id,
         {"participant_ids": participant_ids}, idem, success=True,
         message=f"Group created with {len(students)} members.")
    return JsonResponse({"ok": True, "message": "Group created.", "group_id": group.id})


@require_service
@transaction.atomic
def op_remove_group_participant(request):
    actor, err = _actor_or_deny(request)
    if err:
        return err
    if request.method != "POST":
        return _deny("POST required.", 405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _deny("Invalid JSON body.", 400)

    program, err = _get_program(request, payload.get("program_id"), actor)
    if err:
        return err
    student = Student.objects.filter(
        id=payload.get("participant_id"), team__madrasa=actor.madrasa).first()
    if student is None:
        return _deny("Participant not found.", 404)

    program.participants.remove(student)
    for g in Prize.objects.filter(program=program, participants=student):
        g.participants.remove(student)
        if g.participants.count() == 0:
            g.delete()

    _log(actor, "remove_group_participant", "program", program.id,
         {"participant_id": student.id}, payload.get("idempotency_key", ""),
         success=True, message="Participant removed from program.")
    return JsonResponse({"ok": True, "message": "Participant removed."})