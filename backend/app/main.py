from fastapi import FastAPI

from app.api.routes import health

app = FastAPI(title="Formiq")

app.include_router(health.router)
