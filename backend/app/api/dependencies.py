from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import get_db

# A database session for one request: get_db opens it from SessionLocal and
# closes it after the response.
DbSession = Annotated[Session, Depends(get_db)]
