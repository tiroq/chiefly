"""
Integration tests for the daily review service.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import TaskRecordState, WorkflowStatus
from db.base import Base
from db.models import DailyReviewSnapshot, TaskRecord, TaskSnapshot


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
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


@pytest_asyncio.fixture
async def session_with_tasks(db_session):
    """Session pre-seeded with task records and latest snapshots."""
    now = datetime.now(tz=timezone.utc)
    records = [
        TaskRecord(
            stable_id=uuid.uuid4(),
            state=TaskRecordState.ACTIVE.value,
            processing_status=WorkflowStatus.APPLIED.value,
            created_at=now - timedelta(days=1),
        ),
        TaskRecord(
            stable_id=uuid.uuid4(),
            state=TaskRecordState.ACTIVE.value,
            processing_status=WorkflowStatus.APPLIED.value,
            created_at=now - timedelta(days=3),
        ),
        TaskRecord(
            stable_id=uuid.uuid4(),
            state=TaskRecordState.ACTIVE.value,
            processing_status=WorkflowStatus.AWAITING_REVIEW.value,
            created_at=now - timedelta(hours=2),
        ),
    ]

    for record in records:
        db_session.add(record)

    snapshots = [
        TaskSnapshot(
            id=1,
            stable_id=records[0].stable_id,
            tasklist_id="inbox",
            task_id="task-routed-1",
            payload={"title": "Prepare Q2 report", "notes": "", "kind": "task"},
            content_hash=hashlib.sha256("Prepare Q2 report|".encode()).hexdigest(),
            is_latest=True,
        ),
        TaskSnapshot(
            id=2,
            stable_id=records[1].stable_id,
            tasklist_id="inbox",
            task_id="task-routed-waiting",
            payload={
                "title": "Wait for Alex certificates",
                "notes": "",
                "kind": "waiting",
            },
            content_hash=hashlib.sha256("Wait for Alex certificates|".encode()).hexdigest(),
            is_latest=True,
        ),
        TaskSnapshot(
            id=3,
            stable_id=records[2].stable_id,
            tasklist_id="inbox",
            task_id="task-proposed-1",
            payload={"title": "Buy milk", "notes": "", "kind": "task"},
            content_hash=hashlib.sha256("Buy milk|".encode()).hexdigest(),
            is_latest=True,
        ),
    ]
    for snapshot in snapshots:
        db_session.add(snapshot)

    await db_session.commit()
    return db_session


@pytest.mark.asyncio
async def test_daily_review_generates_snapshot(session_with_tasks):
    """Daily review creates a DailyReviewSnapshot in the DB."""
    from apps.api.services.llm_service import LLMService
    from apps.api.services.review_service import DailyReviewService
    from apps.api.services.telegram_service import TelegramService
    from db.repositories.daily_review_repo import DailyReviewRepository

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_daily_review.return_value = "Summary text here"

    mock_tg = AsyncMock(spec=TelegramService)
    mock_tg.send_text.return_value = 99

    svc = DailyReviewService(
        session=session_with_tasks,
        telegram=mock_tg,
        llm=mock_llm,
    )
    snapshot = await svc.generate_and_send()

    assert snapshot is not None
    assert snapshot.id is not None
    assert "Daily Review" in snapshot.summary_text
    assert isinstance(snapshot.payload_json, dict)
    assert "active_tasks" in snapshot.payload_json

    mock_tg.send_text.assert_called_once()
    mock_llm.generate_daily_review.assert_called_once()

    # Verify persisted in DB
    repo = DailyReviewRepository(session_with_tasks)
    latest = await repo.get_latest()
    assert latest is not None
    assert latest.id == snapshot.id


@pytest.mark.asyncio
async def test_daily_review_payload_structure(session_with_tasks):
    """Verify the payload JSON has expected structure."""
    from apps.api.services.llm_service import LLMService
    from apps.api.services.review_service import DailyReviewService
    from apps.api.services.telegram_service import TelegramService

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_daily_review.return_value = "Test summary"

    mock_tg = AsyncMock(spec=TelegramService)
    mock_tg.send_text.return_value = 1

    svc = DailyReviewService(
        session=session_with_tasks,
        telegram=mock_tg,
        llm=mock_llm,
    )
    snapshot = await svc.generate_and_send()

    payload = snapshot.payload_json
    assert "generated_at" in payload
    assert "active_tasks" in payload
    assert "waiting_items" in payload
    assert "commitments" in payload
    assert "stale_tasks" in payload
    assert "pending_proposals" in payload
    assert isinstance(payload["pending_proposals"], int)
    assert payload["pending_proposals"] == 1


@pytest.mark.asyncio
async def test_empty_inbox_review(db_session):
    """Daily review works when there are no tasks."""
    from apps.api.services.llm_service import LLMService
    from apps.api.services.review_service import DailyReviewService
    from apps.api.services.telegram_service import TelegramService

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_daily_review.return_value = "Nothing to review today."

    mock_tg = AsyncMock(spec=TelegramService)
    mock_tg.send_text.return_value = 1

    svc = DailyReviewService(
        session=db_session,
        telegram=mock_tg,
        llm=mock_llm,
    )
    snapshot = await svc.generate_and_send()
    assert snapshot is not None
    assert snapshot.payload_json["active_tasks"] == []
