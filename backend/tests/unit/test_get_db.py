from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.db import database
from app.db.database import get_db


@pytest.fixture
def fake_session(monkeypatch):
    """The session get_db receives from SessionLocal, replaced so no database is used."""
    session = Mock(spec=Session)
    monkeypatch.setattr(database, "SessionLocal", Mock(return_value=session))
    return session


# FastAPI runs generator dependencies such as get_db as context managers.


def test_get_db_closes_session(fake_session):
    with contextmanager(get_db)() as session:
        assert session is fake_session
        fake_session.close.assert_not_called()

    fake_session.close.assert_called_once()


def test_get_db_closes_session_when_the_consumer_raises(fake_session):
    with pytest.raises(RuntimeError, match="request failed"):
        with contextmanager(get_db)():
            raise RuntimeError("request failed")

    fake_session.close.assert_called_once()
