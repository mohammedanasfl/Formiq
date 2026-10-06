# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 1.3: the FastAPI application with a `GET /health` endpoint and typed configuration.
The database and other backend layers are planned for later phases.

## Contents

- `app/main.py`: creates the FastAPI application and registers routers
- `app/core/config.py`: application settings, read from environment variables and `.env`
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

## Running the application

From the `backend/` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload
```

The health endpoint is then available at http://127.0.0.1:8000/health.
