"""Development and operations commands, run from backend/ against DATABASE_URL.

    python -m app.cli set-password USER_ID

Sets the login password of an existing user who has an email. The password is
read from the terminal without echo, or from standard input when it is not a
terminal; it is never taken as an argument, so it stays out of shell history
and process lists.

    python -m app.cli import-exercises [--dry-run]

Imports the pinned free-exercise-db dataset (backend/data/free-exercise-db)
into the exercise catalog, and prints what it did. With --dry-run it changes
nothing and prints what the import would do. Running it again is safe: it
adds no duplicates and changes no user's data.
"""

import argparse
import getpass
import sys

from app.catalog import free_exercise_db
from app.core.config import settings
from app.db.database import SessionLocal
from app.services.auth_service import AuthService
from app.services.exceptions import ServiceError
from app.services.exercise_import_service import ExerciseImportService, ImportSummary


def read_password() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    password = getpass.getpass("New password: ")
    if getpass.getpass("Repeat it: ") != password:
        raise SystemExit("The passwords differ; nothing was changed.")
    return password


def set_password(user_id: int) -> None:
    password = read_password()
    with SessionLocal() as session:
        try:
            AuthService(session).set_password(user_id, password)
        except ServiceError as error:
            raise SystemExit(f"Not changed: {error}.") from None
    print(f"Password set for user {user_id}.")


def import_exercises(dry_run: bool) -> None:
    try:
        records = free_exercise_db.load_records()
    except free_exercise_db.SourceFileError as error:
        raise SystemExit(f"Nothing imported: {error}.") from None
    parsed = free_exercise_db.parse_records(records)
    with SessionLocal() as session:
        summary = ExerciseImportService(session).import_source(
            parsed,
            source=free_exercise_db.SOURCE,
            version=free_exercise_db.SOURCE_VERSION,
            discovered=len(records),
            images_dir=settings.exercise_images_dir,
            dry_run=dry_run,
        )
    print(report(summary))


def report(summary: ImportSummary) -> str:
    """The import's summary, for a person to read."""

    def listed(items: list[tuple[str, str]]) -> list[str]:
        return [f"    {source_id}: {detail}" for source_id, detail in items]

    unresolved = "; ".join(
        f"{name}: {', '.join(values)}" for name, values in summary.unresolved.items()
    )
    dry_run = "DRY RUN, nothing was changed: " if summary.dry_run else ""
    lines = [
        f"{dry_run}{summary.source} at {summary.version}",
        f"  discovered: {summary.discovered}",
        f"  imported:   {len(summary.imported)}",
        f"  updated:    {len(summary.updated)}",
        f"  unchanged:  {len(summary.unchanged)}",
        f"  skipped:    {len(summary.skipped)}",
        *listed(summary.skipped),
        f"  rejected:   {len(summary.rejected)}",
        *listed(summary.rejected),
        f"  unresolved mappings: {unresolved or 'none'}",
        "  unknown fields (kept in the records): " + (", ".join(summary.unknown_fields) or "none"),
        f"  incomplete records (imported): {len(summary.incomplete)}",
        *listed(summary.incomplete),
        (
            f"  images registered: {summary.images_registered}; "
            f"listed but not in {settings.exercise_images_dir.name}/: {summary.images_missing}"
        ),
        (
            "  imported earlier, no longer in the source (left as they are): "
            f"{', '.join(summary.not_in_source) or 'none'}"
        ),
        "  exercises from this source by use: "
        + ", ".join(f"{use} {count}" for use, count in summary.uses.items()),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    set_password_command = commands.add_parser(
        "set-password", help="set a user's login password"
    )
    set_password_command.add_argument("user_id", type=int)
    import_command = commands.add_parser(
        "import-exercises", help="import the pinned free-exercise-db dataset into the catalog"
    )
    import_command.add_argument(
        "--dry-run", action="store_true", help="report what the import would do; change nothing"
    )
    arguments = parser.parse_args(argv)

    if arguments.command == "set-password":
        set_password(arguments.user_id)
    else:
        import_exercises(arguments.dry_run)


if __name__ == "__main__":
    main()
