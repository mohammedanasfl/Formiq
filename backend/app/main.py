from fastapi import FastAPI

from app.api.routes import equipment, exercises, health, muscle_groups, users
from app.core.config import settings

app = FastAPI(title=settings.app_name)

app.include_router(health.router)
app.include_router(users.router)
app.include_router(exercises.router)
app.include_router(muscle_groups.router)
app.include_router(equipment.router)
