# Meelad AI Assistant — Architecture

> **Note:** The AI service now lives in a **separate standalone repository**
> (previously `meelad-ai/` inside this repo) and is deployed independently
> (e.g. Render). Wiring: Django's `MEELAD_AI_SERVICE_BASE_URL` +
> `MEELAD_AI_SERVICE_TOKEN` point at the AI service; the AI service's
> `MEELAD_API_BASE_URL` + `MEELAD_SERVICE_TOKEN` point back at Django.

An AI-powered operations assistant added **on top of** the existing Meelad Fest
Django application. It is purely additive: no existing model, view, URL,
workflow, or business rule was changed.

```
Browser (existing templates + ai_chat.js widget)
      │  authenticated Django session (same login as the rest of the app)
      ▼
Django  ·  applications/aiassistant          ← system of record boundary
      │  POST /ai/chat/  (session auth, CSRF, rate limiting, audit log)
      │  server-to-service token: X-Meelad-AI-Token
      ▼
FastAPI  ·  meelad-ai/                       ← separate process/container
      │  POST /api/ai/chat
      ▼
LangGraph agent (plan → tools → plan → … → answer, MAX_AGENT_ITERATIONS cap)
      │            │
      │            └── search_meelad_knowledge → per-madrasa fest-rules RAG
      ▼
Domain tools (students, teams, programs, groups, results, venues, schedules)
      │  HTTP only — MeeladClient, user-scoped, timeouts + retries
      ▼
Django internal JSON APIs / aiassistant operations (Django re-validates everything)
      ▼
Existing business logic → PostgreSQL
```

## Hard boundaries

* The AI service **never** touches PostgreSQL, never imports Django models, and
  never sees SQL. All data flows through the Django HTTP boundary.
* The LLM never decides business facts: scores, rankings, conflict detection,
  availability, eligibility and authorization are computed by Django
  (deterministic Python). The LLM only understands, coordinates and explains.
* The frontend never sees an LLM API key — it talks to Django only.

## Components

| Path | Purpose |
|---|---|
| `applications/aiassistant/` | Django side: session-auth endpoint, internal APIs for the AI service, write operations with validation + audit log, `AIOperationAuditLog` model |
| `meelad-ai/app/api/` | FastAPI routes + Pydantic schemas (`POST /api/ai/chat`, `GET /api/ai/health`) |
| `meelad-ai/app/agent/` | LangGraph graph, typed state, nodes (decide/execute), conversation memory, prompts |
| `meelad-ai/app/tools/` | Tool catalogue; each tool wraps one `MeeladClient` call |
| `meelad-ai/app/clients/meelad_client.py` | HTTP client to Django: auth headers, timeouts, exponential-backoff retries, structured errors |
| `meelad-ai/app/llm/provider.py` | Provider abstraction (`get_planner()`); `LLM_PROVIDER=mock`, `deepseek` (paid primary, `deepseek-flash`) or `openai` (+ any OpenAI-compatible base URL). The single DeepSeek planner is wrapped in a `FallbackPlanner` so an exhausted account (401/402/429) degrades to a graceful chat message. The former Gemini primary and local Ollama fallback are commented out (disabled Sept 2026) |
| `meelad-ai/app/rag/` | RAG pipeline (chunker, embeddings, vectorstore, retrievers). Per-madrasa fest-rules RAG is on by default (`RAG_RULES_ENABLED`): the index is built from the rules PDF each madrasa uploads in Django (text extracted at upload, served via `/ai/api/fest-rules/`, re-indexed automatically on re-upload). The optional local-docs corpus stays behind `RAG_ENABLED=true` |
| `meelad-ai/app/security/permissions.py` | Tool-level permission gate (defense in depth; Django is authoritative) |
| `meelad-ai/app/monitoring/` | Structured logging (conversation_id, user_id) and latency/call metrics |

## Agent workflow

1. Request arrives with `conversation_id`; prior messages + any **pending
   action** are restored from the conversation store.
2. If a write is awaiting approval, the decision node handles confirmation:
   * clear *yes/confirm/proceed* → execute the stored write calls (with
     idempotency keys);
   * *no/cancel* → drop the pending action, change nothing;
   * ambiguous (“okay”, “fine”) → **re-ask**; never executes a write;
   * anything else → re-ask.
3. Otherwise the planner routes the message to read tools (rankings, students,
   programs, participants, results, venues, schedule, conflicts, knowledge…),
   possibly across several rounds.
4. Scheduling proposals are computed **by Django** (`suggest_schedule` ->
   `suggest_conflict_free_schedule`, aligned with `check_schedule_conflict`),
   shown to the user, and only applied after explicit confirmation — then
   re-validated by Django on the write path.
5. Every executed tool call is recorded with a status and returned as
   `tool_calls` in the response. Tool failures become honest “could not
   retrieve…” answers — the agent never invents data or success.
6. The loop is capped by `MAX_AGENT_ITERATIONS` (default 6); on exhaustion the
   agent stops gracefully.

## Security

* Browser → Django: existing session auth + CSRF; the AI endpoint requires a
  logged-in user.
* Django → AI service: `X-Meelad-AI-Token` shared secret (`MEELAD_SERVICE_TOKEN`
  / `MEELAD_AI_SERVICE_TOKEN`), plus `X-Meelad-User-Id` identifying the actor.
* AI service → Django: every client call is bound to that user id; Django
  performs final authorization on every read and write.
* Write operations additionally require: explicit user confirmation, Django
  validation, idempotency key, and an audit-log row (user, timestamp, operation,
  target, requested action, approval, result).
* Tool arguments are fixed schemas; model output is treated as untrusted; no
  SQL/shell/eval anywhere; unknown tools are rejected; loops are capped.

## Configuration

See `meelad-ai/.env.example`. Key variables: `LLM_PROVIDER`, `LLM_API_KEY`,
`LLM_MODEL`, `LLM_BASE_URL`, `MEELAD_API_BASE_URL`, `MEELAD_SERVICE_TOKEN`,
`AI_SERVICE_HOST/PORT`, `MAX_AGENT_ITERATIONS`, `RAG_ENABLED`,
`VECTOR_DATABASE_URL`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`,
`LOG_LEVEL`. Django side: `MEELAD_AI_SERVICE_TOKEN`, `MEELAD_AI_BASE_URL`,
`MEELAD_AI_TIMEOUT_SECONDS`.

Secrets live only in the environment; `.env` is git-ignored.

## Running

```bash
# Django (existing app)
python manage.py migrate            # adds only the aiassistant audit-log table
python manage.py runserver

# AI service
cd meelad-ai
pip install -r requirements.txt
cp .env.example .env               # set MEELAD_SERVICE_TOKEN etc.
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

`LLM_PROVIDER=mock` runs a deterministic built-in planner — the full flow
(read tools, proposals, confirmation, writes) works without any LLM account,
which is also how the test-suite exercises the graph. The mock planner
recognises the common intents so it is genuinely useful even without an LLM
key: greetings, teams & rankings, students (lists, counts, programs, results),
programs (list, count, status, participants, results), venues (list/count,
availability), schedule (today, unscheduled, conflicts, remaining), statistics
/ fest overview, head-to-head team comparisons ("Red vs Blue), and the uploaded
fest-rules RAG. Anything else gets an honest "I'm not sure" reply that lists the
supported topics. `LLM_PROVIDER=deepseek` (the current primary) uses DeepSeek
(`deepseek-flash`, OpenAI-compatible `/chat/completions`); `LLM_PROVIDER=openai`
uses OpenAI or any OpenAI-compatible endpoint. The legacy `LLM_PROVIDER=gemini`
value is served by DeepSeek (the Gemini planner is commented out, disabled Sept
2026).

### DeepSeek primary (Gemini & Ollama disabled)

DeepSeek is the paid primary provider: `DEEPSEEK_API_KEY`,
`DEEPSEEK_MODEL=deepseek-flash`. Thinking mode is disabled by default
(`DEEPSEEK_THINKING=false` — deepseek-flash otherwise reasons at effort
"high" by default, which would add latency to every agent round). Requests use
the OpenAI-compatible `/chat/completions` endpoint with JSON output mode
(`response_format=json_object` + the word "json" in the prompt) so the decision
parses reliably.

If the DeepSeek account is exhausted (401 expired key, 402 no balance, 429
rate limit), the wrapped `FallbackPlanner` returns a clear chat message naming
the providers instead of a stack trace. Ordinary errors (invalid input,
config, internal) are not masked.

The old chain legs are disabled (commented out in `meelad-ai/app/llm/
provider.py`, Sept 2026): the Google Gemini primary (`google-genai` SDK, quota
probe on every call) because the platform now pays for DeepSeek, and the local
Ollama fallback because Render containers have no Ollama server. Both can be
re-enabled by uncommenting the marked blocks.

Logs identify the provider that answered (`LLM provider: DeepSeek`).

## Testing

* `meelad-ai/tests/` — agent graph, tool execution, confirmation/rejection,
  unauthorized writes, backend failures, iteration cap (pytest, FakeClient).
* `applications/aiassistant/tests.py` — Django endpoint auth, permission
  scoping, write validation, idempotency, audit logging (Django test runner).
* Full-suite note: two pre-existing failures in `applications.program.tests`
  (`SaveGeneralPrizeMadrasaScopingTests`, `ResultPosterPDFTests`) exist on the
  base commit and are unrelated to the AI feature.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `401 Unauthorized` from `/api/ai/chat` | Missing/mismatched service token between Django and the AI service |
| "I couldn't retrieve … from the backend" | Django unreachable/errored — check Django logs; the agent deliberately does not guess |
| Health OK but every answer is a failure | `MEELAD_API_BASE_URL` wrong, or user-scoped endpoint returned 403 |
| Widget shows "unavailable" | AI service down — start uvicorn; Django endpoint degrades gracefully |
| Duplicate schedule attempts | Idempotency keys + Django-side conflict validation reject repeats |

