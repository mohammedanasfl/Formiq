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
(`POST /coach/proposals/{proposal_id}/approve`, which is safe to repeat; the user may instead reject
one, and list those still waiting); proposals are kept in PostgreSQL, so they outlive a restart. The exercise catalog can import the free-exercise-db dataset (see Exercise catalog).

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
- `data/exercises-dataset/`: the second pinned exercise dataset (no images or GIFs), with its licence
  and `SOURCE.md`; imported with `--source exercises-dataset`
- `data/exercise-images/`: the exercise images the API serves (none included yet; see its README)
- `app/observability/`: the coach's tracing (Langfuse, or off)
- `app/cli.py`: development commands (`set-password USER_ID`,
  `import-exercises [--source free-exercise-db|exercises-dataset] [--dry-run]`)
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

### A second source: exercises-dataset

`python -m app.cli import-exercises --source exercises-dataset [--dry-run]` imports the pinned
[exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) (commit
`7455efae41b330c265e7cd4b78dfa848e7ce5ebd`, `data/exercises-dataset/`; see `SOURCE.md` there). The
default source stays free-exercise-db, and the same importer applies either: idempotent, in one
transaction, matched by `(source, source_id)`, with a dry run. The rules and tables are in
`app/catalog/exercises_dataset.py`:

- it keeps the external id, the source (`EXERCISES_DATASET`), the commit, and the record with only
  its **English** instructions; the name is shown in Title Case (the original is in the record);
- it makes nothing up: no difficulty (`UNRATED`; no migration, the column is text), no movement
  pattern, no `uses` (so the coach cannot put it in a proposed workout until Formiq classifies it),
  no description, no sets, reps or rest. The coach never offers an `UNRATED` exercise to a beginner
  or as a warm-up or cool-down activity;
- it registers **no image or GIF** (`image_paths` is empty): the media belong to a third party and
  are not cleared (`SOURCE.md`);
- it holds back, and reports with the reason, a record whose equipment value is not a piece of
  equipment, whose name or steps name gear its one equipment value does not (a "body weight" pull-up
  with a bar), whose primary muscle has no Formiq muscle group, or whose name is unusable or another
  record's; equipment and muscles go through explicit tables, and an unknown value is never guessed;
- an exact name collision with an exercise the catalog already has is skipped at import, never
  merged, and no existing exercise or id is changed.

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

Integration tests run in a **disposable** database, `formiq_pytest`, on the same PostgreSQL server.
They empty it (every user, plan and session, before and after each test) and move its schema down
and up again (the migration tests), so it is never a database that holds anything that matters:
not the development database (`DATABASE_URL`), and not `formiq_test`, which is the QA database
(accounts, plans and proposals made by hand and by the app's QA runs; a test run used to empty it,
Phase 2.7). `TEST_DATABASE_URL` is still needed, as the address of the server and its login:

```
TEST_DATABASE_URL=postgresql+psycopg://formiq:formiq@localhost:5432/formiq_test
```

The tests use the same server and login with the database name `formiq_pytest`; nothing is added
to `.env`. They create it the first time they run (the login needs the right to create databases,
as the container's `formiq` login has) and mark it with a comment only they set. They then fail
closed:

- `TEST_DATABASE_URL` missing, naming `DATABASE_URL`'s database, or naming anything but
  `formiq_pytest` (or `formiq_test`, as the server's address): an error, nothing is touched;
- before every step that deletes or migrates, the connection about to be used is asked which
  database it is in (`tests/integration/database.py`, `assert_disposable`): anything but
  `formiq_pytest` carrying the marker is refused, so a database that merely has that name is never
  emptied;
- `formiq_test` and the development database are never connected to by the tests.

The tests apply the Alembic migrations to `formiq_pytest` themselves. To drop the test database
(it is recreated by the next run): `docker compose exec postgres dropdb -U formiq formiq_pytest`.
`formiq_test` is created when the PostgreSQL data volume is first initialized (or with
`docker compose exec postgres createdb -U formiq formiq_test`) and is for manual and QA use; run
Alembic against a database by overriding `DATABASE_URL` for that command:

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
| `GET` | `/equipment` | | 200 |
| `GET` | `/muscle-groups` | | 200 |
| `POST` | `/coach/message` | message, history, and optionally `workout_plan_id` (the saved plan the user is changing) and `timezone` (the user's IANA time zone, e.g. `Asia/Kolkata`) | 200 (422 for a `timezone` that is not an IANA zone) |
| `GET` | `/coach/proposals/pending` | | 200 (the proposals that can still be approved) |
| `POST` | `/coach/proposals/{proposal_id}/approve` | the proposal's binding | 201 (200 when it was already approved: the plan it saved) |
| `POST` | `/coach/proposals/{proposal_id}/reject` | the proposal's binding | 204 |
| `POST` | `/auth/login` | email and password | 200 |
| `POST` | `/auth/register` | email and password (8+ characters): a new account, signed in | 201 |
| `GET` | `/users/{user_id}` | | 200 |
| `POST` | `/users/{user_id}/profile` | onboarding profile | 201 |
| `GET` | `/users/{user_id}/profile` | | 200 |
| `PATCH` | `/users/{user_id}/profile` | profile fields to change | 200 |
| `POST` | `/users/{user_id}/workout-plans` | workout plan | 201 |
| `GET` | `/users/{user_id}/workout-plans` | filters: `status`, `scheduled_date` | 200 |
| `GET` | `/users/{user_id}/workout-plans/{plan_id}` | | 200 |
| `PATCH` | `/users/{user_id}/workout-plans/{plan_id}` | plan fields to change | 200 |
| `DELETE` | `/users/{user_id}/workout-plans/{plan_id}` | | 204 |
| `POST` | `/users/{user_id}/workout-plans/{plan_id}/exercises` | plan exercise | 201 |
| `PATCH` | `/users/{user_id}/workout-plans/{plan_id}/exercises/{plan_exercise_id}` | exercise fields to change | 200 |
| `DELETE` | `/users/{user_id}/workout-plans/{plan_id}/exercises/{plan_exercise_id}` | | 204 |
| `POST` | `/users/{user_id}/workout-sessions` | optional `workout_plan_id`, notes | 201 |
| `GET` | `/users/{user_id}/workout-sessions` | filter: `status` | 200 |
| `GET` | `/users/{user_id}/workout-sessions/{session_id}` | | 200 |
| `PATCH` | `/users/{user_id}/workout-sessions/{session_id}` | `status`, notes | 200 |
| `DELETE` | `/users/{user_id}/workout-sessions/{session_id}` | | 204 (IN_PROGRESS only) |
| `POST` | `/users/{user_id}/workout-sessions/{session_id}/exercises` | session exercise | 201 |
| `PATCH` | `/users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}` | exercise fields to change | 200 |
| `DELETE` | `/users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}` | | 204 |
| `POST` | `/users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}/sets` | set | 201 |
| `PATCH` | `/users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}/sets/{set_id}` | set fields to change | 200 |
| `DELETE` | `/users/{user_id}/workout-sessions/{session_id}/exercises/{session_exercise_id}/sets/{set_id}` | | 204 |
| `POST` | `/users/{user_id}/workout-sessions/{session_id}/recovery-summary` | optional: discomfort, warning signs, allergens to avoid (enums only) | 200 |

The coach's "today" and "tomorrow" are the user's local days in the `timezone` the app sends, and the UTC
days without one (the coach is told which). A relative date or weekday the user says must be the day
Formiq works out from it, and words that fit two days ("the weekend", "next week") are asked about, never
guessed ([contract](../docs/agent-production-contract.md) section 8). The time zone database comes from the
operating system (or the `tzdata` package, which this project does not add): a server without one answers
every zone but `UTC` with a 422, and the app then sends the message without it.

`POST .../recovery-summary` is the nutrition and recovery summary of one COMPLETED workout
session (`409` while it is IN_PROGRESS or CANCELLED). It only reads: nothing is stored, and no
language model is involved. Its estimates are ranges with their assumptions and sources, kept
apart from calculated facts and general guidance; see
[nutrition and recovery](../docs/nutrition-recovery.md).

`PATCH` changes only the fields that are sent. Optional fields (`last_name`, `target_weight_kg`,
`goal_period_weeks`, `dietary_preference`) can be cleared with `null`; other fields cannot.

**Equipment.** A profile keeps the catalog equipment the user has (`GET /equipment`; the rows of
`user_profile_equipment`) or that they have none (`user_profiles.no_equipment`). The request takes
`equipment_ids` (each id once: a repeat is ignored; an id that is not active catalog equipment is a `400`
and nothing is saved) and `no_equipment` (bodyweight only; never together with ids: `422`). The response
has `no_equipment` and `equipment` (each piece with its `id` and `name`). A list in a `PATCH` replaces
the selection (`[]` clears it), `no_equipment: true` clears the list, and choosing equipment says the user
has some. With neither, the user never said: every profile made before equipment was kept, and anyone who
skipped the step. The coach starts from what the profile says (a piece it does not list is one the user
lacks) until the conversation says otherwise (`docs/agent-production-contract.md`, sections 8 and 10).

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
