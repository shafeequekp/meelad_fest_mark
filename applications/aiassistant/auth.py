"""Service-to-service authentication for the AI boundary.

Two concerns are separated:

* ``require_service`` — proves the caller is the trusted AI service (FastAPI)
  by checking a shared bearer token. This is not user authorization; it only
  authenticates the calling service.
* ``actor_user``      -- resolves who the end user is *on behalf of whom* the
  call is being made. The final authorization (data is scoped to the actor's
  madrasa, write ops allowed) is enforced in the view layer against Django's
  authenticated user, never delegated to the LLM.
"""
import logging

from django.conf import settings
from django.http import JsonResponse

from applications.accounts.models import User

logger = logging.getLogger(__name__)


def _token_matches(provided):
    expected = getattr(settings, "MEELAD_AI_SERVICE_TOKEN", None)
    if not expected:
        return False
    return provided and _constant_time_eq(provided, expected)


def _constant_time_eq(a, b):
    try:
        import hmac
    except ImportError:  # pragma: no cover
        return a == b
    return hmac.compare_digest(a, b)


def require_service(view):
    """Reject requests that do not carry the trusted service token.

    These endpoints are consumed only by the AI service using a shared-token
    header (never session cookies), so CSRF is not applicable: the wrapped view
    is marked csrf_exempt for Django's CSRF middleware. Authentication and
    authorization still apply on every call.
    """
    from django.views.decorators.csrf import csrf_exempt

    @csrf_exempt
    def wrapped(request, *args, **kwargs):
        token = request.headers.get("X-Meelad-AI-Token", "")
        if not _token_matches(token):
            logger.warning("Rejected AI API call with missing/invalid service token")
            return JsonResponse({"error": "Unauthorized"}, status=401)
        return view(request, *args, **kwargs)
    wrapped.__name__ = getattr(view, "__name__", "wrapped")
    return wrapped


def resolve_actor(request):
    """Resolve the actor user for an AI service request, if any.

    Returns the User instance or None. Views must still scope their queries to
    ``actor.madrasa``. If no actor is supplied the request may only access
    nothing (returns None) and views are expected to treat it as unauthorized.
    """
    actor_id = request.headers.get("X-Meelad-User-Id", "")
    if not actor_id:
        return None
    try:
        return User.objects.filter(id=int(actor_id)).first()
    except (TypeError, ValueError):
        return None