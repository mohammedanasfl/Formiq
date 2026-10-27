# Formiq

Adaptive AI fitness coach. A FastAPI + PostgreSQL backend with an AI coach (LangGraph + Gemini)
that reads the user's data and proposes workouts, but never writes: only the user's approval saves
a plan. The React Native app (`frontend/`) comes later. Repo: `mohammedanasfl/Formiq`.

## Working rules

- Work on branch `dev`. `main` only changes through PRs from `dev`.
- **Commit and push only when the user says "commit it"** ("push it" means commit and push to
  `dev`). Never merge PRs or enable auto-merge unless asked.
- **Never modify `.env`, never put an API key in it, never commit secrets.** The user adds
  `GEMINI_API_KEY`, `AUTH_JWT_SECRET` (32+ bytes) and the Langfuse keys themselves.
- **Never modify an existing Alembic migration.** Schema changes get a new migration.
- Report deferred or out-of-scope issues to the user; don't silently fix them.
- Work phase by phase from the user's brief, against its Definition of Done.

## Architecture rules

- Routes do HTTP only. Services own the rules and transactions. Repositories only add, flush and
  query.
- Another user's resource returns 404, never 403: its existence is never revealed.
- Identity comes only from the JWT (`get_current_user`). The client never chooses the user.
- Agent code (`app/agent`, `app/ai`) never touches the DB. It reaches data only through
  `app/tools`, which call the services.
- Before changing the agent, tools, approvals, observability, `coach_service.py` or auth, read
  `docs/agent-production-contract.md`. Its critical limits are pinned in
  `backend/tests/unit/test_agent_contract.py`; changing a guarantee is a deliberate decision, never
  a test to relax.

## Commands (run from `backend/`)

```bash
docker compose up -d                          # PostgreSQL on localhost:5432 (from repo root)
source .venv/bin/activate
alembic upgrade head                          # apply migrations
pytest -q                                     # all tests; integration tests need Postgres
python -m app.cli set-password USER_ID        # set a dev user's password
python -m app.cli import-exercises [--dry-run] # import/refresh the free-exercise-db catalog
.venv/bin/python -m pytest ../playground/tests  # playground tests (also: node --test playground/tests/)
.venv/bin/python ../playground/server.py      # playground at http://localhost:2001/playground/
```

Tests use the disposable `formiq_pytest` database (created and marked by the tests on the server
`TEST_DATABASE_URL` names; they refuse any other database), whose schema comes from Alembic
migrations only. `formiq_test` is the QA database: a test run never touches it (Phase 2.7; see
`backend/README.md`). The playground always runs on port 2001. `tests/conftest.py` turns the application's Langfuse tracer
off for every test, whatever `backend/.env` enables; tracing tests build their own tracer.
Run the playground tests in their own pytest run: in the same session as backend tests that
start the app, they error with "Cannot add middleware after an application has started".

## History

- **Phase 1** (1.1 to 1.6): repo foundation, FastAPI app with health endpoint, Pydantic settings,
  PostgreSQL + SQLAlchemy, Alembic, pytest.
- **Phase 2** (2.1 to 2.5): users and user profiles (models, schemas, repositories, services, API),
  a dedicated `formiq_test` database. Merged to `main` (PR #3).
- **Phase 3**: exercise catalog (3.1), workout plans (3.2), workout sessions and sets (3.3).
- **Phase 4: the AI coach** (`POST /coach/message`), read-only:
  - 4.1 Gemini provider and LangGraph runtime; 4.2 read-only tools; 4.3 state and context;
    4.4 decision policy (every answer about the user's data needs evidence from this turn);
    4.5 deterministic safety guardrails; 4.6 context compaction; 4.7 prompt-injection boundary;
    4.8 Langfuse tracing (never authoritative); 4.9 to 4.10 evaluation and reliability tests;
    4.11 write-approval boundary (`app/approvals`, dormant); 4.12 the production contract doc.
  - Then: a local playground (`playground/`), discovery of the current plan and last workout,
    4.13 JWT authentication (`POST /auth/login`, `user_credentials` table, Argon2id hashes).
  - Cleanup (`9e7242f`): the evaluation framework was replaced by scenario tests, the contract cut
    to its critical guarantees, the tests consolidated. Merged to `main` (PR #4, 2026-10-08).
- **Phase 5** (`cf47def`): "what should I do today?" from the profile, current plan and last
  workout; the `propose_workout_plan` tool; `POST /coach/proposals/{id}/approve` saves the exact
  proposal shown (its binding), once.
- **Phase 6** (`2ef15d3`): a user's workout sessions start one at a time (user row lock).
- **Imported catalog** (`5ee929a`): plan sections (warm-up, main, cool-down); free-exercise-db
  imported with `import-exercises`; proposals kept in PostgreSQL (`workout_plan_proposals`).
- **Complete workouts and observability** (`7bb3706`, `288f878`): catalog equipment corrections
  and duplicates (`app/catalog/classification.py`); completeness judged in code
  (`app/tools/completeness.py`), with `coverage` in the proposal response; stricter reply checks
  (no claimed approvals or invented proposals); searches superseded by an accepted proposal;
  opt-in `LANGFUSE_CAPTURE_CONTENT` (development and test only); tests never trace.
- **Saved workout lifecycle** (`48c9fe7`): saved plans carry each exercise's catalog name,
  description and instructions (`exercise`); end-to-end lifecycle tests; the playground shows
  coverage and reopens saved plans.
- **Phase 7: nutrition and recovery** (2026-10-17, branch `phase-7-nutrition-recovery`, not yet
  merged to `dev`): `POST
  /users/{user_id}/workout-sessions/{session_id}/recovery-summary` summarises one COMPLETED
  workout: protein, carbohydrate, hydration, recovery for the muscles trained, food examples. Rules
  in `app/guidance/` (pure), read-only `app/services/recovery_summary_service.py`, route
  `app/api/routes/recovery_summaries.py`. No migration, no coach tool, no LangGraph change, no
  language model. Rules, sources, safety order and what is unverified: `docs/nutrition-recovery.md`.

## Current state (2026-10-14)

- `dev` is at `48c9fe7`, pushed: 7 commits ahead of `main` (Phase 5 onwards), no PR open.
- Deploying `dev` needs `alembic upgrade head`; `AUTH_JWT_SECRET` and `GEMINI_API_KEY` set; a
  password per user via the CLI; and `python -m app.cli import-exercises`, run again whenever
  `app/catalog/` changes (the catalog corrections reach a database only through it; it is safe to
  re-run, and `--dry-run` shows what it would change). The dev database is current.
- Not done yet: timed sets (a set needs `reps`, so a timed exercise is logged without sets; needs
  a migration); exercise names in session history; five imported main exercises have no
  instructions or description.

## Coach proposals: approve, reject, pending (Phase 2.1 to 2.3, on `phase-7-nutrition-recovery`)

- `POST /coach/proposals/{id}/approve`: 201 the first time, 200 with the same plan when sent again
  (idempotent; 409 if the saved plan changed since). `POST /coach/proposals/{id}/reject`: 204, status
  `REJECTED` (no migration), 409 for an approved one; rejecting again is 204 only while the row is
  kept: an expired proposal's row is cleared when its user next gets a new one, and then a reject or
  approve is a 404. `GET /coach/proposals/pending` lists what can still be approved.
- One rule for "awaiting approval" (`PlanProposalService.approvable`), used by that list and by what the
  coach reads; a request that names a plan (`workout_plan_id`) reads only proposals that revise it.
  A revision keeps its plan's day; another day only when the user named one (`app/tools/schedule.py`).
  Details and limits: `docs/agent-production-contract.md` sections 8 and 10.

- Phase 2.5 (on the same branch, uncommitted): a day move is a revision on its own (an ADJUST is
  unchanged only when its day is the plan's too); a proposal carries `weight_kg` per exercise, a
  revision keeps its plan's weights, and the model sets one only when the user gave it
  (`app/tools/weights.py`); the reply check is held to the records (`Lifecycle` in
  `app/agent/trust.py`): nothing is said saved, applied or updated without them, "no proposal is
  waiting" is said only when none is, and a refused proposal presents nothing. Details and limits:
  `docs/agent-production-contract.md` sections 5, 8 and 10. Scripted tests only; live Gemini not run.

- Phase 2.7 (same branch, uncommitted, scripted tests only; live Gemini and Android not re-run): the
  coach's dates are the user's own and deterministic. `POST /coach/message` takes an optional IANA
  `timezone` (the app sends the device's); "today" is the user's local day in it, the UTC day without it
  (`app/tools/coach_calendar.py`), the model is told the calendar in its instructions
  (`CoachContext.dates`), and the proposal tool resolves the user's own words to dates by rules
  (`app/tools/schedule.py`): the model's `scheduled_date` must be the day they named, "the weekend",
  "next week" and other words that fit two days are asked about, never guessed. A newer proposal for a
  saved plan supersedes the user's earlier pending ones for it (`SUPERSEDED`, no migration). The reply
  guard classifies claims on a normalized text (workout names, quotes and `&` are one word) and holds
  state claims to the plan they name; a sentence that says the pending proposal awaits approval may call
  it "the harder version" only if the record supports the word. Backend tests now run in the disposable
  `formiq_pytest` database, never `formiq_test` (QA) or the development one. Details and limits:
  `docs/agent-production-contract.md` sections 5, 8 and 10; the live plan is in
  `docs/live-gemini-regression-checklist.md`.

## Decisions to remember

- `app/approvals/access.py` and `proposal.py` are used by the proposal flow. `store.py` and
  `audit.py` (and parts of `test_write_boundary*.py`) are still unused: proposals are kept in
  PostgreSQL by `PlanProposalService` instead. The user chose to keep them; propose replacing
  them rather than bending a feature to fit them.
- The three overlapping tracing test files (`tests/unit/test_coach_tracing.py`,
  `tests/integration/test_coach_tracing.py`, `tests/unit/test_reliability_observability.py`) are
  also kept on purpose. Don't delete any of these unless the user asks.
- Revising a saved plan (user's decision, 2026-10-14): approving the revision saves it as a new
  PLANNED plan and cancels the original in the same transaction; the original is never edited
  or deleted. An ALTERNATIVE keeps an original main exercise only when the catalog has no other
  suitable one: no fixed share of changed exercises.
- The safety thresholds (2 kg/week loss, 800 kcal/day, 72 h fast) and the workout completeness
  minimums are product guardrails, not medical rules.
- Recovery summary (user's decisions, 2026-10-17): the language-model explanation is deferred (a
  later coach read tool would explain the validated result, which changes the pinned tool set);
  calories burned only as a MET range, never one number or an intake target; one session-keyed
  endpoint, no date or timezone summary. Estimates are ranges with sources and assumptions, apart
  from calculated facts and general guidance. A warning sign withholds every estimate, hydration,
  food and recovery-timing item; pain or injury gives no return-to-training time; the only free
  text read is the user's notes, by the coach's keyword backstop, and it is never echoed. Energy
  ranges cover ages 19 to 59 (the 2024 Adult Compendium's range). VEGETARIAN excludes eggs. The
  thresholds are product guardrails, not medical rules; the values not yet checked against a
  primary text are listed in `docs/nutrition-recovery.md`.
- Langfuse: the model request span is `model_request` (it was `gemini` before `288f878`; older
  traces keep the old name). The project has no custom dashboards, widgets or evaluators to
  update (checked 2026-10-14). `LANGFUSE_CAPTURE_CONTENT` is refused outside `APP_ENV`
  development or test.
