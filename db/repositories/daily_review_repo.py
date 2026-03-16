from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.daily_review_snapshot import DailyReviewSnapshot


class DailyReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self) -> DailyReviewSnapshot | None:
        result = await self._session.execute(
            select(DailyReviewSnapshot)
            .order_by(DailyReviewSnapshot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, snapshot: DailyReviewSnapshot) -> DailyReviewSnapshot:
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot
