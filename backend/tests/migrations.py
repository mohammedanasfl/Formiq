"""The Alembic migration modules, for the tests of the data a migration seeds."""

from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# the exercise catalog's seeds and what followed them
SEED_REVISION = "b84c61ea69bf"
LATER_SEED_REVISION = "14d543e636a8"
SOURCE_REVISION = "620eafb9c204"
PROPOSALS_REVISION = "9f7cfca45752"
ACTIVITIES_REVISION = "a7d3f1c82e4b"
TREADMILL_REVISION = "c9e24b7a5d13"


def migration_module(revision: str) -> ModuleType:
    """The migration's module, read from its file: no database is touched."""
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_revision(revision).module
