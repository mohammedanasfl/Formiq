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

Tests use the `formiq_test` database, whose schema comes from Alembic migrations only. The
playground always runs on port 2001. `tests/conftest.py` turns the application's Langfuse tracer
off for every test, whatever `backend/.env` enables; tracing tests build their own tracer.

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

## Current state (2026-10-14)

- `dev` is at `48c9fe7`, pushed: 7 commits ahead of `main` (Phase 5 onwards), no PR open.
- Deploying `dev` needs `alembic upgrade head`; `AUTH_JWT_SECRET` and `GEMINI_API_KEY` set; a
  password per user via the CLI; and `python -m app.cli import-exercises`, run again whenever
  `app/catalog/` changes (the catalog corrections reach a database only through it; it is safe to
  re-run, and `--dry-run` shows what it would change). The dev database is current.
- Not done yet: timed sets (a set needs `reps`, so a timed exercise is logged without sets; needs
  a migration); exercise names in session history; a proposal rejection endpoint; five imported
  main exercises have no instructions or description.

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
- Langfuse: the model request span is `model_request` (it was `gemini` before `288f878`; older
  traces keep the old name). The project has no custom dashboards, widgets or evaluators to
  update (checked 2026-10-14). `LANGFUSE_CAPTURE_CONTENT` is refused outside `APP_ENV`
  development or test.
