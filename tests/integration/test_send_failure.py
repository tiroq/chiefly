from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ConfidenceBand, TaskKind, WorkflowStatus
from db.base import Base
from db.models import TaskRecord, TelegramReviewSession


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


class TestTelegramSendFailure:
    @pytest.mark.asyncio
    async def test_send_next_marks_send_failed_on_telegram_error(self, db_session):
        from apps.api.services.review_queue_service import ReviewQueueService
        from db.repositories.review_session_repo import ReviewSessionRepository

        stable_id = uuid.uuid4()
        record = TaskRecord(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="g-001",
            state="active",
            processing_status=WorkflowStatus.AWAITING_REVIEW,
        )
        db_session.add(record)

        session = TelegramReviewSession(
            id=uuid.uuid4(),
            stable_id=stable_id,
            telegram_chat_id="chat-123",
            telegram_message_id=0,
            status="queued",
            proposed_changes={
                "normalized_title": "Test task",
                "kind": "task",
                "confidence": "high",
            },
        )
        db_session.add(session)
        await db_session.commit()

        mock_telegram = AsyncMock()
        mock_telegram.send_proposal = AsyncMock(side_effect=RuntimeError("Telegram API down"))

        svc = ReviewQueueService(db_session, mock_telegram)

        with pytest.raises(RuntimeError, match="Telegram API down"):
            await svc.send_next()

        repo = ReviewSessionRepository(db_session)
        updated = await repo.get_by_id(session.id)
        assert updated is not None
        assert updated.status == "send_failed"

    @pytest.mark.asyncio
    async def test_send_next_retries_send_failed_sessions(self, db_session):
        from apps.api.services.review_pause import _reset_cache, set_review_paused
        from apps.api.services.review_queue_service import ReviewQueueService
        from db.repositories.review_session_repo import ReviewSessionRepository

        _reset_cache()

        stable_id = uuid.uuid4()
        record = TaskRecord(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="g-001",
            state="active",
            processing_status=WorkflowStatus.AWAITING_REVIEW,
        )
        db_session.add(record)

        from db.models.task_snapshot import TaskSnapshot

        snapshot = TaskSnapshot(
            id=1,
            tasklist_id="inbox",
            task_id="g-001",
            payload={"title": "Test task"},
            content_hash="abc123",
            stable_id=stable_id,
        )
        db_session.add(snapshot)

        session = TelegramReviewSession(
            id=uuid.uuid4(),
            stable_id=stable_id,
            telegram_chat_id="chat-123",
            telegram_message_id=0,
            status="send_failed",
            proposed_changes={
                "normalized_title": "Test task",
                "kind": "task",
                "confidence": "high",
            },
        )
        db_session.add(session)
        await db_session.commit()

        mock_telegram = AsyncMock()
        mock_telegram.send_proposal = AsyncMock(return_value=42)
        mock_telegram.send_text = AsyncMock(return_value=43)

        svc = ReviewQueueService(db_session, mock_telegram)
        result = await svc.send_next()

        assert result is True
        mock_telegram.send_proposal.assert_awaited_once()

        repo = ReviewSessionRepository(db_session)
        updated = await repo.get_by_id(session.id)
        assert updated is not None
        assert updated.status == "pending"
        assert updated.telegram_message_id == 42

    @pytest.mark.asyncio
    async def test_processing_worker_send_failure_creates_system_event(self, db_session):
        from db.models.system_event import SystemEvent
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.system_event_repo import SystemEventRepo

        stable_id = uuid.uuid4()
        record = TaskRecord(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="g-001",
            state="active",
            processing_status=WorkflowStatus.AWAITING_REVIEW,
        )
        db_session.add(record)

        review_id = uuid.uuid4()
        session = TelegramReviewSession(
            id=review_id,
            stable_id=stable_id,
            telegram_chat_id="chat-123",
            telegram_message_id=0,
            status="queued",
            proposed_changes={
                "normalized_title": "Test task",
                "kind": "task",
                "confidence": "high",
            },
        )
        db_session.add(session)
        await db_session.commit()

        send_err = RuntimeError("Connection refused")
        session.status = "send_failed"
        review_repo = ReviewSessionRepository(db_session)
        await review_repo.save(session)

        event = SystemEvent(
            event_type="telegram_send_failed",
            severity="error",
            subsystem="processing",
            stable_id=stable_id,
            message=f"Telegram send failed after review session creation: {send_err}",
        )
        event_repo = SystemEventRepo(db_session)
        await event_repo.create(event)
        await db_session.commit()

        updated = await review_repo.get_by_id(review_id)
        assert updated is not None
        assert updated.status == "send_failed"

        events = await event_repo.list_events(event_type="telegram_send_failed")
        assert len(events) == 1
        assert events[0].stable_id == stable_id
        assert events[0].severity == "error"
        assert "Connection refused" in events[0].message
