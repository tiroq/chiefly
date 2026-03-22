from __future__ import annotations

import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.domain.enums import WorkflowStatus
from core.domain import notes_codec
from core.schemas.admin import TaskDetailResult, TaskListResult, TaskView
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository

logger = get_logger(__name__)


def build_task_view(record: TaskRecord, snapshot: TaskSnapshot | None) -> TaskView:
    payload = snapshot.payload if snapshot else {}
    notes_text = payload.get("notes", "")
    meta = notes_codec.parse(notes_text) or {}

    project_id_str = meta.get("project_id") or payload.get("project_id")
    project_id: uuid.UUID | None = None
    if project_id_str:
        try:
            project_id = uuid.UUID(str(project_id_str))
        except ValueError:
            pass

    return TaskView(
        id=record.stable_id,
        raw_text=payload.get("title", ""),
        status=record.processing_status,
        state=record.state,
        created_at=record.created_at,
        updated_at=record.updated_at,
        normalized_title=meta.get("normalized_title"),
        kind=meta.get("kind") or payload.get("kind"),
        project_id=project_id,
        project_name=meta.get("project_name"),
        next_action=meta.get("next_action"),
        due_hint=meta.get("due_hint"),
        confidence_band=meta.get("confidence"),
        current_tasklist_id=record.current_tasklist_id,
        current_task_id=record.current_task_id,
        last_error=record.last_error,
    )


class AdminTasksService:
    def __init__(
        self,
        record_repo: TaskRecordRepository,
        revision_repo: TaskRevisionRepository,
    ) -> None:
        self._record_repo = record_repo
        self._revision_repo = revision_repo

    async def list_tasks(
        self,
        session: AsyncSession,
        status: WorkflowStatus | None = None,
        kind: str | None = None,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> TaskListResult:
        offset = (page - 1) * per_page
        rows = await self._record_repo.list_filtered(
            processing_status=status,
            kind=kind,
            project_id=project_id,
            search=search,
            limit=per_page,
            offset=offset,
        )
        items = [build_task_view(record, snapshot) for record, snapshot in rows]

        total = await self._record_repo.count_filtered(
            processing_status=status,
            kind=kind,
            project_id=project_id,
            search=search,
        )
        total_pages = max(1, math.ceil(total / per_page))
        return TaskListResult(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    async def get_task_detail(
        self,
        session: AsyncSession,
        stable_id: uuid.UUID,
    ) -> TaskDetailResult | None:
        result = await self._record_repo.get_with_latest_snapshot(stable_id)
        if result is None:
            return None
        record, snapshot = result
        task_view = build_task_view(record, snapshot)
        revisions = await self._revision_repo.list_by_stable_id(stable_id)
        return TaskDetailResult(task=task_view, revisions=revisions)
