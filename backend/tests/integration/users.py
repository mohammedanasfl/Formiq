"""Users for the API tests. The API has no route that creates a user without a
password (an account is made by signing up, POST /auth/register), so the tests
add the users they sign in as to the test database themselves."""

from sqlalchemy.orm import Session

from app.models import User


def create_user(engine, *, email: str | None = None, phone: str | None = None) -> int:
    """A committed user with this email or phone, and no password; its id."""
    with Session(engine) as session:
        user = User(email=email, phone=phone)
        session.add(user)
        session.commit()
        return user.id
