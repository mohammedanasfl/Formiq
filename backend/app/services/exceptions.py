"""Service-level errors. The API layer will translate them into HTTP responses."""


class ServiceError(Exception):
    """Base class for the service-level errors."""


class InvalidUserError(ServiceError):
    """The user data has neither an email nor a phone."""


class UserAlreadyExistsError(ServiceError):
    """A user with the same email or phone already exists."""


class UserNotFoundError(ServiceError):
    """The user does not exist."""


class UserProfileAlreadyExistsError(ServiceError):
    """The user already has a profile."""


class UserProfileNotFoundError(ServiceError):
    """The user has no profile."""


class InvalidProfileUpdateError(ServiceError):
    """The profile update sets a required field to null."""


class ExerciseNotFoundError(ServiceError):
    """The exercise does not exist in the catalog."""


class InactiveExerciseError(ServiceError):
    """The exercise is retired (is_active is false), so it cannot be added to a plan."""


class WorkoutPlanNotFoundError(ServiceError):
    """The user has no workout plan with this id."""


class WorkoutPlanExerciseNotFoundError(ServiceError):
    """The workout plan has no exercise with this id."""


class InvalidWorkoutPlanError(ServiceError):
    """The change would break a workout plan rule: for example a PLANNED plan
    without a scheduled date or exercises, or null for a required field."""


class WorkoutPlanConflictError(ServiceError):
    """Base class for changes that the workout plan's current state does not allow."""


class InvalidStatusTransitionError(WorkoutPlanConflictError):
    """The plan cannot change from its current status to the requested one."""


class WorkoutPlanNotEditableError(WorkoutPlanConflictError):
    """The plan is CANCELLED, so neither it nor its exercises can be changed."""


class WorkoutPlanNotDeletableError(WorkoutPlanConflictError):
    """Only DRAFT plans can be deleted; a PLANNED plan is cancelled instead."""


class ExerciseOrderTakenError(WorkoutPlanConflictError):
    """Another exercise of the plan already has this exercise_order."""
