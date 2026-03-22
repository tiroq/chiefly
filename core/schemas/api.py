from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from core.domain.enums import ProjectType


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    project_type: ProjectType
    is_active: bool

    model_config = {"from_attributes": True}


class DailyReviewResponse(BaseModel):
    id: UUID
    summary_text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
