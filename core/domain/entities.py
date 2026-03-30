from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from core.domain.enums import (
    ProjectType,
    ReviewAction,
    TaskKind,
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
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    deleted_at: datetime | None = None
    last_synced_name: str | None = None


@dataclass
class TaskRevision:
    id: UUID
    stable_id: UUID
    revision_no: int
    raw_text: str
    proposal_json: dict[str, object]
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
    stable_id: UUID
    telegram_chat_id: str
    telegram_message_id: int
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass
class DailyReviewSnapshot:
    id: UUID
    summary_text: str
    payload_json: dict[str, object]
    created_at: datetime
