"""Keep-alive for the FastAPI AI service on Render's free tier.

Render free instances sleep after ~15 minutes without *inbound* traffic, and
Render's own health checks do not count as traffic. When the service is
asleep, the user's first chat message has to wait for a full cold boot and
often times out ("assistant not loading").

This middleware piggy-backs a cheap, throttled keep-alive GET to the AI
service's ``/api/ai/health`` endpoint onto normal site traffic: while the
Django site is receiving page views, the AI service is pinged at most once
per ``MEELAD_AI_KEEPALIVE_INTERVAL`` seconds and therefore stays warm.

The ping runs in a daemon thread and is fully fire-and-forget: it can never
slow down or fail a request. A failed ping is retried on the next request.
"""
import logging
import os
import threading

import requests

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache keys. The default LocMemCache is per-process, so on a multi-worker
# deployment each worker may ping once per interval - trivial for a health
# endpoint, and correct on Render free tier (single instance).
_OK_KEY = "meelad-ai-keepalive-ok"
_INFLIGHT_KEY = "meelad-ai-keepalive-inflight"

# Paths that never need to wake the AI service.
_SKIP_PREFIXES = ("/static/", "/media/", "/admin/jsi18n/", "/favicon")


def ping_ai_service(base_url):
    """GET the AI service health endpoint. Returns True if reachable."""
    try:
        url = base_url.rstrip("/") + "/api/ai/health"
        resp = requests.get(url, timeout=10)
        return resp.status_code < 500
    except Exception:  # noqa: BLE001 - keep-alive must never raise
        logger.debug("AI keep-alive ping failed", exc_info=True)
        return False


def _ping_and_mark(base_url, interval):
    try:
        if ping_ai_service(base_url):
            cache.set(_OK_KEY, True, timeout=interval)
    finally:
        # Always release the single-flight gate: on failure so the next
        # request retries, on success because the OK marker now throttles.
        cache.delete(_INFLIGHT_KEY)


def wake_ai_service_once():
    """Ping the AI service in the background unless recently confirmed alive.

    Used by the keep-alive middleware (site-traffic pings). Deduped through the
    cache so at most one ping is in flight and successes are remembered for the
    interval. (The old widget ``chat/wake/`` endpoint was removed: the pings it
    fired from the browser added noise without measurably reducing cold starts
    — register this middleware instead to piggy-back pings on page views.)
    """
    base = getattr(settings, "MEELAD_AI_SERVICE_BASE_URL", "")
    if not base:
        return
    interval = int(getattr(settings, "MEELAD_AI_KEEPALIVE_INTERVAL", 600))
    if interval <= 0 or cache.get(_OK_KEY):
        return
    # Atomic single-flight gate: only one ping per window. The key expires,
    # so a crashed/failed ping is retried by a later request.
    if not cache.add(_INFLIGHT_KEY, True, timeout=120):
        return
    threading.Thread(
        target=_ping_and_mark, args=(base, interval), daemon=True,
        name="meelad-ai-keepalive",
    ).start()


class AiServiceKeepAliveMiddleware:
    """Ping the AI service in the background on ordinary page views."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            self._maybe_ping(request)
        except Exception:  # noqa: BLE001 - scheduling must never raise
            logger.debug("AI keep-alive scheduling failed", exc_info=True)
        return self.get_response(request)

    def _maybe_ping(self, request):
        # Local dev runs the AI service manually; force with
        # MEELAD_AI_KEEPALIVE_FORCE=1 if you want to exercise this path.
        if getattr(settings, "DEBUG", False) and not os.getenv("MEELAD_AI_KEEPALIVE_FORCE"):
            return
        if request.method != "GET":
            return
        path = request.path_info or ""
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return
        base = getattr(settings, "MEELAD_AI_SERVICE_BASE_URL", "")
        if not base:
            return
        interval = int(getattr(settings, "MEELAD_AI_KEEPALIVE_INTERVAL", 600))
        if interval <= 0:
            return
        wake_ai_service_once()