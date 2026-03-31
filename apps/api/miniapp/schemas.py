from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ReviewQueueItem(BaseModel):
    stable_id: uuid.UUID
    raw_text: str
    normalized_title: str
    project_name: str | None = None
    kind: str
    confidence: str
    has_ambiguity: bool = False
    created_at: datetime


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    pending: int
    queued: int


class ReviewDetail(BaseModel):
    stable_id: uuid.UUID
    raw_text: str
    normalized_title: str
    kind: str
    confidence: str
    project_name: str | None = None
    project_id: str | None = None
    next_action: str | None = None
    due_hint: str | None = None
    substeps: list[str] = []
    ambiguities: list[str] = []
    disambiguation_options: list[dict[str, object]] = []
    telegram_message_id: int | None = None
    created_at: datetime


class ActionResponse(BaseModel):
    success: bool
    message: str


class EditTitleRequest(BaseModel):
    title: str


class ChangeProjectRequest(BaseModel):
    project_id: str


class ChangeTypeRequest(BaseModel):
    kind: str


class ClarifyRequest(BaseModel):
    option_index: int


class DraftResponse(BaseModel):
    success: bool
    draft_text: str | None = None
    message: str


class UserSettingsResponse(BaseModel):
    auto_next: bool
    batch_size: int
    paused: bool
    sync_summary: bool
    daily_brief: bool
    show_confidence: bool
    show_raw_input: bool
    draft_suggestions: bool
    ambiguity_prompts: bool
    show_steps_auto: bool
    changes_only: bool


class UserSettingsUpdateRequest(BaseModel):
    auto_next: bool | None = None
    batch_size: int | None = None
    paused: bool | None = None
    sync_summary: bool | None = None
    daily_brief: bool | None = None
    show_confidence: bool | None = None
    show_raw_input: bool | None = None
    draft_suggestions: bool | None = None
    ambiguity_prompts: bool | None = None
    show_steps_auto: bool | None = None
    changes_only: bool | None = None


class ProjectListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    project_type: str
    description: str | None = None
    is_active: bool
