"""
Production settings for the Meelad Django backend.

Deployed on Render with a Neon Postgres (free tier) database.

This module is imported (via `from .production import *`) by meelad/settings.py
when either:
  - MEELAD_ENV=production, or
  - meelad/local.py is absent (local.py is gitignored and only exists on
    developer machines).

Everything deployment-specific is read from environment variables, so the same
code deploys anywhere without edits.
"""
import os

import dj_database_url

# --- Core Django security ----------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is required in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

DEBUG = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")

# Comma-separated hostnames, e.g. "meelad-web.onrender.com,.onrender.com"
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", ".onrender.com").split(",") if h.strip()
]

# --- Neon Postgres ------------------------------------------------------------
# Set DATABASE_URL to the Neon POOLED connection string, e.g.
#   postgresql://USER:PASSWORD@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required in production "
        "(Neon Postgres connection string)."
    )

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=0,    # Neon's PgBouncer (transaction pooling) prefers no
                           # persistent per-process connections
        ssl_require=True,  # Neon requires TLS
    )
}

# --- Render reverse proxy / TLS ----------------------------------------------
# Render terminates TLS at its proxy; trust the forwarded protocol header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "0").lower() in ("1", "true", "yes")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))

# Needed for admin/login POSTs on https origins (comma-separated list)
_csrf_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# --- Static files via WhiteNoise (no external storage needed) -----------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Keeps the FastAPI AI service awake on Render's free tier (see module
    # docstring). Fire-and-forget background ping, throttled via the cache.
    'applications.aiassistant.middleware.AiServiceKeepAliveMiddleware',
]

# Storage is configured once in meelad/settings.py (Cloudinary for media,
# WhiteNoise for staticfiles) and applies to production as well.

