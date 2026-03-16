import uuid

from sqlalchemy import select
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

    async def get_pending_edit_by_chat(
        self, chat_id: str
    ) -> TelegramReviewSession | None:
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
