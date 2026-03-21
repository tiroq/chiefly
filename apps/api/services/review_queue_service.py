from __future__ import annotations

from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_item_repo import TaskItemRepository

logger = get_logger(__name__)


class QueueStatus(TypedDict):
    has_active: bool
    total_queued: int
    items: list[str]


class ReviewQueueService:
    def __init__(
        self,
        session: AsyncSession,
        telegram: TelegramService,
    ) -> None:
        self._session = session
        self._telegram = telegram

    async def send_next(self) -> bool:
        session_repo = ReviewSessionRepository(self._session)

        if await session_repo.has_active_review():
            return False

        next_item = await session_repo.get_next_queued()
        if next_item is None:
            return False

        task_repo = TaskItemRepository(self._session)
        task = await task_repo.get_by_id(next_item.task_item_id)
        if task is None:
            logger.warning("queued_review_task_missing", task_item_id=str(next_item.task_item_id))
            next_item.status = "resolved"
            await session_repo.save(next_item)
            await self._session.commit()
            return await self.send_next()

        project_repo = ProjectRepository(self._session)
        project = await project_repo.get_by_id(task.project_id) if task.project_id else None

        try:
            kind = TaskKind(task.kind) if task.kind else TaskKind.TASK
        except ValueError:
            kind = TaskKind.TASK

        try:
            confidence = (
                ConfidenceBand(task.confidence_band)
                if task.confidence_band
                else ConfidenceBand.MEDIUM
            )
        except ValueError:
            confidence = ConfidenceBand.MEDIUM

        classification = TaskClassificationResult(
            kind=kind,
            normalized_title=task.normalized_title or task.raw_text,
            confidence=confidence,
            next_action=task.next_action,
            due_hint=task.due_hint,
        )

        msg_id = await self._telegram.send_proposal(
            task_id=str(task.id),
            raw_text=task.raw_text,
            classification=classification,
            project_name=project.name if project else None,
        )

        next_item.status = "pending"
        next_item.telegram_message_id = msg_id
        await session_repo.save(next_item)
        await self._session.commit()

        queued_count = await session_repo.count_queued()
        if queued_count > 0:
            await self._telegram.send_text(
                f"📬 {queued_count} more item(s) in queue. Use /next after reviewing."
            )

        logger.info("review_sent", task_item_id=str(task.id), queued_remaining=queued_count)
        return True

    async def get_queue_status(self) -> QueueStatus:
        session_repo = ReviewSessionRepository(self._session)
        task_repo = TaskItemRepository(self._session)

        queued_sessions = await session_repo.list_queued(limit=10)
        has_active = await session_repo.has_active_review()
        total_queued = await session_repo.count_queued()

        items = []
        for qs in queued_sessions:
            task = await task_repo.get_by_id(qs.task_item_id)
            if task:
                items.append(task.normalized_title or task.raw_text)

        return {
            "has_active": has_active,
            "total_queued": total_queued,
            "items": items,
        }
