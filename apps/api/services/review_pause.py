from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.app_setting_repo import AppSettingRepository

_PAUSE_KEY = "review_paused"
_PAUSE_TRUE = "true"
_PAUSE_FALSE = "false"

_cached_paused: bool | None = None


def is_review_paused() -> bool:
    if _cached_paused is None:
        return False
    return _cached_paused


async def load_pause_state(session: AsyncSession) -> bool:
    global _cached_paused
    repo = AppSettingRepository(session)
    val = await repo.get(_PAUSE_KEY, _PAUSE_FALSE)
    _cached_paused = val == _PAUSE_TRUE
    return _cached_paused


async def toggle_review_pause(session: AsyncSession) -> bool:
    global _cached_paused
    repo = AppSettingRepository(session)
    current = await repo.get(_PAUSE_KEY, _PAUSE_FALSE)
    new_paused = current != _PAUSE_TRUE
    await repo.set(_PAUSE_KEY, _PAUSE_TRUE if new_paused else _PAUSE_FALSE)
    await session.commit()
    _cached_paused = new_paused
    return new_paused


async def set_review_paused(session: AsyncSession, paused: bool) -> None:
    global _cached_paused
    repo = AppSettingRepository(session)
    await repo.set(_PAUSE_KEY, _PAUSE_TRUE if paused else _PAUSE_FALSE)
    await session.commit()
    _cached_paused = paused


def _reset_cache() -> None:
    global _cached_paused
    _cached_paused = None
