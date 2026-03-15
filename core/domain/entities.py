from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from core.domain.enums import (
    ConfidenceBand,
    ProjectType,
    ReviewAction,
    TaskKind,
    TaskStatus,
)


@dataclass
class Project:
    id: UUID
    name: str
    slug: str
    google_tasklist_id: str
    project_type: ProjectType
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class TaskItem:
    id: UUID
    source_google_task_id: str
    source_google_tasklist_id: str
    raw_text: str
    status: TaskStatus
    kind: TaskKind | None = None
    normalized_title: str | None = None
    project_id: UUID | None = None
    current_google_task_id: str | None = None
    current_google_tasklist_id: str | None = None
    next_action: str | None = None
    due_hint: str | None = None
    confidence_score: float | None = None
    confidence_band: ConfidenceBand | None = None
    llm_model: str | None = None
    is_processed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class TaskRevision:
    id: UUID
    task_item_id: UUID
    revision_no: int
    raw_text: str
    proposal_json: dict
    created_at: datetime
    user_decision: ReviewAction | None = None
    user_notes: str | None = None
    final_title: str | None = None
    final_kind: TaskKind | None = None
    final_project_id: UUID | None = None
    final_next_action: str | None = None


@dataclass
class TelegramReviewSession:
    id: UUID
    task_item_id: UUID
    telegram_chat_id: str
    telegram_message_id: int
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass
class DailyReviewSnapshot:
    id: UUID
    summary_text: str
    payload_json: dict
    created_at: datetime
