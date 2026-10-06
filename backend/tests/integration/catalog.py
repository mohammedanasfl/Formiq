"""Helpers that add exercise catalog test data.

The rows are only flushed, never committed. Their names start with "Test", so
they never clash with the seeded reference data.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models import Equipment, Exercise, ExerciseMuscle, MuscleGroup


def add_muscle_group(session: Session, name: str, *, is_active: bool = True) -> MuscleGroup:
    muscle_group = MuscleGroup(name=name, is_active=is_active)
    session.add(muscle_group)
    session.flush()
    return muscle_group


def add_equipment(session: Session, name: str, *, is_active: bool = True) -> Equipment:
    item = Equipment(name=name, is_active=is_active)
    session.add(item)
    session.flush()
    return item


def add_exercise(
    session: Session,
    name: str,
    *,
    primary: Sequence[MuscleGroup] = (),
    secondary: Sequence[MuscleGroup] = (),
    equipment: Sequence[Equipment] = (),
    difficulty: str = "BEGINNER",
    movement_pattern: str = "SQUAT",
    is_active: bool = True,
) -> Exercise:
    exercise = Exercise(
        name=name,
        difficulty=difficulty,
        movement_pattern=movement_pattern,
        is_active=is_active,
        muscles=[ExerciseMuscle(muscle_group=group, role="PRIMARY") for group in primary]
        + [ExerciseMuscle(muscle_group=group, role="SECONDARY") for group in secondary],
        equipment=list(equipment),
    )
    session.add(exercise)
    session.flush()
    return exercise


def add_exercises_for_each_filter(session: Session):
    """Exercises for testing that every exercise filter is applied.

    "Test Match" has difficulty BEGINNER, movement pattern SQUAT, the returned
    muscle group and equipment, and is active. Each other exercise differs from
    it in exactly one of these, so each filter excludes exactly one of them.
    Returns the muscle group and the equipment.
    """
    muscle_group = add_muscle_group(session, "Test Filter Muscle")
    other_muscle_group = add_muscle_group(session, "Test Other Muscle")
    item = add_equipment(session, "Test Filter Equipment")
    matching = {
        "primary": [muscle_group],
        "equipment": [item],
        "difficulty": "BEGINNER",
        "movement_pattern": "SQUAT",
    }

    add_exercise(session, "Test Match", **matching)
    add_exercise(session, "Test Other Difficulty", **{**matching, "difficulty": "ADVANCED"})
    add_exercise(session, "Test Other Pattern", **{**matching, "movement_pattern": "HINGE"})
    add_exercise(session, "Test Other Muscle", **{**matching, "primary": [other_muscle_group]})
    add_exercise(session, "Test No Equipment", **{**matching, "equipment": []})
    add_exercise(session, "Test Inactive", **matching, is_active=False)
    return muscle_group, item
