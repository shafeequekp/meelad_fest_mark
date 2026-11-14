# Meelad Fest — Django + FastAPI AI Assistant

A full-featured student cultural fest management platform built with **Django 4.2**
and **FastAPI**. The Django backend is the system of record: it owns all
business data, authorization, scheduling decisions, and scoring. On top of it
sits a context-aware **AI assistant** served by a separate FastAPI service
(deployed independently on Render) that only formats answers using Django's
deterministic business logic.

![Framework](https://img.shields.io/badge/Django-4.2-green)
![Backend](https://img.shields.io/badge/FastAPI-0.104-blue)
![Database](https://img.shields.io/badge/PostgreSQL-Neon-lightgrey)
![Deploy](https://img.shields.io/badge/Render-deployed-brightgreen)
![License](https://img.shields.io/badge/License-Apache%202.0-blue)

> Fork of the original Meelad Fest project. The AI assistant code lives in a
> separate repository (`meelad-ai/`) and is wired into this Django app via
> HTTP only.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Getting Started (local development)](#getting-started-local-development)
- [Running the AI assistant locally](#running-the-ai-assistant-locally)
- [Deployment (Render + Neon Postgres)](#deployment-render--neon-postgres)
- [Project layout](#project-layout)
- [Configuration reference](#configuration-reference)
- [Admin & superuser bootstrap](#admin--superuser-bootstrap)
- [API boundary (Django <-> FastAPI)](#api-boundary-django--fastapi)
- [AI assistant tools reference](#ai-assistant-tools-reference)
- [Database & media storage](#database--media-storage)
- [Frontend build (Tailwind CSS)](#frontend-build-tailwind-css)
- [Running tests](#running-tests)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Authors](#authors)

---

## Features

### Fest management
- Multi-madrasa accounts with **Boys/Girls/Both sections** support.
- Program catalog (individual, group, and general programs) with scheduling, venues, judges, criteria, and evaluation.
- Fest rules PDF upload (text extracted for the AI knowledge base).
- Registration links (student, parent, program, and parent links) with usage tracking.
- Student/team/prize/scoreboard, results publishing, and statistics.

### AI assistant
- A dedicated FastAPI + LangGraph agent (separate repo) that answers questions
  about teams, students, programs, venues, schedules, results, and the uploaded
  fest rules.
- **RAG** over each madrasa's uploaded fest-rules PDF.
- Service-to-service auth via shared token; Django re-validates every write.
- Django <-> FastAPI integration boundary exposes scoped internal JSON APIs.

### Deployment
- Render Blueprint with Neon Postgres (free tier), WhiteNoise for static files,
  Cloudinary for media, and a background keep-alive ping so the free-tier AI
  service stays warm.

---

## Architecture

```text
Browser
  │  authenticated Django session (same login as the rest of the app)
  ▼
Django  ·  applications/aiassistant  <- system of record boundary
  │  POST /ai/chat/                 (session auth, CSRF, audit log)
  │  X-Meelad-AI-Token (service-to-service)
  ▼
FastAPI · meelad-ai/                <- separate process/container
  │  POST /api/ai/chat
  ▼
LangGraph agent (plan -> tools -> plan -> ...)
  │            │
  │            └── search_meelad_knowledge -> per-madrasa fest-rules RAG
  ▼
Domain tools (students, teams, programs, groups, results, venues, schedules)
  │  HTTP only — MeeladClient, user-scoped, timeouts + retries
  ▼
Django internal JSON APIs / aiassistant operations (Django re-validates)
  ▼
Existing business logic -> PostgreSQL
```

### Hard boundaries
- The AI service **never** touches PostgreSQL, never imports Django models, and
  never sees SQL. All data flows through the Django HTTP boundary.
- The LLM never decides business facts. Scores, rankings, conflict detection,
  availability, eligibility, and authorization are computed by Django.
- The frontend never sees an LLM API key — it talks to Django only.

---

## Prerequisites

- Python **3.10** (see `runtime.txt`)
- A virtual environment
- Node 18+ (only if you want to rebuild the Tailwind CSS bundle)

Optional but recommended:
- PostgreSQL + Neon (for local development mirror of production)
- Cloudinary account (for media storage in production)

---

## Getting Started (local development)

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env example and fill in secrets
cp .env.example .env
# edit .env: DATABASE_URL, SECRET_KEY, MEELAD_* keys, etc.

# 4. Run migrations
python manage.py migrate

# 5. Create the initial superuser (bootstrap command)
python manage.py bootstrap_superuser

# 6. Run the dev server
python manage.py runserver

# 7. (optional) Run the AI service locally
cd meelad-ai
cp .env.example .env
# set MEELAD_SERVICE_TOKEN etc.
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

The dev server is at `http://127.0.0.1:8000`. The Django app auto-loads a root
`.env` file (`meelad/settings.py`), and existing environment variables always
win over `.env`, so on Render the dashboard values take precedence.

---

## Running the AI assistant locally

```bash
# from the AI service repo (meelad-ai/)
pip install -r requirements.txt
cp .env.example .env
# set: MEELAD_SERVICE_TOKEN, DEEPSEEK_API_KEY, LLM_PROVIDER=deepseek or mock
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

The Django side must point at this local service via these environment
variables (see [Configuration reference](#configuration-reference)):

```bash
MEELAD_AI_SERVICE_BASE_URL=http://127.0.0.1:8100
MEELAD_AI_SERVICE_TOKEN=<same token as MEELAD_SERVICE_TOKEN in the AI service>
MEELAD_AI_CHAT_TIMEOUT=110
```

> `LLM_PROVIDER=mock` runs a deterministic built-in planner. The full flow
> (read tools, proposals, confirmation, writes) works without any LLM account,
> which is how the test suite exercises the graph.

---

## Deployment (Render + Neon Postgres)

The project is deployable to Render via the included `render.yaml` blueprint.

```bash
# On Render:
# 1. New -> Blueprint -> point at this repo
# 2. Set env vars in the dashboard:
#    - DATABASE_URL          (Neon POOLED connection string)
#    - SECRET_KEY            (generate)
#    - MEELAD_ENV=production
#    - DEBUG=0
#    - ALLOWED_HOSTS=.onrender.com
#    - MEELAD_AI_SERVICE_*   (must match the AI service)
#    - DJANGO_SUPERUSER_*    (initial superuser)
```

The build command automatically:
1. Installs dependencies
2. Collects static files (`collectstatic --noinput`)
3. Runs migrations (`migrate --noinput`)
4. Bootstraps the initial superuser (`bootstrap_superuser`)

The start command runs Gunicorn:

```text
web: gunicorn meelad.wsgi:application --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
```

---

## Project layout

```text
meelad_fest_mark/
├── manage.py                     # Django entrypoint
├── requirements.txt              # Python dependencies (runtime + production)
├── runtime.txt                   # Python 3.10.12
├── Procfile                      # Render web process
├── render.yaml                   # Render blueprint
├── .env                          # Local secrets (gitignored)
├── .env.example                  # Env template for new clones
├── .gitignore
├── AI_ARCHITECTURE.md            # AI boundary + agent workflow (this repo)
├── AI_TOOLS.md                   # AI tool catalogue reference
├── db.sqlite3                    # Local dev SQLite (gitignored)
├── media/                        # Media files (gitignored)
├── staticfiles/                  # Collected frontend/static assets
├── tailwind/                     # Tailwind source (app.css + config)
├── templates/                    # Base + app templates
├── applications/                 # Django apps
│   ├── accounts/                 # Users, madrasa, auth, profile, rules PDF
│   ├── aiassistant/              # Session-auth endpoints, service APIs, ops, audit log
│   ├── program/                  # Programs, venues, judges, results, links
│   ├── schedule/                 # FestDay, ScheduleEntry, scheduling
│   ├── scoreboard/               # Teams, scoring, rankings
│   └── subscription/             # Subscription handling
├── meelad/                       # Django project settings/urls
│   ├── settings.py               # Core config + environment selection
│   ├── production.py             # Render/Neon settings
│   ├── local.py                  # Developer machine settings (gitignored)
│   └── urls.py
├── utils/                        # Shared helpers (e.g. DateBaseModel)
└── templates/                    # App-level templates
```

---

## Configuration reference

All environment variables are read from the `.env` file (local) or the Render
dashboard (production). Secrets **never** live in code.

### Django core
| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | (dev only) | Django secret key. Required in production. |
| `DEBUG` | `0` | Debug mode. |
| `ALLOWED_HOSTS` | `.onrender.com` | Comma-separated hostnames. |
| `CSRF_TRUSTED_ORIGINS` | (none) | Trusted origins for CSRF (https POSTs). |

### Database (Neon Postgres / Render)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Neon POOLED connection string (e.g. `postgresql://...@...-pooler...`). |

### AI assistant integration
| Variable | Default | Purpose |
|---|---|---|
| `MEELAD_AI_SERVICE_BASE_URL` | `http://127.0.0.1:8100` | FastAPI AI service base URL. |
| `MEELAD_AI_SERVICE_TOKEN` | `dev-ai-service-token` | Shared secret with the AI service. Must equal `MEELAD_SERVICE_TOKEN` in the AI service. |
| `MEELAD_AI_CHAT_TIMEOUT` | `110` | Hard wall-clock timeout (seconds) for the Django -> AI chat call. |
| `MEELAD_AI_KEEPALIVE_INTERVAL` | `600` | Seconds between background keep-alive pings (Render free tier). |

### Superuser bootstrap
| Variable | Purpose |
|---|---|
| `DJANGO_SUPERUSER_EMAIL` | Initial superuser email. |
| `DJANGO_SUPERUSER_PASSWORD` | Initial superuser password. |
| `BOOTSTRAP_SUPERUSER_RESET` | `1` to also reset an existing superuser's password on deploy. |

### (Optional) Cashfree payments / other
| Variable | Purpose |
|---|---|
| `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `CASHFREE_API_BASE`, `CASHFREE_WEBHOOK_SECRET` | Cashfree payment integration (prod/test). |

---

## Admin & superuser bootstrap

The project ships a management command `bootstrap_superuser` that creates the
initial superuser. It is run automatically during the Render build.

```bash
# Dry run / see what it does
python manage.py bootstrap_superuser --help
```

You can also create a superuser interactively:

```bash
python manage.py createsuperuser
```

> The custom user model is `accounts.User` (email/phone-based). Your
> `Superuser` account therefore requires an **email or phone number**
> (see `applications/accounts/models.py`).

---

## API boundary (Django <-> FastAPI)

Django exposes two kinds of internal JSON APIs for the AI service:

1. **Read tools** — read-only endpoints (e.g. `/ai/api/teams/`, `/ai/api/students/search/`,
   `/ai/api/fest-rules/`, `/ai/api/schedules/suggest/`). Scoped to the acting
   user's madrasa and serialized with only whitelisted fields (no leaks).
2. **Write operations** — service-token-authenticated endpoints with actor
   resolution and idempotency keys (e.g. `/ai/api/operations/schedule/`,
   `/ai/api/operations/groups/`). Django re-validates everything and refuses
   conflicts/invalid writes.

Entropy:
- **Session auth** for the browser chat widget (`/ai/chat/`, CSRF-protected).
- **Service token** (`X-Meelad-AI-Token`) for the FastAPI AI service.

The AI service consumes these endpoints via `MeeladClient` (HTTP only). It
never imports Django models.

---

## AI assistant tools reference

### Read tools
| Tool | Purpose |
|---|---|
| `get_team_rankings` | Current team standings (authoritative Django scoring). |
| `list_teams` | All teams. |
| `get_team` | One team by id. |
| `search_students` | Find students by name/code. |
| `get_student` | One student by id. |
| `get_student_programs` | Programs a student participates in. |
| `get_student_results` | Published prizes/results of a student. |
| `search_programs` | Programs by title / group / general filters. |
| `get_program` | One program by id. |
| `get_program_participants` | Students in a program. |
| `get_program_result` | Published result/winners of a program. |
| `get_program_status` | Scheduled/result status of a program. |
| `get_unscheduled_programs` | Programs without venue/time. |
| `list_group_programs` | All group programs. |
| `get_groups_for_program` | Groups (with members) of a group program. |
| `get_winners` | Winners of a program (normalized view). |
| `get_top_students` | Top of the standings. |
| `get_venues` | All venues. |
| `get_venue_schedule` | Programs booked at a venue. |
| `check_venue_availability` | Deterministic availability check at a datetime. |
| `get_schedule` | All scheduled programs. |
| `list_fest_days` | Active fest days (scheduling unit). |
| `find_schedule_conflicts` | Deterministic conflict detection. |
| `suggest_schedule` | Proposed schedule for a date. |
| `search_meelad_knowledge` | RAG search over this madrasa's uploaded fest rules PDF. |

### Write tools
Write tools are executed **only** after the agent shows a proposal and the user
gives an explicit, unambiguous confirmation. Each write call carries an
`idempotency_key`; Django re-validates and rejects duplicates/conflicts.

---

## Database & media storage

| Asset | Storage | Notes |
|---|---|---|
| Database | SQLite (local dev) / Neon Postgres (Render) | `DATABASE_URL` in production. |
| Media (uploads) | Cloudinary | `STORAGES['default']` = `cloudinary_storage...`. |
| Static files | WhiteNoise | `STORAGES['staticfiles']` = `CompressedStaticFilesStorage`. |

`*.db`, `media/*`, `staticfiles/` are gitignored.

---

## Frontend build (Tailwind CSS)

The site uses Tailwind CSS v3.4 built with the Tailwind CLI.

```bash
# Install dev dependency
npm install

# Build the CSS bundle into staticfiles/
npm run build:css
```

`package.json` is the source of truth for the CSS build (`node_modules/` is
gitignored, but `package.json` / `package-lock.json` are kept).

---

## Running tests

```bash
# Run Django tests
python manage.py test

# Run pytest (project-level)
pytest
```

> Note: two pre-existing failures in `applications.program.tests`
> (`SaveGeneralPrizeMadrasaScopingTests`, `ResultPosterPDFTests`) exist on the
> base commit and are unrelated to the AI feature.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `401 Unauthorized` from `/api/ai/chat` | Missing/mismatched `MEELAD_AI_SERVICE_TOKEN` between Django and the AI service. |
| Chat requests hang | `MEELAD_AI_CHAT_TIMEOUT` too high for the gunicorn `--timeout`; keep it below 120 on Render. |
| Widget shows "unavailable" | AI service down — start uvicorn; Django endpoint degrades gracefully. |
| Render free tier service sleeps | Confirmed keep-alive middleware pings the AI service in the background while the site gets traffic. |
| Duplicate schedule writes | Idempotency keys + Django conflict validation reject repeats. |
| Scanned PDF rules | `search_meelad_knowledge` needs a PDF with a text layer; scanned images have no extractable text. |

---

## License

This project is licensed under the Apache License 2.0.
See the LICENSE file for details.

Copyright 2026 Muhammed Shafeek.

---

## Authors

- **Muhammed Shafeek** — full project
- **AI assistant** — separate `meelad-ai/` repository (FastAPI + LangGraph), wired via HTTP
