"""
Daily review service - generates and sends the daily review summary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.telegram_service import TelegramService
from core.domain import notes_codec
from core.domain.enums import TaskRecordState, WorkflowStatus
from db.models.daily_review_snapshot import DailyReviewSnapshot
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot
from db.repositories.daily_review_repo import DailyReviewRepository

logger = get_logger(__name__)

STALE_THRESHOLD_DAYS = 3
WAITING_THRESHOLD_DAYS = 2
TOP_ACTIVE_LIMIT = 10


def _extract_meta(snapshot: TaskSnapshot | None) -> dict:
    """Extract metadata from snapshot payload via notes codec."""
    if snapshot is None:
        return {}
    payload = snapshot.payload or {}
    notes_text = payload.get("notes", "")
    meta = notes_codec.parse(notes_text) or {}
    return meta


def _title_from(snapshot: TaskSnapshot | None, meta: dict) -> str:
    """Get the best title for display."""
    normalized = meta.get("normalized_title")
    if normalized:
        return normalized
    if snapshot and snapshot.payload:
        return snapshot.payload.get("title", "")
    return ""


class DailyReviewService:
    def __init__(
        self,
        session: AsyncSession,
        telegram: TelegramService,
        llm: LLMService,
    ) -> None:
        self._session = session
        self._telegram = telegram
        self._llm = llm

    async def _list_active_records(
        self, limit: int | None = None
    ) -> list[tuple[TaskRecord, TaskSnapshot | None]]:
        """List active task records with their latest snapshots."""
        stmt = (
            select(TaskRecord, TaskSnapshot)
            .outerjoin(
                TaskSnapshot,
                (TaskSnapshot.stable_id == TaskRecord.stable_id) & (TaskSnapshot.is_latest == True),  # noqa: E712
            )
            .where(TaskRecord.state == TaskRecordState.ACTIVE.value)
            .order_by(TaskRecord.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def _list_by_workflow_status(
        self, status: WorkflowStatus
    ) -> list[tuple[TaskRecord, TaskSnapshot | None]]:
        """List task records by workflow status with their latest snapshots."""
        stmt = (
            select(TaskRecord, TaskSnapshot)
            .outerjoin(
                TaskSnapshot,
                (TaskSnapshot.stable_id == TaskRecord.stable_id) & (TaskSnapshot.is_latest == True),  # noqa: E712
            )
            .where(TaskRecord.processing_status == status.value)
            .order_by(TaskRecord.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def generate_and_send(self) -> DailyReviewSnapshot:
        review_repo = DailyReviewRepository(self._session)

        now = datetime.now(tz=timezone.utc)
        stale_cutoff = now - timedelta(days=STALE_THRESHOLD_DAYS)
        waiting_cutoff = now - timedelta(days=WAITING_THRESHOLD_DAYS)

        def _to_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        active_rows = await self._list_active_records(limit=TOP_ACTIVE_LIMIT)
        pending_rows = await self._list_by_workflow_status(WorkflowStatus.AWAITING_REVIEW)
        applied_rows = await self._list_by_workflow_status(WorkflowStatus.APPLIED)

        waiting_items: list[tuple[str, str]] = []
        commitments: list[tuple[str, str]] = []
        stale_tasks: list[tuple[str, str]] = []

        for record, snapshot in applied_rows:
            meta = _extract_meta(snapshot)
            kind = meta.get("kind") or (
                snapshot.payload.get("kind") if snapshot and snapshot.payload else None
            )
            title = _title_from(snapshot, meta)

            if (
                kind == "waiting"
                and record.created_at is not None
                and _to_utc(record.created_at) < waiting_cutoff
            ):
                waiting_items.append((str(record.stable_id), title))

            if kind == "commitment":
                commitments.append((str(record.stable_id), title))

            if record.created_at is not None and _to_utc(record.created_at) < stale_cutoff:
                stale_tasks.append((str(record.stable_id), title))

        payload: dict = {
            "generated_at": now.isoformat(),
            "active_tasks": [
                {
                    "id": str(record.stable_id),
                    "title": _title_from(snapshot, _extract_meta(snapshot)),
                }
                for record, snapshot in active_rows
            ],
            "waiting_items": [{"id": id_, "title": title} for id_, title in waiting_items],
            "commitments": [{"id": id_, "title": title} for id_, title in commitments],
            "stale_tasks": [{"id": id_, "title": title} for id_, title in stale_tasks],
            "pending_proposals": len(pending_rows),
        }

        summary = self._llm.generate_daily_review(payload)

        # Prepend header
        header = f"📅 <b>Daily Review — {now.strftime('%B %d, %Y')}</b>\n\n"
        full_summary = header + summary

        snapshot_record = DailyReviewSnapshot(
            id=uuid.uuid4(),
            summary_text=full_summary,
            payload_json=payload,
        )
        snapshot_record = await review_repo.create(snapshot_record)
        await self._session.commit()

        await self._telegram.send_text(full_summary)

        logger.info(
            "daily_review_sent",
            snapshot_id=str(snapshot_record.id),
            active_count=len(active_rows),
            waiting_count=len(waiting_items),
        )
        return snapshot_record
