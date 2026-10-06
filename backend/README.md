# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 1.6: the FastAPI application with a `GET /health` endpoint, typed configuration, the
PostgreSQL database foundation (SQLAlchemy engine, session factory, and declarative base),
Alembic migrations (one initial, empty migration), and pytest unit and integration tests.
Database models and other backend layers are planned for later phases.

## Contents

- `app/main.py`: creates the FastAPI application and registers routers
- `app/core/config.py`: application settings, read from environment variables and `.env`
- `app/db/database.py`: SQLAlchemy engine, session factory, and the `get_db()` dependency
- `app/db/base.py`: declarative base for future database models
- `app/api/routes/health.py`: `GET /health` endpoint
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

The health endpoint is then available at http://127.0.0.1:8000/health.
