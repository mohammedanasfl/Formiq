from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MuscleGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
