from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.dependencies import get_tracer
from app.api.routes import (
    auth,
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


@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """FastAPI's 422, without the values that failed: it names the field and
    why, and never sends back what was sent, such as a password."""
    errors = [{key: value for key, value in e.items() if key != "input"} for e in error.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(exercises.router)
app.include_router(muscle_groups.router)
app.include_router(equipment.router)
app.include_router(workout_plans.router)
app.include_router(workout_sessions.router)
app.include_router(coach.router)
