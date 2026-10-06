from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserCreate(BaseModel):
    email: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def require_email_or_phone(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("email or phone is required")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime
