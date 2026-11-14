# Meelad AI Tools Reference

Every tool calls Django through `MeeladClient` over HTTP — never the database.
Results come from Django's business logic; the LLM only formats them.

Common behaviour for all tools:

* **Failure** — never raises to the LLM; returns a structured error that the
  agent turns into an honest “could not retrieve …” answer.
* **Authorization** — the acting user id travels with every request; Django
  performs the authoritative permission check. The agent adds a tool-level
  gate (`app/security/permissions.py`) as defense in depth.
* **Timeouts/retries** — connection/request timeouts plus exponential-backoff
  retries for transient reads; write calls are never retried blindly and carry
  an idempotency key.

## Read tools

| Tool | Purpose | Inputs | Example request |
|---|---|---|---|
| `get_team_rankings` | Current team standings (authoritative Django scoring) | — | “Who is leading?” |
| `list_teams` | All teams | — | “Show the teams.” |
| `get_team` | One team by id | `team_id` (int, required) | “Show team 3.” |
| `search_students` | Find students by name/code | `query` (str), `limit` (int) | “Find student Ahmed.” |
| `get_student` | One student by id | `student_id` (int, required) | — |
| `get_student_programs` | Programs a student participates in | `student_id` (int, required) | “Show Ahmed's programs.” |
| `get_student_results` | Published prizes/results of a student | `student_id` (int, required) | “What did Ahmed win?” |
| `search_programs` | Programs by title / group / general filters | `query` (str), `is_group` (bool), `is_general` (bool) | “Find the Arabic speech program.” |
| `get_program` | One program by id | `program_id` (int, required) | — |
| `get_program_participants` | Students in a program | `program_id` (int, required) | “Who is in program X?” |
| `get_program_result` | Published result/winners of a program | `program_id` (int, required) | “Who won first prize in Arabic speech?” |
| `get_program_status` | Scheduled/result status of a program | `program_id` (int, required) | “Is program X done?” |
| `get_unscheduled_programs` | Programs without venue/time | — | “What still has no slot?” |
| `list_group_programs` | All group programs | — | “Show group programs.” |
| `get_groups_for_program` | Groups (with members) of a group program | `program_id` (int, required) | “Show the groups for X.” |
| `get_winners` | Winners of a program (normalized view) | `program_id` (int, required) | “Show all first-prize winners.” |
| `get_top_students` | Top of the standings (team-based, per existing rules) | `limit` (int) | “Show the top 10.” |
| `get_venues` | All venues | — | “List venues.” |
| `get_venue_schedule` | Programs booked at a venue | `venue_id` (int, required) | “What's on at Hall A?” |
| `check_venue_availability` | Deterministic availability check at a datetime | `venue_id` (int), `at` (ISO datetime) | “Is Hall A available at 3 PM?” |
| `get_schedule` | All scheduled programs | — | “What's scheduled today?” |
| `list_fest_days` | Active fest days (id, name, date) — scheduling unit | — | needed before `create_schedule` |
| `find_schedule_conflicts` | Deterministic conflict detection (Django) | — | “Find scheduling conflicts.” |
| `suggest_schedule` | Proposed schedule for a date incl. fest_day id (Django algorithm) | `date` (ISO date) | “Schedule the remaining programs tomorrow.” |
| `search_meelad_knowledge` | RAG search over THIS madrasa's uploaded fest rules PDF (upload it in the profile modal → Fest Rules; auto re-indexed on re-upload) | `query` (str, required) | “How is a tie handled per the fest rules?” |

## Write tools

Write tools are **only** executed after the agent shows a proposal and the user
gives an explicit, unambiguous confirmation (“yes” / “confirm” / “proceed”).
Ambiguous replies (“okay”) re-prompt instead of executing. On execution each
call carries an `idempotency_key`; Django re-validates everything and refuses
conflicts/invalid data; every attempt is recorded in
`AIOperationAuditLog` (user, timestamp, operation, target, requested action,
approval, result).

| Tool | Purpose | Inputs | Django-side guarantees |
|---|---|---|---|
| `create_schedule` | Place a program on a fest day + start time (FestDay + ScheduleEntry, like `add_schedule`) | `program_id` (int), `fest_day` (int, required), `start_time` (HH:MM, required), `duration_minutes` (int, default 60), `venue_id` (int), `notes` (str), `idempotency_key` (str) | Program/venue/fest-day existence, madrasa scoping, already-scheduled guard, `check_schedule_conflicts` (participant + venue overlap, returned as warnings like the board), idempotency, `_resync_program`, audit log |
| `update_schedule` | Move/reschedule a program (same endpoint semantics — fest_day + start_time) | same as `create_schedule` | same as `create_schedule` |
| `create_group` | Create a group for a group program | `program_id` (int), `participant_ids` (array of ints, required), `idempotency_key` (str) | Program is a group program, participant eligibility, duplicates, minimum size, existing membership; name follows the existing “<member> & team” convention; scores remain team-owned per existing rules |
| `remove_group_participant` | Remove a participant from a group program | `program_id`, `participant_id` (int, required), `idempotency_key` (str) | Membership check, audit log; existing group flow untouched |

## Deliberate omissions

* No tool generates or runs SQL, code, or shell commands.
* No tool bypasses Django validation “for speed”.
* No LLM-side score/rank/conflict calculation — those are Django's alone.
* RAG is optional (`RAG_ENABLED=false` by default); the agent answers
  application-data questions without it.

