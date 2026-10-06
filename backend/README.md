# Formiq Backend

The Formiq backend is written in Python and uses [FastAPI](https://fastapi.tiangolo.com/).

## Requirements

- Python 3.11+

## Status

Phase 1.2: the FastAPI application with a `GET /health` endpoint.
The database and other backend layers are planned for later phases.

## Contents

- `app/main.py`: creates the FastAPI application and registers routers
- `app/api/routes/health.py`: `GET /health` endpoint
- `tests/`: tests (empty for now)
- `requirements.txt`: Python dependencies
- `.env.example`: example environment variables (not loaded by the application yet)

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
