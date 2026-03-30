from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.base import Base


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


class TestPausePersistence:
    @pytest.mark.asyncio
    async def test_toggle_persists_to_db(self, db_session):
        from apps.api.services.review_pause import (
            _reset_cache,
            is_review_paused,
            load_pause_state,
            toggle_review_pause,
        )

        _reset_cache()
        assert is_review_paused() is False

        result = await toggle_review_pause(db_session)
        assert result is True
        assert is_review_paused() is True

        _reset_cache()
        assert is_review_paused() is False

        loaded = await load_pause_state(db_session)
        assert loaded is True
        assert is_review_paused() is True

    @pytest.mark.asyncio
    async def test_set_persists_to_db(self, db_session):
        from apps.api.services.review_pause import (
            _reset_cache,
            is_review_paused,
            load_pause_state,
            set_review_paused,
        )

        _reset_cache()

        await set_review_paused(db_session, True)
        assert is_review_paused() is True

        _reset_cache()
        loaded = await load_pause_state(db_session)
        assert loaded is True

        await set_review_paused(db_session, False)
        assert is_review_paused() is False

        _reset_cache()
        loaded = await load_pause_state(db_session)
        assert loaded is False

    @pytest.mark.asyncio
    async def test_load_returns_false_when_no_row(self, db_session):
        from apps.api.services.review_pause import _reset_cache, load_pause_state

        _reset_cache()
        loaded = await load_pause_state(db_session)
        assert loaded is False

    @pytest.mark.asyncio
    async def test_toggle_twice_returns_to_unpaused(self, db_session):
        from apps.api.services.review_pause import (
            _reset_cache,
            is_review_paused,
            toggle_review_pause,
        )

        _reset_cache()

        await toggle_review_pause(db_session)
        assert is_review_paused() is True

        await toggle_review_pause(db_session)
        assert is_review_paused() is False

    @pytest.mark.asyncio
    async def test_cache_survives_without_reload(self, db_session):
        from apps.api.services.review_pause import (
            _reset_cache,
            is_review_paused,
            toggle_review_pause,
        )

        _reset_cache()
        await toggle_review_pause(db_session)
        assert is_review_paused() is True
        assert is_review_paused() is True
