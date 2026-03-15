"""
Integration tests for Telegram callback flows (confirm, discard).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ConfidenceBand, ProjectType, TaskKind, TaskStatus
from db.base import Base
from db.models import Project, TaskItem, TelegramReviewSession


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
async def proposed_task(db_session) -> TaskItem:
    """A task in PROPOSED status ready for user decision."""
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

    task = TaskItem(
        id=uuid.uuid4(),
        source_google_task_id="gtask-confirm-001",
        source_google_tasklist_id="inbox-list-id",
        current_google_task_id="gtask-confirm-001",
        current_google_tasklist_id="inbox-list-id",
        raw_text="Buy birthday gift for mom",
        normalized_title="Buy birthday gift for mom",
        kind=TaskKind.TASK,
        status=TaskStatus.PROPOSED,
        project_id=project.id,
        confidence_band=ConfidenceBand.HIGH,
    )
    db_session.add(task)

    review_session = TelegramReviewSession(
        id=uuid.uuid4(),
        task_item_id=task.id,
        telegram_chat_id="123456",
        telegram_message_id=100,
        status="pending",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(review_session)
    await db_session.commit()
    return task


@pytest.mark.asyncio
async def test_confirm_flow_updates_status(db_session, proposed_task):
    """Confirm action transitions task to ROUTED."""
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.domain.state_machine import transition
    from core.schemas.llm import TaskClassificationResult
    from core.utils.datetime import utcnow
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_item_repo import TaskItemRepository

    task_repo = TaskItemRepository(db_session)
    session_repo = ReviewSessionRepository(db_session)
    revision_svc = RevisionService(db_session)

    task = proposed_task
    review_session = await session_repo.get_active_by_task(task.id)

    # Simulate confirm flow
    task.status = transition(task.status, TaskStatus.CONFIRMED)
    task.confirmed_at = utcnow()
    task.is_processed = True
    task.status = transition(TaskStatus.CONFIRMED, TaskStatus.ROUTED)
    await task_repo.save(task)

    if review_session:
        review_session.status = "resolved"
        review_session.resolved_at = utcnow()
        await session_repo.save(review_session)

    cls_result = TaskClassificationResult(
        kind=task.kind or "task",
        normalized_title=task.normalized_title or task.raw_text,
        confidence=task.confidence_band or "medium",
    )
    await revision_svc.create_decision_revision(
        task_item_id=task.id,
        raw_text=task.raw_text,
        decision=ReviewAction.CONFIRM,
        classification=cls_result,
        project_id=task.project_id,
    )
    await db_session.commit()

    # Verify
    updated_task = await task_repo.get_by_id(task.id)
    assert updated_task.status == TaskStatus.ROUTED
    assert updated_task.confirmed_at is not None
    assert updated_task.is_processed is True

    updated_session = await session_repo.get_active_by_task(task.id)
    assert updated_session is None  # No longer pending

    revisions = await revision_svc.list_revisions(task.id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.CONFIRM


@pytest.mark.asyncio
async def test_discard_flow_updates_status(db_session, proposed_task):
    """Discard action transitions task to DISCARDED."""
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.domain.state_machine import transition
    from core.schemas.llm import TaskClassificationResult
    from core.utils.datetime import utcnow
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_item_repo import TaskItemRepository

    task_repo = TaskItemRepository(db_session)
    session_repo = ReviewSessionRepository(db_session)
    revision_svc = RevisionService(db_session)

    task = proposed_task
    review_session = await session_repo.get_active_by_task(task.id)

    # Simulate discard flow
    task.status = transition(task.status, TaskStatus.DISCARDED)
    task.is_processed = True
    await task_repo.save(task)

    if review_session:
        review_session.status = "resolved"
        review_session.resolved_at = utcnow()
        await session_repo.save(review_session)

    cls_result = TaskClassificationResult(
        kind=task.kind or "task",
        normalized_title=task.normalized_title or task.raw_text,
        confidence=task.confidence_band or "medium",
    )
    await revision_svc.create_decision_revision(
        task_item_id=task.id,
        raw_text=task.raw_text,
        decision=ReviewAction.DISCARD,
        classification=cls_result,
        project_id=task.project_id,
    )
    await db_session.commit()

    # Verify
    updated_task = await task_repo.get_by_id(task.id)
    assert updated_task.status == TaskStatus.DISCARDED
    assert updated_task.is_processed is True

    revisions = await revision_svc.list_revisions(task.id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.DISCARD


@pytest.mark.asyncio
async def test_revision_number_increments(db_session, proposed_task):
    """Each revision for a task increments revision_no."""
    from apps.api.services.revision_service import RevisionService
    from core.domain.enums import ReviewAction
    from core.schemas.llm import TaskClassificationResult

    revision_svc = RevisionService(db_session)
    task = proposed_task

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Test task",
        confidence=ConfidenceBand.HIGH,
    )

    rev1 = await revision_svc.create_decision_revision(
        task_item_id=task.id,
        raw_text=task.raw_text,
        decision=ReviewAction.EDIT,
        classification=cls_result,
        project_id=task.project_id,
    )
    rev2 = await revision_svc.create_decision_revision(
        task_item_id=task.id,
        raw_text=task.raw_text,
        decision=ReviewAction.CONFIRM,
        classification=cls_result,
        project_id=task.project_id,
    )
    await db_session.commit()

    assert rev1.revision_no == 1
    assert rev2.revision_no == 2
