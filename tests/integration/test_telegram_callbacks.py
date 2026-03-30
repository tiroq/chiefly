"""
Integration tests for Telegram callback flows (confirm, discard).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from core.domain.enums import ConfidenceBand, ProjectType, TaskKind, WorkflowStatus
from db.base import Base
from db.models import Project, TaskRecord, TelegramReviewSession


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def proposed_task(db_session: AsyncSession) -> TaskRecord:
    project = Project(
        id=uuid.uuid4(),
        name="Personal",
        slug="personal",
        google_tasklist_id="personal-list-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(project)

    task = TaskRecord(
        stable_id=uuid.uuid4(),
        state="active",
        processing_status="awaiting_review",
        current_tasklist_id="inbox-list-id",
        current_task_id="gtask-confirm-001",
    )
    db_session.add(task)

    review_session = TelegramReviewSession(
        id=uuid.uuid4(),
        stable_id=task.stable_id,
        telegram_chat_id="123456",
        telegram_message_id=100,
        status="pending",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(review_session)
    await db_session.commit()
    return task


@pytest.mark.asyncio
async def test_confirm_flow_updates_status(
    db_session: AsyncSession, proposed_task: TaskRecord
) -> None:
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.schemas.llm import TaskClassificationResult
    from core.utils.datetime import utcnow
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_record_repo import TaskRecordRepository

    task_repo = TaskRecordRepository(db_session)
    session_repo = ReviewSessionRepository(db_session)
    revision_svc = RevisionService(db_session)

    task: TaskRecord = proposed_task
    review_session = await session_repo.get_active_by_stable_id(task.stable_id)

    # Simulate confirm flow
    await task_repo.update_processing_status(task.stable_id, WorkflowStatus.APPLIED)

    if review_session:
        review_session.status = "resolved"
        review_session.resolved_at = utcnow()
        _ = await session_repo.save(review_session)

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Buy birthday gift for mom",
        confidence=ConfidenceBand.HIGH,
    )
    _ = await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="Buy birthday gift for mom",
        decision=ReviewAction.CONFIRM,
        classification=cls_result,
        project_id=None,
    )
    await db_session.commit()

    # Verify
    updated_task = await task_repo.get_by_stable_id(task.stable_id)
    assert updated_task is not None
    assert updated_task.processing_status == WorkflowStatus.APPLIED.value

    updated_session = await session_repo.get_active_by_stable_id(task.stable_id)
    assert updated_session is None  # No longer pending

    revisions = await revision_svc.list_revisions(task.stable_id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.CONFIRM


@pytest.mark.asyncio
async def test_discard_flow_updates_status(
    db_session: AsyncSession, proposed_task: TaskRecord
) -> None:
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.schemas.llm import TaskClassificationResult
    from core.utils.datetime import utcnow
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_record_repo import TaskRecordRepository

    task_repo = TaskRecordRepository(db_session)
    session_repo = ReviewSessionRepository(db_session)
    revision_svc = RevisionService(db_session)

    task: TaskRecord = proposed_task
    review_session = await session_repo.get_active_by_stable_id(task.stable_id)

    # Simulate discard flow
    await task_repo.update_processing_status(task.stable_id, WorkflowStatus.DISCARDED)

    if review_session:
        review_session.status = "resolved"
        review_session.resolved_at = utcnow()
        _ = await session_repo.save(review_session)

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Buy birthday gift for mom",
        confidence=ConfidenceBand.HIGH,
    )
    _ = await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="Buy birthday gift for mom",
        decision=ReviewAction.DISCARD,
        classification=cls_result,
        project_id=None,
    )
    await db_session.commit()

    # Verify
    updated_task = await task_repo.get_by_stable_id(task.stable_id)
    assert updated_task is not None
    assert updated_task.processing_status == WorkflowStatus.DISCARDED.value

    revisions = await revision_svc.list_revisions(task.stable_id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.DISCARD


@pytest.mark.asyncio
async def test_revision_number_increments(
    db_session: AsyncSession, proposed_task: TaskRecord
) -> None:
    """Each revision for a task increments revision_no."""
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.schemas.llm import TaskClassificationResult

    revision_svc = RevisionService(db_session)
    task: TaskRecord = proposed_task

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Test task",
        confidence=ConfidenceBand.HIGH,
    )

    rev1 = await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="Buy birthday gift for mom",
        decision=ReviewAction.EDIT,
        classification=cls_result,
        project_id=None,
    )
    rev2 = await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="Buy birthday gift for mom",
        decision=ReviewAction.CONFIRM,
        classification=cls_result,
        project_id=None,
    )
    await db_session.commit()

    assert rev1.revision_no == 1
    assert rev2.revision_no == 2
