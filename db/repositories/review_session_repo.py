import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import ReviewSessionStatus
from db.models.telegram_review_session import TelegramReviewSession


class ReviewSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, session_id: uuid.UUID) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession).where(TelegramReviewSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_stable_id(self, stable_id: uuid.UUID) -> TelegramReviewSession | None:
        """Return the session currently active (visible) in Telegram for this task."""
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(
                TelegramReviewSession.stable_id == stable_id,
                TelegramReviewSession.status == ReviewSessionStatus.ACTIVE.value,
            )
            .order_by(TelegramReviewSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_reviewable_by_stable_id(
        self, stable_id: uuid.UUID
    ) -> TelegramReviewSession | None:
        """Return the most recent reviewable (queued or active) session for this task."""
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(
                TelegramReviewSession.stable_id == stable_id,
                TelegramReviewSession.status.in_([
                    ReviewSessionStatus.QUEUED.value,
                    ReviewSessionStatus.ACTIVE.value,
                ]),
            )
            .order_by(TelegramReviewSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, review_session: TelegramReviewSession) -> TelegramReviewSession:
        self._session.add(review_session)
        await self._session.flush()
        return review_session

    async def save(self, review_session: TelegramReviewSession) -> TelegramReviewSession:
        self._session.add(review_session)
        await self._session.flush()
        return review_session

    async def count_pending(self) -> int:
        """Count sessions that are unresolved (queued + active)."""
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status.in_([
                    ReviewSessionStatus.QUEUED.value,
                    ReviewSessionStatus.ACTIVE.value,
                ])
            )
        )
        return result.scalar() or 0

    async def count_queued(self) -> int:
        """Count sessions waiting in the review queue (not yet sent to Telegram)."""
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status == ReviewSessionStatus.QUEUED.value
            )
        )
        return result.scalar() or 0

    async def get_next_queued(self) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == ReviewSessionStatus.QUEUED.value)
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_next_queued_for_update(self) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == ReviewSessionStatus.QUEUED.value)
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def get_next_send_failed_for_update(self) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == ReviewSessionStatus.SEND_FAILED.value)
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def has_active_review(self) -> bool:
        """Return True if any session is currently active (visible) in Telegram."""
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status == ReviewSessionStatus.ACTIVE.value
            )
        )
        return (result.scalar() or 0) > 0

    async def list_queued(self, limit: int = 10) -> list[TelegramReviewSession]:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == ReviewSessionStatus.QUEUED.value)
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_skipped(self, limit: int = 20) -> list[TelegramReviewSession]:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == ReviewSessionStatus.SKIPPED.value)
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: str) -> int:
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status == status
            )
        )
        return result.scalar() or 0
