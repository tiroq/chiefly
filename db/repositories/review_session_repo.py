import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.telegram_review_session import TelegramReviewSession


class ReviewSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, session_id: uuid.UUID) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession).where(TelegramReviewSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_task(self, task_item_id: uuid.UUID) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(
                TelegramReviewSession.task_item_id == task_item_id,
                TelegramReviewSession.status == "pending",
            )
            .order_by(TelegramReviewSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pending_edit_by_chat(self, chat_id: str) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(
                TelegramReviewSession.telegram_chat_id == chat_id,
                TelegramReviewSession.status == "awaiting_edit",
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
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status.in_(["queued", "pending"])
            )
        )
        return result.scalar() or 0

    async def count_queued(self) -> int:
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status == "queued"
            )
        )
        return result.scalar() or 0

    async def get_next_queued(self) -> TelegramReviewSession | None:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == "queued")
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_active_review(self) -> bool:
        result = await self._session.execute(
            select(func.count(TelegramReviewSession.id)).where(
                TelegramReviewSession.status.in_(["pending", "awaiting_edit"])
            )
        )
        return (result.scalar() or 0) > 0

    async def list_queued(self, limit: int = 10) -> list[TelegramReviewSession]:
        result = await self._session.execute(
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status == "queued")
            .order_by(TelegramReviewSession.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
