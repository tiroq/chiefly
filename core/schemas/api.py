from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from core.domain.enums import ConfidenceBand, ProjectType, TaskKind, TaskStatus


class TaskItemResponse(BaseModel):
    id: UUID
    source_google_task_id: str
    raw_text: str
    normalized_title: str | None
    kind: TaskKind | None
    status: TaskStatus
    confidence_band: ConfidenceBand | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
