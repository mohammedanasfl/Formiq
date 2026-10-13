# Formiq

Adaptive AI fitness coach. A FastAPI + PostgreSQL backend with a read-only AI coach (LangGraph +
Gemini). The React Native app (`frontend/`) comes later. Repo: `mohammedanasfl/Formiq`.

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
.venv/bin/python ../playground/server.py      # playground at http://localhost:2001/playground/
```

Tests use the `formiq_test` database, whose schema comes from Alembic migrations only. The
playground always runs on port 2001.

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
    to its critical guarantees, the tests consolidated.

## Current state (2026-10-13)

- `dev` is at `9e7242f`, pushed. PR #4 (`dev` to `main`, Phase 3 + Phase 4) is open, not merged.
- Deploying it needs `alembic upgrade head`, `AUTH_JWT_SECRET` and `GEMINI_API_KEY` set, and a
  password per user via the CLI.
- **Next: Phase 5 (writes)**, waiting for the user's brief.

## Decisions to remember

- `app/approvals/proposal.py`, `store.py`, `audit.py` and their tests
  (`test_write_boundary*.py`) are unused today; only `approvals/access.py` is used, by
  `app/agent/graph.py`. The user chose to keep them. In Phase 5, check whether they fit the real
  write flow; if not, propose replacing them rather than bending the feature to fit them.
- The three overlapping tracing test files (`tests/unit/test_coach_tracing.py`,
  `tests/integration/test_coach_tracing.py`, `tests/unit/test_reliability_observability.py`) are
  also kept on purpose. Don't delete any of these unless the user asks.
- The safety thresholds (2 kg/week loss, 800 kcal/day, 72 h fast) are product guardrails, not
  medical rules.
