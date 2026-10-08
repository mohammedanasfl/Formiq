"""The playground's backend tests run with the backend's virtual environment:

    cd backend
    .venv/bin/python -m pytest ../playground/tests

They call neither Gemini nor PostgreSQL: the model is a fake and the database
session a mock. The application needs a DATABASE_URL to import; a dummy one is
used when none is set, and no test connects to it.
"""

import os
import sys
from pathlib import Path

PLAYGROUND = Path(__file__).resolve().parents[1]
BACKEND = PLAYGROUND.parent / "backend"

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://playground:unused@127.0.0.1:1/unused"
)
for path in (str(BACKEND), str(PLAYGROUND)):
    if path not in sys.path:
        sys.path.insert(0, path)
