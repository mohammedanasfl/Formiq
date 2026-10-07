from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import get_tracer
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # Traces are sent in the background; send what is left once, on the way out.
    if get_tracer.cache_info().currsize:
        get_tracer().shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health.router)
app.include_router(users.router)
app.include_router(exercises.router)
app.include_router(muscle_groups.router)
app.include_router(equipment.router)
app.include_router(workout_plans.router)
app.include_router(workout_sessions.router)
app.include_router(coach.router)
