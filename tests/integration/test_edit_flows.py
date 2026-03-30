"""
Integration tests for edit title, change project, and change type callback flows.
These test the flows that were bugfixed (missing revision creation).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from core.domain.enums import ConfidenceBand, ProjectType, ReviewAction, TaskKind
from db.base import Base
from db.models import Project, TaskRecord, TaskRevision, TelegramReviewSession


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


@pytest_asyncio.fixture
async def task_with_session(
    db_session,
) -> tuple[TaskRecord, TelegramReviewSession, Project, Project]:
    project_personal = Project(
        id=uuid.uuid4(),
        name="Personal",
        slug="personal",
        google_tasklist_id="personal-list-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    project_nft = Project(
        id=uuid.uuid4(),
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-list-id",
        project_type=ProjectType.CLIENT,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(project_personal)
    db_session.add(project_nft)

    task = TaskRecord(
        stable_id=uuid.uuid4(),
        state="active",
        processing_status="awaiting_review",
        current_tasklist_id="inbox-list-id",
        current_task_id="gtask-edit-001",
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
    return task, review_session, project_personal, project_nft


@pytest.mark.asyncio
async def test_edit_title_creates_revision(db_session, task_with_session):
    """Editing a title should create a TaskRevision with EDIT decision."""
    from apps.api.services.revision_service import RevisionService
    from core.schemas.llm import TaskClassificationResult
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_revision_repo import TaskRevisionRepository

    task, review_session, project_personal, _ = task_with_session
    session_repo = ReviewSessionRepository(db_session)
    revision_svc = RevisionService(db_session)

    # Simulate the edit flow: mark session as awaiting_edit, then apply title
    review_session.status = "awaiting_edit"
    await session_repo.save(review_session)
    active_session = await session_repo.get_active_by_stable_id(task.stable_id)
    assert active_session is not None
    assert active_session.status == "awaiting_edit"

    new_title = "Updated Title After Edit"

    # Create revision (this is what the bugfix adds)
    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title=new_title,
        confidence=ConfidenceBand.HIGH,
    )
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.EDIT,
        classification=cls_result,
        project_id=project_personal.id,
        user_notes=f"Title changed to: {new_title}",
    )

    review_session.status = "pending"
    await session_repo.save(review_session)
    await db_session.commit()

    # Verify
    active_session = await session_repo.get_active_by_stable_id(task.stable_id)
    assert active_session is not None
    assert active_session.status == "pending"

    rev_repo = TaskRevisionRepository(db_session)
    revisions: list[TaskRevision] = await rev_repo.list_by_stable_id(task.stable_id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.EDIT
    assert revisions[0].final_title == new_title
    assert revisions[0].user_notes is not None
    assert "Title changed to:" in revisions[0].user_notes


@pytest.mark.asyncio
async def test_change_project_creates_revision(db_session, task_with_session):
    """Changing project should create a TaskRevision with CHANGE_PROJECT decision."""
    from apps.api.services.revision_service import RevisionService
    from core.schemas.llm import TaskClassificationResult
    from db.repositories.task_revision_repo import TaskRevisionRepository

    task, _, _, project_nft = task_with_session
    revision_svc = RevisionService(db_session)

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Original Title",
        confidence=ConfidenceBand.HIGH,
    )
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.CHANGE_PROJECT,
        classification=cls_result,
        project_id=project_nft.id,
    )
    await db_session.commit()

    rev_repo = TaskRevisionRepository(db_session)
    revisions: list[TaskRevision] = await rev_repo.list_by_stable_id(task.stable_id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.CHANGE_PROJECT
    assert revisions[0].final_project_id == project_nft.id


@pytest.mark.asyncio
async def test_change_type_creates_revision(db_session, task_with_session):
    """Changing kind should create a TaskRevision with CHANGE_TYPE decision."""
    from apps.api.services.revision_service import RevisionService
    from core.schemas.llm import TaskClassificationResult
    from db.repositories.task_revision_repo import TaskRevisionRepository

    task, _, project_personal, _ = task_with_session
    revision_svc = RevisionService(db_session)

    # Change type from TASK to WAITING
    new_kind = TaskKind.WAITING

    cls_result = TaskClassificationResult(
        kind=new_kind,
        normalized_title="Original Title",
        confidence=ConfidenceBand.HIGH,
    )
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.CHANGE_TYPE,
        classification=cls_result,
        project_id=project_personal.id,
        final_kind=new_kind,
    )
    await db_session.commit()

    rev_repo = TaskRevisionRepository(db_session)
    revisions: list[TaskRevision] = await rev_repo.list_by_stable_id(task.stable_id)
    assert len(revisions) == 1
    assert revisions[0].user_decision == ReviewAction.CHANGE_TYPE
    assert revisions[0].final_kind == TaskKind.WAITING


@pytest.mark.asyncio
async def test_multiple_edits_increment_revisions(db_session, task_with_session):
    """Multiple edits should create sequential revision numbers."""
    from apps.api.services.revision_service import RevisionService
    from core.schemas.llm import TaskClassificationResult
    from db.repositories.task_revision_repo import TaskRevisionRepository

    task, _, project_personal, project_nft = task_with_session
    revision_svc = RevisionService(db_session)

    cls_result = TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Title v1",
        confidence=ConfidenceBand.HIGH,
    )

    # Edit title
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.EDIT,
        classification=cls_result,
        project_id=project_personal.id,
        user_notes="Title change",
    )

    # Change project
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.CHANGE_PROJECT,
        classification=cls_result,
        project_id=project_nft.id,
    )

    # Change type
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.CHANGE_TYPE,
        classification=cls_result.model_copy(update={"kind": TaskKind.IDEA}),
        project_id=project_nft.id,
        final_kind=TaskKind.IDEA,
    )

    # Confirm
    await revision_svc.create_decision_revision(
        stable_id=task.stable_id,
        raw_text="test raw text for editing",
        decision=ReviewAction.CONFIRM,
        classification=cls_result,
        project_id=project_nft.id,
    )
    await db_session.commit()

    rev_repo = TaskRevisionRepository(db_session)
    revisions: list[TaskRevision] = await rev_repo.list_by_stable_id(task.stable_id)
    assert len(revisions) == 4
    assert [r.revision_no for r in revisions] == [1, 2, 3, 4]
    assert [r.user_decision for r in revisions] == [
        ReviewAction.EDIT,
        ReviewAction.CHANGE_PROJECT,
        ReviewAction.CHANGE_TYPE,
        ReviewAction.CONFIRM,
    ]
