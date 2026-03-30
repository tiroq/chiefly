from __future__ import annotations
# pyright: reportAny=false, reportExplicitAny=false

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from core.domain.enums import ProcessingReason, ProcessingStatus
from db.base import Base
from db.models.source_task import SourceTask
from db.repositories.processing_queue_repo import ProcessingQueueRepository


SessionFactory = async_sessionmaker[AsyncSession]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(  # pyright: ignore[reportUnusedFunction]
    _type: Any, _compiler: Any, **_kwargs: Any
) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(  # pyright: ignore[reportUnusedFunction]
    _type: Any, _compiler: Any, **_kwargs: Any
) -> str:
    return "INTEGER"


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db_session(db_session_factory: SessionFactory) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session


async def _create_source_task(session: AsyncSession, *, google_task_id: str) -> SourceTask:
    source_task = SourceTask(
        id=uuid.uuid4(),
        google_task_id=google_task_id,
        google_tasklist_id="inbox",
        title_raw=f"raw-{google_task_id}",
        notes_raw=None,
        google_status="needsAction",
        google_updated_at=datetime.now(tz=timezone.utc),
        content_hash="a" * 64,
        is_deleted=False,
    )
    session.add(source_task)
    await session.flush()
    return source_task


def _is_sqlite(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "sqlite"


async def _claim_once(db_session_factory: SessionFactory, worker_name: str) -> uuid.UUID | None:
    async with db_session_factory() as session:
        repo = ProcessingQueueRepository(session)
        claimed = await repo.claim_next(locked_by=worker_name)
        await session.commit()
        return claimed.id if claimed is not None else None


class TestProcessingQueueConcurrentClaim:
    @pytest.mark.asyncio
    async def test_two_claims_two_pending_entries(
        self, db_session: AsyncSession, db_session_factory: SessionFactory
    ) -> None:
        source_task_1 = await _create_source_task(db_session, google_task_id="g-concurrent-1")
        source_task_2 = await _create_source_task(db_session, google_task_id="g-concurrent-2")

        queue_repo = ProcessingQueueRepository(db_session)
        _ = await queue_repo.enqueue(source_task_1.id, ProcessingReason.NEW_TASK)
        _ = await queue_repo.enqueue(source_task_2.id, ProcessingReason.NEW_TASK)
        await db_session.commit()

        is_sqlite = _is_sqlite(db_session)
        if is_sqlite:
            claim_a = await _claim_once(db_session_factory, "worker-a")
            claim_b = await _claim_once(db_session_factory, "worker-b")
        else:
            claim_a, claim_b = await asyncio.gather(
                _claim_once(db_session_factory, "worker-a"),
                _claim_once(db_session_factory, "worker-b"),
            )

        assert claim_a is not None
        assert claim_b is not None
        assert claim_a != claim_b

    @pytest.mark.asyncio
    async def test_two_claims_one_pending_entry(
        self, db_session: AsyncSession, db_session_factory: SessionFactory
    ) -> None:
        source_task = await _create_source_task(db_session, google_task_id="g-concurrent-single")

        queue_repo = ProcessingQueueRepository(db_session)
        enqueued = await queue_repo.enqueue(source_task.id, ProcessingReason.NEW_TASK)
        await db_session.commit()

        is_sqlite = _is_sqlite(db_session)
        if is_sqlite:
            claim_a = await _claim_once(db_session_factory, "worker-a")
            claim_b = await _claim_once(db_session_factory, "worker-b")
        else:
            claim_a, claim_b = await asyncio.gather(
                _claim_once(db_session_factory, "worker-a"),
                _claim_once(db_session_factory, "worker-b"),
            )

        claims = {claim_a, claim_b}
        assert enqueued.id in claims
        assert None in claims

    @pytest.mark.asyncio
    async def test_claim_next_skips_older_when_newer_exists_for_same_source_task(
        self, db_session: AsyncSession
    ) -> None:
        source_task = await _create_source_task(db_session, google_task_id="g-latest-only")

        queue_repo = ProcessingQueueRepository(db_session)
        older = await queue_repo.enqueue(source_task.id, ProcessingReason.NEW_TASK)
        newer = await queue_repo.enqueue(source_task.id, ProcessingReason.SOURCE_CHANGED)

        now = datetime.now(tz=timezone.utc)
        older.created_at = now - timedelta(seconds=5)
        newer.created_at = now
        db_session.add(older)
        db_session.add(newer)
        await db_session.commit()

        claimed = await queue_repo.claim_next(locked_by="worker-latest")
        await db_session.commit()

        assert claimed is not None
        assert claimed.id == newer.id

        older_db = await queue_repo.get_by_id(older.id)
        newer_db = await queue_repo.get_by_id(newer.id)

        assert older_db is not None
        assert older_db.processing_status == ProcessingStatus.SKIPPED
        assert older_db.completed_at is not None

        assert newer_db is not None
        assert newer_db.processing_status == ProcessingStatus.LOCKED
        assert newer_db.locked_by == "worker-latest"
