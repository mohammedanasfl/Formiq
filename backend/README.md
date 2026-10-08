# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 2.5: a FastAPI application with a health check and an API for creating users and their
onboarding profiles, stored in PostgreSQL through SQLAlchemy, with Alembic migrations and unit and
integration tests (integration tests use a dedicated test database). Authentication, AI coaching,
and other features are planned for later phases.

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
- `app/models/`: SQLAlchemy models (`User`, `UserProfile`)
- `app/schemas/`: Pydantic request and response schemas
- `app/repositories/`: database access for users and profiles
- `app/services/`: business logic and service-level errors
- `app/api/dependencies.py`: the database session dependency for routes
- `app/api/routes/`: `GET /health` and the `/users` endpoints
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

## Tests

Run the tests from the `backend/` directory, with the virtual environment activated:

```bash
pytest                     # all tests
pytest tests/unit          # unit tests
pytest tests/integration   # integration tests
```

Integration tests require the local PostgreSQL container to be running (`docker compose up -d`
from the repository root). Unit tests do not need PostgreSQL.

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

## API

| Method | Path | Request body | Success |
|---|---|---|---|
| `GET` | `/health` | | 200 |
| `POST` | `/auth/login` | email and password | 200 |
| `POST` | `/users` | email and/or phone (at least one) | 201 |
| `GET` | `/users/{user_id}` | | 200 |
| `POST` | `/users/{user_id}/profile` | onboarding profile | 201 |
| `GET` | `/users/{user_id}/profile` | | 200 |
| `PATCH` | `/users/{user_id}/profile` | profile fields to change | 200 |

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
is not found. `POST /users` and the exercise catalog need no sign-in. The coach takes its user from
the token only; its request body has no `user_id`.

1. Set `AUTH_JWT_SECRET` in `.env` (never in `.env.example`), for example to the output of
   `openssl rand -hex 32`. `AUTH_JWT_ALGORITHM` (HS256, HS384 or HS512) and
   `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` (30 by default) are optional.
2. Apply the migrations (`alembic upgrade head`): passwords are kept, as Argon2id hashes only,
   in the `user_credentials` table.
3. Give an existing user who has an email a password. The command asks for it without echoing
   it, and never takes it as an argument:
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
