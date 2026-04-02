from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.review_pause import is_review_paused
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import ConfidenceBand, ReviewSessionStatus, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository

logger = get_logger(__name__)


class SendNextResult(StrEnum):
    SENT = "sent"
    PAUSED = "paused"
    ACTIVE_EXISTS = "active_exists"
    QUEUE_EMPTY = "queue_empty"


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

    async def send_next(self) -> SendNextResult:
        """Send the next queued proposal to Telegram.

        Checks pause state and active reviews before sending.
        Returns the outcome as a SendNextResult enum value.

        Returns:
            SendNextResult: The result of the send operation (SENT, PAUSED, etc.).
        """
        if is_review_paused():
            logger.info("review_queue_paused_skip_send_next")
            return SendNextResult.PAUSED

        session_repo = ReviewSessionRepository(self._session)

        if await session_repo.has_active_review():
            return SendNextResult.ACTIVE_EXISTS

        next_item = await session_repo.get_next_queued_for_update()
        if next_item is None:
            next_item = await session_repo.get_next_send_failed_for_update()
        if next_item is None:
            return SendNextResult.QUEUE_EMPTY

        proposed = next_item.proposed_changes or {}
        if not proposed:
            logger.warning(
                "queued_review_missing_proposed_changes",
                session_id=str(next_item.id),
            )
            next_item.status = ReviewSessionStatus.RESOLVED.value
            await session_repo.save(next_item)
            await self._session.commit()
            return await self.send_next()

        try:
            kind = TaskKind(proposed.get("kind", "task"))
        except ValueError:
            kind = TaskKind.TASK

        try:
            confidence = ConfidenceBand(proposed.get("confidence", "medium"))
        except ValueError:
            confidence = ConfidenceBand.MEDIUM

        classification = TaskClassificationResult(
            kind=kind,
            normalized_title=proposed.get("normalized_title", ""),
            confidence=confidence,
            next_action=proposed.get("next_action"),
            due_hint=proposed.get("due_hint"),
        )

        raw_text = ""
        if next_item.stable_id:
            snapshot_repo = TaskSnapshotRepository(self._session)
            snapshot = await snapshot_repo.get_latest_by_stable_id(next_item.stable_id)
            if snapshot and snapshot.payload:
                raw_text = snapshot.payload.get("title", "")
        if not raw_text:
            raw_text = classification.normalized_title

        task_id_for_callback = (
            str(next_item.stable_id) if next_item.stable_id else str(next_item.id)
        )

        try:
            msg_id = await self._telegram.send_proposal(
                task_id=task_id_for_callback,
                raw_text=raw_text,
                classification=classification,
                project_name=proposed.get("project_name"),
                queue_position=1,
            )
        except Exception:
            next_item.status = ReviewSessionStatus.SEND_FAILED.value
            await session_repo.save(next_item)
            await self._session.commit()
            logger.error(
                "review_send_proposal_failed",
                session_id=str(next_item.id),
                stable_id=str(next_item.stable_id),
            )
            raise

        next_item.status = ReviewSessionStatus.ACTIVE.value
        next_item.telegram_message_id = msg_id
        await session_repo.save(next_item)
        await self._session.commit()

        queued_count = await session_repo.count_queued()
        if queued_count > 0:
            await self._telegram.send_text(
                f"📬 {queued_count} more item(s) in queue. Use /next after reviewing."
            )

        logger.info(
            "review_sent",
            stable_id=str(next_item.stable_id),
            session_id=str(next_item.id),
            queued_remaining=queued_count,
        )
        return SendNextResult.SENT

    async def get_queue_status(self) -> QueueStatus:
        """Retrieve the current status of the review queue.

        Includes information about active reviews, total queued items,
        and titles of the next few items in the queue.

        Returns:
            QueueStatus: A dictionary containing queue status details.
        """
        session_repo = ReviewSessionRepository(self._session)

        queued_sessions = await session_repo.list_queued(limit=10)
        has_active = await session_repo.has_active_review()
        total_queued = await session_repo.count_queued()

        items = []
        for qs in queued_sessions:
            proposed = qs.proposed_changes or {}
            title = proposed.get("normalized_title", "")
            if not title and qs.stable_id:
                snapshot_repo = TaskSnapshotRepository(self._session)
                snapshot = await snapshot_repo.get_latest_by_stable_id(qs.stable_id)
                if snapshot and snapshot.payload:
                    title = snapshot.payload.get("title", "")
            if title:
                items.append(title)

        return {
            "has_active": has_active,
            "total_queued": total_queued,
            "items": items,
        }
