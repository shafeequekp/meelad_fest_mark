"""Read-only endpoints exposed to the AI service.

Every read is scoped to the acting user's madrasa and returns only whitelisted
serialized data. The AI service never touches Django models; it communicates
exclusively through these endpoints.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse

from applications.program.models import Prize, Student
from applications.scoreboard.models import Team
from . import services
from . import serializers as s
from .auth import require_service, resolve_actor


def _actor_or_deny(request):
    actor = resolve_actor(request)
    if actor is None or actor.madrasa_id is None:
        raise PermissionDenied("Authenticated user with a madrasa is required.")
    return actor


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


# ---------------------------------------------------------------------------
# Fest rules & regulations (AI knowledge base source)
# ---------------------------------------------------------------------------
@require_service
def fest_rules(request):
    """Return this madrasa's fest-rules document text for the AI knowledge base.

    The AI service builds its per-madrasa RAG index from this response. The
    text was extracted from the uploaded PDF at upload time, so the AI service
    never needs a PDF parser. ``updated_at`` lets it detect re-uploads and
    rebuild its index.
    """
    actor = _actor_or_deny(request)
    madrasa = actor.madrasa
    if not (madrasa.fest_rules and (madrasa.fest_rules_text or "").strip()):
        return _json({"has_rules": False, "madrasa_id": madrasa.id})
    return _json({
        "has_rules": True,
        "madrasa_id": madrasa.id,
        "madrasa_name": madrasa.name,
        "fest_name": madrasa.meelad_fest_name or "",
        "updated_at": (madrasa.fest_rules_updated_at.isoformat()
                       if madrasa.fest_rules_updated_at else None),
        "file_name": madrasa.fest_rules.name.rsplit("/", 1)[-1],
        "text": madrasa.fest_rules_text,
    })


@require_service
def health(request):
    return _json({"status": "ok", "service": "meelad-ai-django"})


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
@require_service
def list_teams(request):
    actor = _actor_or_deny(request)
    teams = Team.objects.filter(madrasa=actor.madrasa).order_by("name")
    return _json({"teams": [s.team_summary(t) for t in teams]})


@require_service
def team_detail(request, team_id):
    actor = _actor_or_deny(request)
    team = Team.objects.filter(madrasa=actor.madrasa, id=team_id).first()
    if not team:
        return _json({"error": "Team not found"}, 404)
    return _json({"team": s.team_summary(team)})


@require_service
def team_rankings(request):
    """Reuse the authoritative deterministic leaderboard from Django."""
    actor = _actor_or_deny(request)
    # Leaderboard respects the fest structure (boys/girls-only fests never
    # count the other section's prizes).
    leaderboard = Prize.get_team_leaderboard(
        actor.madrasa, services.fest_type_for(actor.madrasa))
    rows = [s.leaderboard_row(rank, row) for rank, row in enumerate(leaderboard, start=1)]
    return _json({"leaderboard": rows, "method": "Prize.get_team_leaderboard"})


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
@require_service
def search_students(request):
    actor = _actor_or_deny(request)
    q = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 20) or 20), 50)
    # In a boys-only / girls-only fest, students of the other section are
    # invisible to the AI.
    qs = Student.objects.filter(
        team__madrasa=actor.madrasa,
        gender__in=actor.madrasa.active_genders(),
    ).select_related("team", "category")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(code_number__icontains=q))
    return _json({"students": [s.student_summary(st) for st in qs[:limit]]})


@require_service
def student_detail(request, student_id):
    actor = _actor_or_deny(request)
    student = Student.objects.filter(
        id=student_id, team__madrasa=actor.madrasa,
        gender__in=actor.madrasa.active_genders(),
    ).select_related("team", "category").first()
    if not student:
        return _json({"error": "Student not found"}, 404)
    return _json({"student": s.student_summary(student)})


@require_service
def student_programs(request, student_id):
    actor = _actor_or_deny(request)
    student = Student.objects.filter(
        id=student_id, team__madrasa=actor.madrasa,
        gender__in=actor.madrasa.active_genders(),
    ).first()
    if not student:
        return _json({"error": "Student not found"}, 404)
    # Only programs of the fest's active sections.
    programs = (
        services.programs_for_madrasa(actor.madrasa)
        .filter(participants=student)
        .distinct()
    )
    return _json({"student": s.student_summary(student),
                  "programs": [s.program_summary(p) for p in programs]})


@require_service
def student_results(request, student_id):
    actor = _actor_or_deny(request)
    student = Student.objects.filter(
        id=student_id, team__madrasa=actor.madrasa,
        gender__in=actor.madrasa.active_genders(),
    ).first()
    if not student:
        return _json({"error": "Student not found"}, 404)
    individual = Prize.objects.filter(
        student=student, program__is_result_published=True,
        program__is_group=False, program__is_general=False,
    ).exclude(position__isnull=True, grade__isnull=True).select_related("program", "position", "grade")
    group = Prize.objects.filter(
        participants=student, program__is_result_published=True,
    ).select_related("program", "group_program_position", "general_program_position")
    return _json({
        "student": s.student_summary(student),
        "results": [s.prize_summary(p) for p in list(individual) + list(group)],
    })


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@require_service
def list_programs(request):
    actor = _actor_or_deny(request)
    qs = services.programs_for_madrasa(actor.madrasa).distinct().order_by("title")
    q = request.GET.get("q", "").strip()
    is_group = request.GET.get("is_group")
    is_general = request.GET.get("is_general")
    section = request.GET.get("section")
    scheduled = request.GET.get("scheduled")
    if q:
        qs = qs.filter(title__icontains=q)
    if is_group is not None:
        qs = qs.filter(is_group=is_group == "true")
    if is_general is not None:
        qs = qs.filter(is_general=is_general == "true")
    if section:
        # A section outside the fest structure (e.g. 'girls' in a boys-only
        # fest) can never have programs.
        if section not in services.active_sections_for(actor.madrasa):
            return _json({"programs": []})
        qs = qs.filter(section=section)
    if scheduled is not None:
        qs = qs.filter(scheduled_time__isnull=(scheduled == "false"))
    return _json({"programs": [s.program_summary(p) for p in qs[:50]]})


@require_service
def program_detail(request, program_id):
    actor = _actor_or_deny(request)
    program = services.programs_for_madrasa(actor.madrasa).filter(id=program_id).first()
    if not program:
        return _json({"error": "Program not found"}, 404)
    return _json({"program": s.program_summary(program)})


@require_service
def program_participants(request, program_id):
    actor = _actor_or_deny(request)
    program = services.programs_for_madrasa(actor.madrasa).filter(id=program_id).first()
    if not program:
        return _json({"error": "Program not found"}, 404)
    participants = program.participants.filter(
        team__madrasa=actor.madrasa).select_related("team", "category")
    return _json({
        "program": s.program_summary(program),
        "participants": [s.student_summary(p) for p in participants],
    })


@require_service
def program_result(request, program_id):
    actor = _actor_or_deny(request)
    program = services.programs_for_madrasa(actor.madrasa).filter(id=program_id).first()
    if not program:
        return _json({"error": "Program not found"}, 404)
    if not program.is_result_published:
        return _json({"program": s.program_summary(program), "published": False,
                      "detail": "Result not yet published."})
    prizes = Prize.objects.filter(program=program).select_related(
        "student", "team", "position", "grade", "group_program_position",
        "general_program_position")
    return _json({"program": s.program_summary(program), "published": True,
                  "prizes": [s.prize_summary(p) for p in prizes]})
# ---------------------------------------------------------------------------
# Group programs & groups
# ---------------------------------------------------------------------------
@require_service
def list_group_programs(request):
    actor = _actor_or_deny(request)
    progs = services.programs_for_madrasa(actor.madrasa).filter(is_group=True).distinct().order_by("title")
    return _json({"programs": [s.program_summary(p) for p in progs]})


@require_service
def group_program_groups(request, program_id):
    actor = _actor_or_deny(request)
    program = services.programs_for_madrasa(actor.madrasa).filter(id=program_id, is_group=True).first()
    if not program:
        return _json({"error": "Program not found"}, 404)
    prizes = Prize.objects.filter(program=program).prefetch_related(
        "participants", "participants__team", "group_program_position")
    out = []
    for p in prizes:
        names = [m.full_name for m in p.participants.all()]
        if not names:
            continue
        out.append({
            "id": p.id,
            "display_name": " & ".join(names) if len(names) > 1 else f"{names[0]} & Team",
            "team": p.team.name if p.team_id else None,
            "member_count": len(names),
            "position": (p.group_program_position.name if p.group_program_position_id else None),
            "members": [m.full_name for m in p.participants.all()],
        })
    return _json({"program": s.program_summary(program), "groups": out})


# ---------------------------------------------------------------------------
# Venues & availability
# ---------------------------------------------------------------------------
@require_service
def list_venues(request):
    actor = _actor_or_deny(request)
    from applications.program.models import Venue
    venues = Venue.objects.filter(madrasa=actor.madrasa).order_by("name")
    return _json({"venues": [s.venue_summary(v) for v in venues]})


@require_service
def venue_schedule(request, venue_id):
    actor = _actor_or_deny(request)
    from applications.program.models import Venue
    venue = Venue.objects.filter(id=venue_id, madrasa=actor.madrasa).first()
    if not venue:
        return _json({"error": "Venue not found"}, 404)
    schedule = services.get_venue_schedules(actor.madrasa, venue)
    return _json({
        "venue": s.venue_summary(venue),
        "schedule": [{
            "program_id": p.id, "title": p.title,
            "scheduled_time": p.scheduled_time.isoformat() if p.scheduled_time else None,
        } for p in schedule],
    })


@require_service
def venue_availability(request, venue_id):
    actor = _actor_or_deny(request)
    from applications.program.models import Venue
    venue = Venue.objects.filter(id=venue_id, madrasa=actor.madrasa).first()
    if not venue:
        return _json({"error": "Venue not found"}, 404)
    at = request.GET.get("datetime")
    if not at:
        return _json({"venue": s.venue_summary(venue)})
    from django.utils import timezone
    try:
        dt = timezone.datetime.fromisoformat(at)
    except ValueError:
        return _json({"error": "datetime must be ISO-8601"}, 400)
    available = not services.get_recents_schedule(
        actor.madrasa).filter(venue=venue, scheduled_time__date=dt.date()).exists()
    return _json({"venue": s.venue_summary(venue), "at": at, "available": available})
# ---------------------------------------------------------------------------
# Fest days (scheduling unit for the AI service)
# ---------------------------------------------------------------------------
@require_service
def list_fest_days(request):
    """Active fest days of the actor's madrasa (id, name, date)."""
    actor = _actor_or_deny(request)
    from applications.schedule.models import FestDay
    days = FestDay.objects.filter(
        madrasa=actor.madrasa, is_active=True).order_by("date", "id")
    return _json({"fest_days": [
        {"id": d.id, "name": d.name, "date": d.date.isoformat()} for d in days
    ]})


# ---------------------------------------------------------------------------
# Schedules / unscheduled / suggestions / conflicts
# ---------------------------------------------------------------------------
@require_service
def list_schedules(request):
    actor = _actor_or_deny(request)
    schedule = services.get_recents_schedule(actor.madrasa)
    return _json({"schedule": [{
        "program_id": p.id, "title": p.title,
        "venue": p.venue.name if p.venue_id else None,
        "scheduled_time": p.scheduled_time.isoformat() if p.scheduled_time else None,
    } for p in schedule]})


@require_service
def unscheduled_programs(request):
    actor = _actor_or_deny(request)
    programs = services.get_unscheduled_programs(actor.madrasa)
    return _json({"programs": [s.program_summary(p) for p in programs]})


@require_service
def suggest_schedule(request):
    """Compute a conflict-free proposed schedule for a date (read-only)."""
    from datetime import date
    from applications.program.models import Venue
    actor = _actor_or_deny(request)
    date_raw = request.GET.get("date")
    if not date_raw:
        return _json({"error": "date (YYYY-MM-DD) is required"}, 400)
    try:
        target = date.fromisoformat(date_raw)
    except ValueError:
        return _json({"error": "date must be YYYY-MM-DD"}, 400)
    venues = Venue.objects.filter(madrasa=actor.madrasa).order_by("name")
    from datetime import time as dtime
    slots = []
    for h in range(9, 17):
        slots.append(dtime(h, 0))
        slots.append(dtime(h, 30))
    madrasa = actor.madrasa
    proposals = services.suggest_conflict_free_schedule(
        madrasa, target, venues, slots, window_minutes=60)
    # Scheduling writes need a FestDay id (same strategy as add_schedule), so
    # attach it to every proposal; the planner refuses to guess one.
    from applications.schedule.models import FestDay
    day = FestDay.objects.filter(
        madrasa=madrasa, date=target, is_active=True).first()
    for p in proposals:
        p["fest_day"] = day.id if day else None
    return _json({
        "date": date_raw,
        "fest_day": day.id if day else None,
        "fest_day_name": day.name if day else None,
        "proposals": proposals,
        "count": len(proposals),
        "unscheduled_count": services.get_unscheduled_programs(madrasa).count(),
    })


@require_service
def schedule_conflicts(request):
    actor = _actor_or_deny(request)
    schedule = services.get_recents_schedule(actor.madrasa).select_related("venue")
    by_key = {}
    for p in schedule:
        if not p.venue_id or not p.scheduled_time:
            continue
        key = (p.venue_id, p.scheduled_time.date())
        by_key.setdefault(key, []).append(p)
    conflicts = []
    for (venue_id, day), progs in by_key.items():
        if len(progs) > 1:
            conflicts.append({
                "day": day.isoformat(),
                "venue": progs[0].venue.name,
                "programs": [
                    {"program_id": x.id, "title": x.title,
                     "scheduled_time": x.scheduled_time.isoformat()} for x in progs
                ],
            })
    return _json({"conflicts": conflicts})
# ---------------------------------------------------------------------------
# Frontend chat proxy (browser -> Django -> FastAPI)
# ---------------------------------------------------------------------------
# This is the ONLY endpoint the browser talks to for the AI widget. It is
# session-authenticated (the user is already logged into Django) and carries a
# CSRF token, so the LLM API key never reaches the browser. Django forwards the
# request to the FastAPI AI service using the shared service token.
def chat_proxy(request):
    """Forward a chat message to the AI service and relay its answer."""
    if request.method != "POST":
        return _json({"error": "POST required"}, 405)
    if not request.user or not request.user.is_authenticated:
        return _json({"error": "Authentication required"}, 401)

    import json as _json_mod
    try:
        body = _json_mod.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return _json({"error": "Invalid JSON body"}, 400)

    message = (body.get("message") or "").strip()
    if not message:
        return _json({"error": "message is required"}, 400)

    return _forward_to_ai_service(request, message, body)


def _forward_to_ai_service(request, message, body):
    import time
    import threading
    import requests
    import logging
    from django.conf import settings

    logger = logging.getLogger(__name__)
    base = getattr(settings, "MEELAD_AI_SERVICE_BASE_URL", "")
    token = getattr(settings, "MEELAD_AI_SERVICE_TOKEN", "")
    if not base or not token:
        return _json({"error": "AI service is not configured."}, 503)

    conversation_id = body.get("conversation_id")
    payload = {
        "message": message,
        "conversation_id": conversation_id,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Meelad-AI-Token": token,
        "X-Meelad-User-Id": str(request.user.id),
    }

    # requests' ``timeout`` is a per-socket-read guard, NOT a total deadline:
    # if the AI service (or any proxy in between) keeps the connection open,
    # the chat can outlive MEELAD_AI_CHAT_TIMEOUT and the gunicorn arbiter
    # aborts the worker mid-request (SIGABRT -> sys.exit(1)), so the browser
    # gets an HTML 500 it cannot parse. Run the call in a helper thread and
    # enforce a hard wall-clock deadline here so Django's own JSON error
    # always wins before the worker timeout (deadline must stay below the
    # gunicorn --timeout).
    deadline = float(getattr(settings, "MEELAD_AI_CHAT_TIMEOUT", 60))

    box = {}

    def _post():
        try:
            box["resp"] = requests.post(
                f"{base}/api/ai/chat", json=payload, headers=headers,
                timeout=(10, deadline))
        except Exception as exc:  # noqa: BLE001 - relayed below
            box["exc"] = exc

    started = time.monotonic()
    helper = threading.Thread(target=_post, daemon=True, name="ai-chat-proxy")
    helper.start()
    helper.join(timeout=deadline)
    elapsed = time.monotonic() - started

    if helper.is_alive():
        # Hard deadline exceeded; the daemon thread is abandoned and its
        # socket cleaned up whenever the AI side eventually closes it.
        logger.error("AI chat exceeded %.0fs hard deadline (%.1fs elapsed)",
                     deadline, elapsed)
        return _json({"error": "AI service timed out. Please try again."}, 504)

    resp = box.get("resp")
    if resp is None:
        exc = box.get("exc")
        if isinstance(exc, requests.exceptions.ConnectionError):
            logger.error("AI service unreachable (%.1fs elapsed)", elapsed)
            return _json({"error": "AI service is unavailable."}, 503)
        if isinstance(exc, requests.exceptions.Timeout):
            logger.error("AI service request timed out (%.1fs elapsed)", elapsed)
            return _json({"error": "AI service timed out. Please try again."}, 504)
        logger.error("Unexpected AI proxy failure: %r (%.1fs elapsed)", exc, elapsed)
        return _json({"error": "Could not reach the AI service."}, 500)

    if resp.status_code >= 500:
        logger.error("AI service error: %s %s", resp.status_code, resp.text[:300])
        return _json({"error": "AI service encountered an error."}, 502)
    try:
        data = resp.json()
    except ValueError:
        logger.error("AI service returned a non-JSON body (status %s)",
                     resp.status_code)
        return _json({"error": "AI service returned an invalid response."}, 502)
    # Persist the turn for the history dropdown (best-effort; only on real
    # AI answers — never on relayed error payloads, and never 500s).
    try:
        if isinstance(data, dict) and not data.get("error") and data.get("answer"):
            conv_id = _save_chat_turn(
                request.user, message, data.get("answer", ""),
                data.get("conversation_id") or conversation_id)
            data["conversation_id"] = conv_id
    except Exception:  # noqa: BLE001
        pass
    return _json(data, status=resp.status_code)


def chat_health(request):
    """Lightweight health probe used by the AI widget."""
    return _json({"available": True})


# ---------------------------------------------------------------------------
# Chat history (browser -> Django, session auth). The widget shows a history
# button next to the close button; clicking it lists the user's latest 20
# sessions (ChatGPT-style titles derived from the first message).
# ---------------------------------------------------------------------------
def _history_title(text):
    text = " ".join((text or "").split())
    return text[:80] if text else "New chat"


def chat_history(request):
    """Return the logged-in user's latest 20 AI chat sessions."""
    if not request.user or not request.user.is_authenticated:
        return _json({"error": "Authentication required"}, 401)
    from .models import AIChatSession
    sessions = (
        AIChatSession.objects.filter(user=request.user)
        .order_by("-updated")[:20]
    )
    return _json({"sessions": [
        {"conversation_id": s.conversation_id, "title": s.title or "New chat",
         "updated": s.updated.isoformat() if s.updated else None}
        for s in sessions
    ]})


def chat_history_detail(request, conversation_id):
    """Return all messages of one session owned by the logged-in user."""
    if not request.user or not request.user.is_authenticated:
        return _json({"error": "Authentication required"}, 401)
    from .models import AIChatSession
    session = AIChatSession.objects.filter(
        user=request.user, conversation_id=conversation_id).first()
    if not session:
        return _json({"error": "Chat not found"}, 404)
    return _json({
        "conversation_id": session.conversation_id,
        "title": session.title or "New chat",
        "messages": [
            {"role": m.role, "content": m.content}
            for m in session.messages.all()
        ],
    })


def chat_new(request):
    """Start a fresh thread: the widget drops its conversation_id."""
    if request.method != "POST":
        return _json({"error": "POST required"}, 405)
    if not request.user or not request.user.is_authenticated:
        return _json({"error": "Authentication required"}, 401)
    import uuid as _uuid
    return _json({"conversation_id": str(_uuid.uuid4())})


def _save_chat_turn(user, message, answer, conversation_id):
    """Persist one user/assistant turn; never breaks the chat on failure."""
    try:
        from .models import AIChatSession, AIChatMessage
        if not conversation_id:
            import uuid as _uuid
            conversation_id = str(_uuid.uuid4())
        session, created = AIChatSession.objects.get_or_create(
            user=user, conversation_id=conversation_id,
            defaults={"title": _history_title(message)},
        )
        if created and not session.title:
            session.title = _history_title(message)
            session.save(update_fields=["title"])
        AIChatMessage.objects.create(
            session=session, role=AIChatMessage.ROLE_USER, content=message)
        if answer:
            AIChatMessage.objects.create(
                session=session, role=AIChatMessage.ROLE_ASSISTANT,
                content=answer)
        session.save(update_fields=["updated"])
        return conversation_id
    except Exception:  # noqa: BLE001 - history must never break chat
        import logging as _logging
        _logging.getLogger(__name__).debug("AI chat history save failed",
                                           exc_info=True)
        return conversation_id