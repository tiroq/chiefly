"""
Idempotency service - prevents duplicate processing of the same task.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.domain.exceptions import LockAcquisitionError
from db.repositories.lock_repo import LockRepository

logger = get_logger(__name__)

LOCK_TTL_SECONDS = 300  # 5 minutes


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = LockRepository(session)

    async def acquire_lock(self, key: str) -> bool:
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=LOCK_TTL_SECONDS)
        acquired = await self._repo.acquire(key, expires_at)
        if not acquired:
            logger.info("lock_already_held", key=key)
        return acquired

    async def release_lock(self, key: str) -> None:
        await self._repo.release(key)

    async def require_lock(self, key: str) -> None:
        """Acquire lock or raise LockAcquisitionError."""
        if not await self.acquire_lock(key):
            raise LockAcquisitionError(f"Could not acquire lock: {key}")
