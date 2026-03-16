"""
Daily review service - generates and sends the daily review summary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import TaskKind, TaskStatus
from db.models.daily_review_snapshot import DailyReviewSnapshot
from db.repositories.daily_review_repo import DailyReviewRepository
from db.repositories.task_item_repo import TaskItemRepository

logger = get_logger(__name__)

STALE_THRESHOLD_DAYS = 3
WAITING_THRESHOLD_DAYS = 2
TOP_ACTIVE_LIMIT = 10


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

    async def generate_and_send(self) -> DailyReviewSnapshot:
        task_repo = TaskItemRepository(self._session)
        review_repo = DailyReviewRepository(self._session)

        now = datetime.now(tz=timezone.utc)
        stale_cutoff = now - timedelta(days=STALE_THRESHOLD_DAYS)
        waiting_cutoff = now - timedelta(days=WAITING_THRESHOLD_DAYS)

        def _to_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        # Collect routed/active tasks
        active_tasks = await task_repo.list_active_routed(limit=TOP_ACTIVE_LIMIT)

        # Collect all proposed/confirmed for analysis
        proposed = await task_repo.list_by_status(TaskStatus.PROPOSED)
        routed = await task_repo.list_by_status(TaskStatus.ROUTED)

        waiting_items = [
            t for t in routed
            if t.kind == TaskKind.WAITING
            and t.created_at is not None
            and _to_utc(t.created_at) < waiting_cutoff
        ]

        commitments = [
            t for t in routed
            if t.kind == TaskKind.COMMITMENT
        ]

        stale_tasks = [
            t for t in routed
            if t.created_at is not None
            and _to_utc(t.created_at) < stale_cutoff
        ]

        payload: dict = {
            "generated_at": now.isoformat(),
            "active_tasks": [
                {"id": str(t.id), "title": t.normalized_title or t.raw_text}
                for t in active_tasks
            ],
            "waiting_items": [
                {"id": str(t.id), "title": t.normalized_title or t.raw_text}
                for t in waiting_items
            ],
            "commitments": [
                {"id": str(t.id), "title": t.normalized_title or t.raw_text}
                for t in commitments
            ],
            "stale_tasks": [
                {"id": str(t.id), "title": t.normalized_title or t.raw_text}
                for t in stale_tasks
            ],
            "pending_proposals": len(proposed),
        }

        summary = self._llm.generate_daily_review(payload)

        # Prepend header
        header = f"📅 <b>Daily Review — {now.strftime('%B %d, %Y')}</b>\n\n"
        full_summary = header + summary

        snapshot = DailyReviewSnapshot(
            id=uuid.uuid4(),
            summary_text=full_summary,
            payload_json=payload,
        )
        snapshot = await review_repo.create(snapshot)
        await self._session.commit()

        await self._telegram.send_text(full_summary)

        logger.info(
            "daily_review_sent",
            snapshot_id=str(snapshot.id),
            active_count=len(active_tasks),
            waiting_count=len(waiting_items),
        )
        return snapshot
