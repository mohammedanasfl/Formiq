from app.schemas.auth import AccessTokenResponse, LoginRequest
from app.schemas.coach import CoachMessageRequest, CoachMessageResponse
from app.schemas.equipment import EquipmentResponse
from app.schemas.exercise import (
    Difficulty,
    ExerciseEquipmentResponse,
    ExerciseFilters,
    ExerciseMuscleResponse,
    ExerciseResponse,
    MovementPattern,
    MuscleRole,
)
from app.schemas.muscle_group import MuscleGroupResponse
from app.schemas.user import UserCreate, UserResponse
from app.schemas.user_profile import (
    UserProfileCreate,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.schemas.workout_plan import (
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanExerciseResponse,
    WorkoutPlanExerciseUpdate,
    WorkoutPlanFilters,
    WorkoutPlanResponse,
    WorkoutPlanStatus,
    WorkoutPlanUpdate,
)
from app.schemas.workout_session import (
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionExerciseResponse,
    WorkoutSessionExerciseUpdate,
    WorkoutSessionFilters,
    WorkoutSessionResponse,
    WorkoutSessionStatus,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetResponse,
    WorkoutSetUpdate,
)

__all__ = [
    "UserCreate",
    "UserResponse",
    "UserProfileCreate",
    "UserProfileUpdate",
    "UserProfileResponse",
    "Difficulty",
    "MovementPattern",
    "MuscleRole",
    "ExerciseFilters",
    "ExerciseMuscleResponse",
    "ExerciseEquipmentResponse",
    "ExerciseResponse",
    "MuscleGroupResponse",
    "EquipmentResponse",
    "WorkoutPlanStatus",
    "WorkoutPlanCreate",
    "WorkoutPlanUpdate",
    "WorkoutPlanResponse",
    "WorkoutPlanFilters",
    "WorkoutPlanExerciseCreate",
    "WorkoutPlanExerciseUpdate",
    "WorkoutPlanExerciseResponse",
    "WorkoutSessionStatus",
    "WorkoutSessionCreate",
    "WorkoutSessionUpdate",
    "WorkoutSessionResponse",
    "WorkoutSessionFilters",
    "WorkoutSessionExerciseCreate",
    "WorkoutSessionExerciseUpdate",
    "WorkoutSessionExerciseResponse",
    "WorkoutSetCreate",
    "WorkoutSetUpdate",
    "WorkoutSetResponse",
    "LoginRequest",
    "AccessTokenResponse",
    "CoachMessageRequest",
    "CoachMessageResponse",
]
