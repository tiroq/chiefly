"""
Integration tests for query semantics correctness.

These tests verify that repository methods return exactly the right items
for each pipeline stage — not more, not less.

Coverage:
  A. ProcessingQueueRepository — new counting/listing methods
  B. TaskRecordRepository — count_by_workflow_status
  C. ReviewSessionRepository — count_unresolved, get_active_review_session
  D. Buffer compatibility — AWAITING_REVIEW count for processing worker throttle
  E. Regression — no wrong-status items appear in wrong queries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from core.domain.enums import (
    ProcessingReason,
    ProcessingStatus,
    ReviewSessionStatus,
    TaskRecordState,
    WorkflowStatus,
)
from db.base import Base
from db.models.source_task import SourceTask
from db.models.task_record import TaskRecord
from db.models.telegram_review_session import TelegramReviewSession


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type: Any, _compiler: Any, **_kwargs: Any) -> str:
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(_type: Any, _compiler: Any, **_kwargs: Any) -> str:
    return "INTEGER"


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


async def _make_source_task(session: AsyncSession, *, suffix: str = "1") -> SourceTask:
    src = SourceTask(
        id=uuid.uuid4(),
        google_task_id=f"g-{suffix}",
        google_tasklist_id="inbox",
        title_raw=f"Task {suffix}",
        notes_raw=None,
        google_status="needsAction",
        google_updated_at=datetime.now(tz=timezone.utc),
        content_hash="a" * 64,
        is_deleted=False,
    )
    session.add(src)
    await session.flush()
    return src


async def _make_queue_entry(
    session: AsyncSession,
    source_task: SourceTask,
    status: ProcessingStatus = ProcessingStatus.PENDING,
    retry_count: int = 0,
) -> uuid.UUID:
    from db.repositories.processing_queue_repo import ProcessingQueueRepository

    repo = ProcessingQueueRepository(session)
    entry = await repo.enqueue(source_task.id, ProcessingReason.NEW_TASK)
    entry.processing_status = status.value
    entry.retry_count = retry_count
    if status in (ProcessingStatus.LOCKED, ProcessingStatus.PROCESSING):
        entry.locked_at = datetime.now(tz=timezone.utc)
        entry.locked_by = "test_worker"
    await session.flush()
    return entry.id


async def _make_task_record(
    session: AsyncSession,
    workflow_status: WorkflowStatus = WorkflowStatus.PENDING,
) -> TaskRecord:
    record = TaskRecord(
        stable_id=uuid.uuid4(),
        state=TaskRecordState.ACTIVE.value,
        processing_status=workflow_status.value,
    )
    session.add(record)
    await session.flush()
    return record


async def _make_review_session(
    session: AsyncSession,
    stable_id: uuid.UUID,
    status: ReviewSessionStatus = ReviewSessionStatus.QUEUED,
) -> TelegramReviewSession:
    rs = TelegramReviewSession(
        id=uuid.uuid4(),
        stable_id=stable_id,
        telegram_chat_id="12345",
        telegram_message_id=0,
        status=status.value,
        proposed_changes={},
    )
    session.add(rs)
    await session.flush()
    return rs


# ─────────────────────────────────────────────────────────────────────────────
# A. ProcessingQueueRepository — new counting/listing methods
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessingQueueQuerySemantics:
    @pytest.mark.asyncio
    async def test_count_in_progress_counts_locked_and_processing(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="ip-1")
        src2 = await _make_source_task(db_session, suffix="ip-2")
        src3 = await _make_source_task(db_session, suffix="ip-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.LOCKED)
        await _make_queue_entry(db_session, src2, ProcessingStatus.PROCESSING)
        await _make_queue_entry(db_session, src3, ProcessingStatus.PENDING)
        await db_session.commit()

        assert await repo.count_in_progress() == 2

    @pytest.mark.asyncio
    async def test_count_in_progress_excludes_pending_and_failed(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="exl-1")
        src2 = await _make_source_task(db_session, suffix="exl-2")

        await _make_queue_entry(db_session, src1, ProcessingStatus.PENDING)
        await _make_queue_entry(db_session, src2, ProcessingStatus.FAILED)
        await db_session.commit()

        assert await repo.count_in_progress() == 0

    @pytest.mark.asyncio
    async def test_count_failed_counts_only_terminal_failures(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="fail-1")
        src2 = await _make_source_task(db_session, suffix="fail-2")
        src3 = await _make_source_task(db_session, suffix="fail-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.FAILED)
        await _make_queue_entry(db_session, src2, ProcessingStatus.FAILED)
        await _make_queue_entry(db_session, src3, ProcessingStatus.PENDING)
        await db_session.commit()

        assert await repo.count_failed() == 2

    @pytest.mark.asyncio
    async def test_count_failed_excludes_pending_and_in_progress(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="fex-1")
        src2 = await _make_source_task(db_session, suffix="fex-2")

        await _make_queue_entry(db_session, src1, ProcessingStatus.PENDING)
        await _make_queue_entry(db_session, src2, ProcessingStatus.LOCKED)
        await db_session.commit()

        assert await repo.count_failed() == 0

    @pytest.mark.asyncio
    async def test_list_failed_returns_only_failed_entries(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="lf-1")
        src2 = await _make_source_task(db_session, suffix="lf-2")
        src3 = await _make_source_task(db_session, suffix="lf-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.FAILED)
        await _make_queue_entry(db_session, src2, ProcessingStatus.PENDING)
        await _make_queue_entry(db_session, src3, ProcessingStatus.FAILED)
        await db_session.commit()

        failed = await repo.list_failed()
        assert len(failed) == 2
        assert all(e.processing_status == ProcessingStatus.FAILED.value for e in failed)

    @pytest.mark.asyncio
    async def test_list_in_progress_returns_locked_and_processing(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="lip-1")
        src2 = await _make_source_task(db_session, suffix="lip-2")
        src3 = await _make_source_task(db_session, suffix="lip-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.LOCKED)
        await _make_queue_entry(db_session, src2, ProcessingStatus.PROCESSING)
        await _make_queue_entry(db_session, src3, ProcessingStatus.PENDING)
        await db_session.commit()

        in_progress = await repo.list_in_progress()
        statuses = {e.processing_status for e in in_progress}
        assert ProcessingStatus.PENDING.value not in statuses
        assert ProcessingStatus.FAILED.value not in statuses
        assert len(in_progress) == 2

    @pytest.mark.asyncio
    async def test_list_retry_pending_returns_only_retried_items(self, db_session):
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="rp-1")
        src2 = await _make_source_task(db_session, suffix="rp-2")
        src3 = await _make_source_task(db_session, suffix="rp-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.PENDING, retry_count=2)
        await _make_queue_entry(db_session, src2, ProcessingStatus.PENDING, retry_count=0)
        await _make_queue_entry(db_session, src3, ProcessingStatus.FAILED, retry_count=3)
        await db_session.commit()

        retry = await repo.list_retry_pending()
        assert len(retry) == 1
        assert retry[0].retry_count == 2
        assert retry[0].processing_status == ProcessingStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_list_retry_pending_excludes_terminal_failures(self, db_session):
        """FAILED entries are terminal — they must never appear in retry_pending."""
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src = await _make_source_task(db_session, suffix="rtf-1")
        await _make_queue_entry(db_session, src, ProcessingStatus.FAILED, retry_count=5)
        await db_session.commit()

        retry = await repo.list_retry_pending()
        assert retry == []

    @pytest.mark.asyncio
    async def test_count_pending_unchanged_semantics(self, db_session):
        """count_pending() still means PENDING only — not LOCKED/PROCESSING."""
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src1 = await _make_source_task(db_session, suffix="cp-1")
        src2 = await _make_source_task(db_session, suffix="cp-2")
        src3 = await _make_source_task(db_session, suffix="cp-3")

        await _make_queue_entry(db_session, src1, ProcessingStatus.PENDING)
        await _make_queue_entry(db_session, src2, ProcessingStatus.LOCKED)
        await _make_queue_entry(db_session, src3, ProcessingStatus.PROCESSING)
        await db_session.commit()

        assert await repo.count_pending() == 1


# ─────────────────────────────────────────────────────────────────────────────
# B. TaskRecordRepository — count_by_workflow_status
# ─────────────────────────────────────────────────────────────────────────────


class TestTaskRecordWorkflowStatusQuery:
    @pytest.mark.asyncio
    async def test_count_awaiting_review_correct(self, db_session):
        """count_by_workflow_status(AWAITING_REVIEW) is the buffer depth signal."""
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        for _ in range(3):
            await _make_task_record(db_session, WorkflowStatus.AWAITING_REVIEW)
        for _ in range(2):
            await _make_task_record(db_session, WorkflowStatus.PENDING)
        await _make_task_record(db_session, WorkflowStatus.APPLIED)
        await db_session.commit()

        count = await repo.count_by_workflow_status(WorkflowStatus.AWAITING_REVIEW)
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_pending_workflow_excludes_awaiting_review(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        await _make_task_record(db_session, WorkflowStatus.PENDING)
        await _make_task_record(db_session, WorkflowStatus.AWAITING_REVIEW)
        await db_session.commit()

        pending_count = await repo.count_by_workflow_status(WorkflowStatus.PENDING)
        assert pending_count == 1

    @pytest.mark.asyncio
    async def test_count_failed_workflow_excludes_discarded(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        await _make_task_record(db_session, WorkflowStatus.FAILED)
        await _make_task_record(db_session, WorkflowStatus.DISCARDED)
        await _make_task_record(db_session, WorkflowStatus.APPLIED)
        await db_session.commit()

        failed_count = await repo.count_by_workflow_status(WorkflowStatus.FAILED)
        assert failed_count == 1

    @pytest.mark.asyncio
    async def test_count_applied_excludes_all_other_statuses(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        await _make_task_record(db_session, WorkflowStatus.APPLIED)
        await _make_task_record(db_session, WorkflowStatus.APPLIED)
        await _make_task_record(db_session, WorkflowStatus.PENDING)
        await _make_task_record(db_session, WorkflowStatus.FAILED)
        await db_session.commit()

        applied_count = await repo.count_by_workflow_status(WorkflowStatus.APPLIED)
        assert applied_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# C. ReviewSessionRepository — count_unresolved, get_active_review_session
# ─────────────────────────────────────────────────────────────────────────────


class TestReviewSessionQuerySemantics:
    @pytest.mark.asyncio
    async def test_count_unresolved_includes_queued_and_active(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task1 = await _make_task_record(db_session)
        task2 = await _make_task_record(db_session)
        task3 = await _make_task_record(db_session)
        task4 = await _make_task_record(db_session)

        await _make_review_session(db_session, task1.stable_id, ReviewSessionStatus.QUEUED)
        await _make_review_session(db_session, task2.stable_id, ReviewSessionStatus.ACTIVE)
        await _make_review_session(db_session, task3.stable_id, ReviewSessionStatus.RESOLVED)
        await _make_review_session(db_session, task4.stable_id, ReviewSessionStatus.SKIPPED)
        await db_session.commit()

        count = await repo.count_unresolved()
        assert count == 2

    @pytest.mark.asyncio
    async def test_count_unresolved_excludes_terminal_states(self, db_session):
        """RESOLVED and SKIPPED are not in the backlog."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.RESOLVED)
        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.SKIPPED)
        await db_session.commit()

        count = await repo.count_unresolved()
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_unresolved_excludes_send_failed(self, db_session):
        """SEND_FAILED is not counted as review backlog — it's a delivery failure."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.SEND_FAILED)
        await db_session.commit()

        count = await repo.count_unresolved()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_active_review_session_returns_active(self, db_session):
        """get_active_review_session() returns the globally active Telegram review session."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.QUEUED)
        rs_active = await _make_review_session(
            db_session, task.stable_id, ReviewSessionStatus.ACTIVE
        )
        await db_session.commit()

        result = await repo.get_active_review_session()
        assert result is not None
        assert result.id == rs_active.id
        assert result.status == ReviewSessionStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_get_active_review_session_returns_none_when_no_active(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.QUEUED)
        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.RESOLVED)
        await db_session.commit()

        result = await repo.get_active_review_session()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_review_session_excludes_queued_items(self, db_session):
        """QUEUED items are in the backlog, not yet shown — must not be returned as active."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task1 = await _make_task_record(db_session)
        task2 = await _make_task_record(db_session)

        await _make_review_session(db_session, task1.stable_id, ReviewSessionStatus.QUEUED)
        await _make_review_session(db_session, task2.stable_id, ReviewSessionStatus.QUEUED)
        await db_session.commit()

        result = await repo.get_active_review_session()
        assert result is None

    @pytest.mark.asyncio
    async def test_count_queued_distinct_from_count_unresolved(self, db_session):
        """count_queued() counts only QUEUED (backlog, not yet shown).
        count_unresolved() counts QUEUED + ACTIVE (entire review backlog)."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task1 = await _make_task_record(db_session)
        task2 = await _make_task_record(db_session)
        task3 = await _make_task_record(db_session)

        await _make_review_session(db_session, task1.stable_id, ReviewSessionStatus.QUEUED)
        await _make_review_session(db_session, task2.stable_id, ReviewSessionStatus.QUEUED)
        await _make_review_session(db_session, task3.stable_id, ReviewSessionStatus.ACTIVE)
        await db_session.commit()

        queued = await repo.count_queued()
        unresolved = await repo.count_unresolved()
        assert queued == 2
        assert unresolved == 3
        assert queued < unresolved

    @pytest.mark.asyncio
    async def test_has_active_review_consistent_with_get_active_session(self, db_session):
        """has_active_review() and get_active_review_session() must be consistent."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        # No active session initially
        assert await repo.has_active_review() is False
        assert await repo.get_active_review_session() is None

        # Create an active session
        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.ACTIVE)
        await db_session.commit()

        assert await repo.has_active_review() is True
        active = await repo.get_active_review_session()
        assert active is not None


# ─────────────────────────────────────────────────────────────────────────────
# D. Buffer compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestBufferCompatibility:
    @pytest.mark.asyncio
    async def test_awaiting_review_count_independent_of_active_review(self, db_session):
        """Active visible review session does not collapse the ready-for-review buffer count.

        A task with AWAITING_REVIEW workflow status and one with ACTIVE review
        session must both be counted correctly by their respective queries.
        """
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_record_repo import TaskRecordRepository

        task_repo = TaskRecordRepository(db_session)
        session_repo = ReviewSessionRepository(db_session)

        # Task 1: AWAITING_REVIEW with a QUEUED session (in buffer, not shown)
        task1 = await _make_task_record(db_session, WorkflowStatus.AWAITING_REVIEW)
        await _make_review_session(db_session, task1.stable_id, ReviewSessionStatus.QUEUED)

        # Task 2: AWAITING_REVIEW with the ACTIVE session (currently shown in Telegram)
        task2 = await _make_task_record(db_session, WorkflowStatus.AWAITING_REVIEW)
        await _make_review_session(db_session, task2.stable_id, ReviewSessionStatus.ACTIVE)

        # Task 3: PENDING — not yet processed
        await _make_task_record(db_session, WorkflowStatus.PENDING)

        await db_session.commit()

        # Buffer depth = total AWAITING_REVIEW tasks
        buffer_depth = await task_repo.count_by_workflow_status(WorkflowStatus.AWAITING_REVIEW)
        assert buffer_depth == 2

        # Review backlog = QUEUED + ACTIVE
        review_backlog = await session_repo.count_unresolved()
        assert review_backlog == 2

        # Active visible item = exactly 1
        active = await session_repo.get_active_review_session()
        assert active is not None
        assert active.stable_id == task2.stable_id

        # Queued (not yet shown) = exactly 1
        queued_count = await session_repo.count_queued()
        assert queued_count == 1

    @pytest.mark.asyncio
    async def test_resolved_items_excluded_from_buffer(self, db_session):
        """Resolved tasks do not inflate the ready-for-review buffer."""
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_record_repo import TaskRecordRepository

        task_repo = TaskRecordRepository(db_session)
        session_repo = ReviewSessionRepository(db_session)

        # APPLIED task — was processed+reviewed+applied
        task1 = await _make_task_record(db_session, WorkflowStatus.APPLIED)
        await _make_review_session(db_session, task1.stable_id, ReviewSessionStatus.RESOLVED)

        # DISCARDED task — processed+reviewed+discarded
        task2 = await _make_task_record(db_session, WorkflowStatus.DISCARDED)
        await _make_review_session(db_session, task2.stable_id, ReviewSessionStatus.RESOLVED)

        await db_session.commit()

        queued = await session_repo.count_queued()
        unresolved = await session_repo.count_unresolved()
        awaiting = await task_repo.count_by_workflow_status(WorkflowStatus.AWAITING_REVIEW)

        assert queued == 0
        assert unresolved == 0
        assert awaiting == 0

    @pytest.mark.asyncio
    async def test_failed_tasks_excluded_from_review_backlog(self, db_session):
        """FAILED workflow tasks must not appear in review backlog."""
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_record_repo import TaskRecordRepository

        task_repo = TaskRecordRepository(db_session)
        session_repo = ReviewSessionRepository(db_session)

        # A failed task has FAILED WorkflowStatus and no open review session
        await _make_task_record(db_session, WorkflowStatus.FAILED)
        await db_session.commit()

        count = await session_repo.count_unresolved()
        failed = await task_repo.count_by_workflow_status(WorkflowStatus.FAILED)

        assert count == 0
        assert failed == 1


# ─────────────────────────────────────────────────────────────────────────────
# E. Regression — items must only appear in their correct query
# ─────────────────────────────────────────────────────────────────────────────


class TestQueryIsolationRegressions:
    @pytest.mark.asyncio
    async def test_failed_queue_entry_not_visible_as_pending(self, db_session):
        """Terminally failed queue entries must never appear in list_pending()."""
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src = await _make_source_task(db_session, suffix="reg-1")
        await _make_queue_entry(db_session, src, ProcessingStatus.FAILED, retry_count=3)
        await db_session.commit()

        pending = await repo.list_pending()
        assert all(e.processing_status != ProcessingStatus.FAILED.value for e in pending)
        assert await repo.count_pending() == 0
        assert await repo.count_failed() == 1

    @pytest.mark.asyncio
    async def test_resolved_review_session_not_visible_in_queued_list(self, db_session):
        """Resolved review sessions must not appear in list_queued()."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.RESOLVED)
        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.SKIPPED)
        await db_session.commit()

        queued = await repo.list_queued()
        assert all(
            s.status not in (ReviewSessionStatus.RESOLVED.value, ReviewSessionStatus.SKIPPED.value)
            for s in queued
        )
        assert len(queued) == 0

    @pytest.mark.asyncio
    async def test_active_review_session_not_visible_in_list_queued(self, db_session):
        """An ACTIVE review session (currently shown in Telegram) is not in the QUEUED backlog."""
        from db.repositories.review_session_repo import ReviewSessionRepository

        repo = ReviewSessionRepository(db_session)
        task = await _make_task_record(db_session)

        await _make_review_session(db_session, task.stable_id, ReviewSessionStatus.ACTIVE)
        await db_session.commit()

        queued = await repo.list_queued()
        assert len(queued) == 0
        assert await repo.count_queued() == 0
        # But it IS unresolved
        assert await repo.count_unresolved() == 1

    @pytest.mark.asyncio
    async def test_claim_next_does_not_return_failed_entry(self, db_session):
        """claim_next() must never return a terminally FAILED entry."""
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src = await _make_source_task(db_session, suffix="cfail-1")
        await _make_queue_entry(db_session, src, ProcessingStatus.FAILED, retry_count=3)
        await db_session.commit()

        claimed = await repo.claim_next()
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_next_does_not_return_completed_entry(self, db_session):
        """claim_next() must never return a COMPLETED entry."""
        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        repo = ProcessingQueueRepository(db_session)
        src = await _make_source_task(db_session, suffix="ccomp-1")
        await _make_queue_entry(db_session, src, ProcessingStatus.COMPLETED)
        await db_session.commit()

        claimed = await repo.claim_next()
        assert claimed is None
