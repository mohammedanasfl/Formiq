# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 1.4: the FastAPI application with a `GET /health` endpoint, typed configuration, and
the PostgreSQL database foundation (SQLAlchemy engine, session factory, and declarative base).
Database models, migrations, and other backend layers are planned for later phases.

## Contents

- `app/main.py`: creates the FastAPI application and registers routers
- `app/core/config.py`: application settings, read from environment variables and `.env`
- `app/db/database.py`: SQLAlchemy engine, session factory, and the `get_db()` dependency
- `app/db/base.py`: declarative base for future database models
- `app/api/routes/health.py`: `GET /health` endpoint
- `tests/`: tests (empty for now)
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

## Running the application

From the `backend/` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload
```

The health endpoint is then available at http://127.0.0.1:8000/health.
