# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 4 complete: a FastAPI application with users and onboarding profiles, the exercise catalog,
workout plans and workout sessions, email and password authentication with JWT access tokens, and
a read-only AI coach (`POST /coach/message`: Gemini through LangGraph, with optional Langfuse
tracing). Data is stored in PostgreSQL through SQLAlchemy, with Alembic migrations and unit and
integration tests (integration tests use a dedicated test database). The coach's guarantees are in
[the agent production contract](../docs/agent-production-contract.md). The coach can propose a
workout (a warm-up, the main exercises and a cool-down), which only the user's own approval saves
(`POST /coach/proposals/{proposal_id}/approve`); proposals are kept in PostgreSQL, so they outlive a
restart. The exercise catalog can import the free-exercise-db dataset (see Exercise catalog).

## Architecture

Requests flow through four layers:

```
API route (app/api) → service (app/services) → repository (app/repositories) → PostgreSQL
```

- Routes handle HTTP: request validation, status codes, and mapping service errors to responses.
- Services hold the business rules and own the database transactions (commit and rollback).
- Repositories only read and write the database; they never commit.

## Contents

- `app/main.py`: creates the FastAPI application and registers routers
- `app/core/config.py`: application settings, read from environment variables and `.env`
- `app/db/database.py`: SQLAlchemy engine, session factory, and the `get_db()` dependency
- `app/db/base.py`: declarative base for the database models
- `app/models/`: SQLAlchemy models
- `app/schemas/`: Pydantic request and response schemas
- `app/repositories/`: database access
- `app/services/`: business logic and service-level errors
- `app/api/dependencies.py`: route dependencies: the database session, the signed-in user, the
  coach's model provider and tracer
- `app/api/routes/`: the API's routes
- `app/core/security.py`: password hashing and access tokens
- `app/agent/`, `app/ai/`, `app/tools/`: the AI coach: its graph and policies, the Gemini provider,
  and its read-only tools
- `app/approvals/`: the rules of the write-approval boundary (the proposals waiting for approval
  are kept in the database by `app/services/plan_proposal_service.py`)
- `app/catalog/`: reading, validating and mapping the imported exercise dataset, and Formiq's
  classification of each exercise's uses (no database access)
- `app/guidance/`: the nutrition and recovery rules behind the recovery summary: protein,
  carbohydrate, hydration, rest windows, food examples and the sources they cite (pure Python,
  no database access; see [nutrition and recovery](../docs/nutrition-recovery.md))
- `data/free-exercise-db/`: the pinned upstream exercise dataset, unmodified, with its licence and
  `SOURCE.md` (provenance, checksums, licence findings)
- `data/exercise-images/`: the exercise images the API serves (none included yet; see its README)
- `app/observability/`: the coach's tracing (Langfuse, or off)
- `app/cli.py`: development commands (`set-password USER_ID`, `import-exercises [--dry-run]`)
- `alembic.ini`, `migrations/`: Alembic configuration and migration scripts
- `tests/`: unit tests (`tests/unit/`) and integration tests (`tests/integration/`)
- `pytest.ini`: pytest configuration
- `requirements.txt`: Python dependencies
- `.env.example`: example environment variables. Copy it to `.env` for local development;
  `.env` is ignored by Git and must not be committed.

## Installing dependencies

From the `backend/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Database

PostgreSQL is required for database functionality. The application itself starts without a
running database.

Start PostgreSQL with the Docker Compose file in the repository root (run from the repository
root):

```bash
docker compose up -d     # start PostgreSQL on localhost:5432
docker compose down      # stop it (data is kept in a named volume)
```

The connection is configured with `DATABASE_URL` in `.env` (copied from `.env.example`):

```
DATABASE_URL=postgresql+psycopg://formiq:formiq@localhost:5432/formiq
```

`DATABASE_URL` is required: the application does not start if it is not set.

## Migrations

Alembic is used for database migrations. It uses the same `DATABASE_URL` as the application.
Run Alembic from the `backend/` directory, with PostgreSQL running and the virtual
environment activated:

```bash
alembic upgrade head     # apply all migrations
alembic downgrade base   # revert all migrations
alembic current          # show the current revision
```

## Exercise catalog

The catalog holds Formiq's own exercises (seeded by the migrations) and exercises imported from
[free-exercise-db](https://github.com/yuhonas/free-exercise-db), pinned at commit
`f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5` and kept unmodified in `data/free-exercise-db/` (see
`SOURCE.md` there). Nothing is fetched from the network: the import reads that file, and refuses it
if its checksum is not the pinned one.

Import it, after `alembic upgrade head`, from `backend/` with the virtual environment activated:

```bash
python -m app.cli import-exercises --dry-run   # validate, and report what it would do
python -m app.cli import-exercises             # import, in one transaction
```

It prints what it found and did: records discovered, imported, updated, unchanged, skipped and
rejected (with reasons), values without a Formiq mapping, incomplete records, and images registered
or missing. Running it again changes nothing. It adds or updates only the imported exercises and
their muscle and equipment links, matched by their upstream id: Formiq's own exercises, and every
user's plans, sessions and history, are never changed, and an updated exercise keeps its id. An
upstream record that is the same exercise as one of Formiq's own (by name, ignoring case and
punctuation) is skipped and reported, never duplicated.

Each imported exercise keeps:

- its upstream record, every field as it was, in `source_record` (re-importable from the database),
  its upstream id in `source_id` (separate from Formiq's `id`) and the commit in `source_version`;
- its muscles and equipment, mapped explicitly to Formiq's catalog (`app/catalog/free_exercise_db.py`);
  a value without a mapping rejects the record and is reported;
- its `uses`: Formiq's own judgement of the workout sections it suits (`WARM_UP`, `MAIN_WORKOUT`,
  `COOL_DOWN`), kept apart from the upstream `category` (`app/catalog/classification.py`).

### Exercise images

`GET /exercises/{exercise_id}/images/{position}` serves an exercise's image; an exercise's `images`
list gives each one's `url`, in order, and is empty when it has none (a client shows a placeholder).
A client never sees or sends a file path: the database keeps each image's path relative to
`data/exercise-images/` (`EXERCISE_IMAGES_DIR` overrides it), and a path is served only when it
resolves to an image file inside that directory. A missing image is a plain 404.

The free-exercise-db images are **not** included: their licence is not confirmed (see
`data/free-exercise-db/SOURCE.md`). To add images whose licence allows it, see
`data/exercise-images/README.md`, then run the import again.

The backend runs from `backend/`, on the host; Docker runs only PostgreSQL. The images directory is
found from the code's own location, so it does not depend on the directory the process starts in.

## Tests

Run the tests from the `backend/` directory, with the virtual environment activated:

```bash
pytest                     # all tests
pytest tests/unit          # unit tests
pytest tests/integration   # integration tests
```

Integration tests require the local PostgreSQL container to be running (`docker compose up -d`
from the repository root). Unit tests do not need PostgreSQL. No test calls Gemini unless asked:
the models are scripted. Two opt-in live smoke runs exist:

```bash
# the configured test model (GEMINI_TEST_MODEL) through Formiq's provider and coach
LIVE_GEMINI_SMOKE=1 GEMINI_TEST_MODEL=gemini-3.5-flash-lite pytest tests/integration/test_gemini_live.py -s
# the agent scenarios, against GEMINI_MODEL (or LIVE_AGENT_SMOKE_MODEL)
LIVE_AGENT_SMOKE=1 pytest tests/integration/test_agent_scenarios.py -k live -s
```

Both need `GEMINI_API_KEY`, use quota, and report a provider failure as a failure, never a pass.
`GEMINI_TEST_MODEL` is used by the smoke test only; the application always uses `GEMINI_MODEL`, and
the test never falls back to it.

### Test database

Integration tests use a separate database, `formiq_test`, in the same PostgreSQL container. They
never use the development database (`DATABASE_URL`). Configure it in `.env`:

```
TEST_DATABASE_URL=postgresql+psycopg://formiq:formiq@localhost:5432/formiq_test
```

The tests stop with an error if `TEST_DATABASE_URL` is missing, points to the same database as
`DATABASE_URL`, or points to a database other than `formiq_test`. They apply the Alembic
migrations to `formiq_test` themselves.

`formiq_test` is created automatically when the PostgreSQL data volume is first initialized. For a
volume created before the test database was added, create it once (from the repository root):

```bash
docker compose exec postgres createdb -U formiq formiq_test
```

To run Alembic commands against the test database, override `DATABASE_URL` for that command:

```bash
DATABASE_URL=postgresql+psycopg://formiq:formiq@localhost:5432/formiq_test alembic current
```

## Running the application

From the `backend/` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload
```

The health endpoint is then available at http://127.0.0.1:8000/health, and interactive API
documentation at http://127.0.0.1:8000/docs.

To watch the coach's turns in the terminal while developing, set `AGENT_DEBUG=events` (the ordered
timeline, no content) or `AGENT_DEBUG=content` (also the prompt text and the tool data that is safe
to show; the user's words and profile are always redacted). It needs `APP_ENV=development` (or
`test`) set explicitly, prints to stderr only and changes nothing a turn does:
`docs/agent-debug.md`.

## API

| Method | Path | Request body | Success |
|---|---|---|---|
| `GET` | `/health` | | 200 |
| `GET` | `/exercises` | filters: `difficulty`, `movement_pattern`, `use`, `muscle_group_id`, `equipment_id`, `is_active` | 200 |
| `GET` | `/exercises/{exercise_id}` | | 200 |
| `GET` | `/exercises/{exercise_id}/images/{position}` | | 200 (an image) |
| `POST` | `/coach/message` | message and history | 200 |
| `POST` | `/coach/proposals/{proposal_id}/approve` | the proposal's binding | 201 |
| `POST` | `/auth/login` | email and password | 200 |
| `POST` | `/auth/register` | email and password (8+ characters): a new account, signed in | 201 |
| `GET` | `/users/{user_id}` | | 200 |
| `POST` | `/users/{user_id}/profile` | onboarding profile | 201 |
| `GET` | `/users/{user_id}/profile` | | 200 |
| `PATCH` | `/users/{user_id}/profile` | profile fields to change | 200 |
| `POST` | `/users/{user_id}/workout-sessions/{session_id}/recovery-summary` | optional: discomfort, warning signs, allergens to avoid (enums only) | 200 |

`POST .../recovery-summary` is the nutrition and recovery summary of one COMPLETED workout
session (`409` while it is IN_PROGRESS or CANCELLED). It only reads: nothing is stored, and no
language model is involved. Its estimates are ranges with their assumptions and sources, kept
apart from calculated facts and general guidance; see
[nutrition and recovery](../docs/nutrition-recovery.md).

`PATCH` changes only the fields that are sent. Optional fields (`last_name`, `target_weight_kg`,
`goal_period_weeks`, `dietary_preference`) can be cleared with `null`; other fields cannot.

Errors return `{"detail": "..."}` with these status codes:

- `400`: the request is invalid for the service (for example, `null` for a required profile field)
- `404`: the user or profile does not exist
- `409`: a user with the same email or phone, or a profile for the user, already exists
- `401`: no valid access token (see Authentication)
- `404`: also for any `user_id` other than the signed-in user's
- `422`: the request body or `user_id` fails validation
- `503`: authentication is not configured (`AUTH_JWT_SECRET` is not set)

## Authentication

Every route under `/users/{user_id}`, and `POST /coach/message`, needs the header
`Authorization: Bearer <access token>`, and serves only the signed-in user: any other `user_id`
is not found. Signing up (`POST /auth/register`) and the exercise catalog need no sign-in. There is
no other way to create a user through the API: an account always gets its password when it is
made, so no one can take an email before its owner signs up with it. The coach takes its user from
the token only; its request body has no `user_id`.

1. Set `AUTH_JWT_SECRET` in `.env` (never in `.env.example`), for example to the output of
   `openssl rand -hex 32`. `AUTH_JWT_ALGORITHM` (HS256, HS384 or HS512) and
   `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` (30 by default) are optional.
2. Apply the migrations (`alembic upgrade head`): passwords are kept, as Argon2id hashes only,
   in the `user_credentials` table.
3. Sign up with `POST /auth/register` (`{"email": ..., "password": ...}`, at least 8
   characters): it creates the account with its password and returns an `access_token`. The email
   is stored in lower case, without surrounding spaces: an address is one account whatever its
   case, and login matches it so. An email that already has an account, in any case, gets 409, and
   that account is left as it was: signing up never gives an existing account a password.
   Accounts made earlier whose emails differ only in case are kept apart, never merged: each logs
   in with its email exactly as stored. To give an existing user who has an email a password,
   or change it, use the command, which asks for it without echoing it and never takes it as an
   argument:
   ```bash
   python -m app.cli set-password USER_ID
   ```
4. Log in, and send the returned `access_token` as the Bearer token:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/auth/login -H 'Content-Type: application/json' \
     -d '{"email": "you@example.com", "password": "..."}'
   ```

A wrong password, an unknown email and a user without a password all get the same 401. Tokens
expire and cannot be revoked earlier; there is no logout, refresh token or password reset yet.
