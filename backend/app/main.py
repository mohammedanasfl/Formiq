from fastapi import FastAPI

from app.api.routes import (
    coach,
    equipment,
    exercises,
    health,
    muscle_groups,
    users,
    workout_plans,
    workout_sessions,
)
from app.core.config import settings

app = FastAPI(title=settings.app_name)

app.include_router(health.router)
app.include_router(users.router)
app.include_router(exercises.router)
app.include_router(muscle_groups.router)
app.include_router(equipment.router)
app.include_router(workout_plans.router)
app.include_router(workout_sessions.router)
app.include_router(coach.router)
