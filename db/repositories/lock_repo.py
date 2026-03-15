from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.processing_lock import ProcessingLock


class LockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire(self, lock_key: str, expires_at: datetime) -> bool:
        """
        Try to acquire a lock. Returns True if acquired, False if already held.
        Automatically cleans up expired locks before attempting.
        """
        now = datetime.now(tz=timezone.utc)
        # Remove expired locks
        await self._session.execute(
            delete(ProcessingLock).where(ProcessingLock.expires_at < now)
        )

        existing = await self._session.execute(
            select(ProcessingLock).where(ProcessingLock.lock_key == lock_key)
        )
        if existing.scalar_one_or_none() is not None:
            return False

        lock = ProcessingLock(lock_key=lock_key, expires_at=expires_at)
        self._session.add(lock)
        try:
            await self._session.flush()
            return True
        except Exception:
            return False

    async def release(self, lock_key: str) -> None:
        await self._session.execute(
            delete(ProcessingLock).where(ProcessingLock.lock_key == lock_key)
        )
        await self._session.flush()
