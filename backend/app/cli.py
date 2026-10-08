"""Development and operations commands, run from backend/ against DATABASE_URL.

    python -m app.cli set-password USER_ID

Sets the login password of an existing user who has an email. The password is
read from the terminal without echo, or from standard input when it is not a
terminal; it is never taken as an argument, so it stays out of shell history
and process lists.
"""

import argparse
import getpass
import sys

from app.db.database import SessionLocal
from app.services.auth_service import AuthService
from app.services.exceptions import ServiceError


def read_password() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    password = getpass.getpass("New password: ")
    if getpass.getpass("Repeat it: ") != password:
        raise SystemExit("The passwords differ; nothing was changed.")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    set_password = commands.add_parser("set-password", help="set a user's login password")
    set_password.add_argument("user_id", type=int)
    arguments = parser.parse_args(argv)

    password = read_password()
    with SessionLocal() as session:
        try:
            AuthService(session).set_password(arguments.user_id, password)
        except ServiceError as error:
            raise SystemExit(f"Not changed: {error}.") from None
    print(f"Password set for user {arguments.user_id}.")


if __name__ == "__main__":
    main()
