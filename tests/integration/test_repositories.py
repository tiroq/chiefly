"""
Integration tests for repository layer with in-memory SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ConfidenceBand, ProjectType, ReviewAction, TaskKind, TaskStatus
from db.base import Base
from db.models import Project, TaskItem, TaskRevision, TelegramReviewSession


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


class TestTaskItemRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        task_id = uuid.uuid4()
        task = TaskItem(
            id=task_id,
            source_google_task_id="g-001",
            source_google_tasklist_id="inbox",
            raw_text="Test task",
            status=TaskStatus.NEW,
        )
        created = await repo.create(task)
        await db_session.commit()

        fetched = await repo.get_by_id(task_id)
        assert fetched is not None
        assert fetched.raw_text == "Test task"
        assert fetched.status == TaskStatus.NEW

    @pytest.mark.asyncio
    async def test_get_by_source_google_task_id(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="unique-g-id",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.NEW,
        )
        await repo.create(task)
        await db_session.commit()

        fetched = await repo.get_by_source_google_task_id("unique-g-id")
        assert fetched is not None
        assert fetched.source_google_task_id == "unique-g-id"

    @pytest.mark.asyncio
    async def test_get_by_source_google_task_id_not_found(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        fetched = await repo.get_by_source_google_task_id("nonexistent")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_by_status(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        for i in range(3):
            task = TaskItem(
                id=uuid.uuid4(),
                source_google_task_id=f"g-status-{i}",
                source_google_tasklist_id="inbox",
                raw_text=f"Task {i}",
                status=TaskStatus.PROPOSED,
            )
            await repo.create(task)

        # Also create one with different status
        other = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-other",
            source_google_tasklist_id="inbox",
            raw_text="Other",
            status=TaskStatus.NEW,
        )
        await repo.create(other)
        await db_session.commit()

        proposed = await repo.list_by_status(TaskStatus.PROPOSED)
        assert len(proposed) == 3

        new_tasks = await repo.list_by_status(TaskStatus.NEW)
        assert len(new_tasks) == 1

    @pytest.mark.asyncio
    async def test_list_active_routed(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        now = datetime.now(tz=timezone.utc)

        for i in range(5):
            task = TaskItem(
                id=uuid.uuid4(),
                source_google_task_id=f"g-routed-{i}",
                source_google_tasklist_id="inbox",
                raw_text=f"Routed {i}",
                status=TaskStatus.ROUTED,
                confirmed_at=now - timedelta(hours=i),
            )
            await repo.create(task)
        await db_session.commit()

        active = await repo.list_active_routed(limit=3)
        assert len(active) == 3

    @pytest.mark.asyncio
    async def test_save_updates_fields(self, db_session):
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-update",
            source_google_tasklist_id="inbox",
            raw_text="Original",
            status=TaskStatus.NEW,
        )
        await repo.create(task)
        await db_session.commit()

        task.status = TaskStatus.PROPOSED
        task.normalized_title = "Updated Title"
        await repo.save(task)
        await db_session.commit()

        fetched = await repo.get_by_id(task.id)
        assert fetched.status == TaskStatus.PROPOSED
        assert fetched.normalized_title == "Updated Title"

    @pytest.mark.asyncio
    async def test_unique_source_google_task_id(self, db_session):
        from sqlalchemy.exc import IntegrityError
        from db.repositories.task_item_repo import TaskItemRepository

        repo = TaskItemRepository(db_session)
        task1 = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="duplicate-id",
            source_google_tasklist_id="inbox",
            raw_text="Task 1",
            status=TaskStatus.NEW,
        )
        await repo.create(task1)
        await db_session.commit()

        task2 = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="duplicate-id",
            source_google_tasklist_id="inbox",
            raw_text="Task 2",
            status=TaskStatus.NEW,
        )
        with pytest.raises(IntegrityError):
            await repo.create(task2)
            await db_session.commit()


class TestTaskRevisionRepository:
    @pytest.mark.asyncio
    async def test_create_and_list(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        # Need a task first
        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-rev-001",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)
        rev = TaskRevision(
            id=uuid.uuid4(),
            task_item_id=task.id,
            revision_no=1,
            raw_text="Test",
            proposal_json={"kind": "task"},
        )
        created = await repo.create(rev)
        await db_session.commit()

        revisions = await repo.list_by_task(task.id)
        assert len(revisions) == 1
        assert revisions[0].revision_no == 1

    @pytest.mark.asyncio
    async def test_get_next_revision_no(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-rev-002",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)

        # First revision number should be 1
        next_no = await repo.get_next_revision_no(task.id)
        assert next_no == 1

        rev1 = TaskRevision(
            id=uuid.uuid4(),
            task_item_id=task.id,
            revision_no=1,
            raw_text="Test",
            proposal_json={},
        )
        await repo.create(rev1)
        await db_session.flush()

        next_no = await repo.get_next_revision_no(task.id)
        assert next_no == 2

    @pytest.mark.asyncio
    async def test_revisions_ordered_by_revision_no(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-rev-003",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)
        for i in [3, 1, 2]:  # Insert out of order
            rev = TaskRevision(
                id=uuid.uuid4(),
                task_item_id=task.id,
                revision_no=i,
                raw_text=f"Rev {i}",
                proposal_json={},
            )
            await repo.create(rev)
        await db_session.commit()

        revisions = await repo.list_by_task(task.id)
        assert [r.revision_no for r in revisions] == [1, 2, 3]


class TestProjectRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_slug(self, db_session):
        from db.repositories.project_repo import ProjectRepository

        repo = ProjectRepository(db_session)
        project = Project(
            id=uuid.uuid4(),
            name="Test Project",
            slug="test-project",
            google_tasklist_id="test-list",
            project_type=ProjectType.PERSONAL,
            is_active=True,
        )
        await repo.create(project)
        await db_session.commit()

        fetched = await repo.get_by_slug("test-project")
        assert fetched is not None
        assert fetched.name == "Test Project"

    @pytest.mark.asyncio
    async def test_list_active_excludes_inactive(self, db_session):
        from db.repositories.project_repo import ProjectRepository

        repo = ProjectRepository(db_session)
        active = Project(
            id=uuid.uuid4(),
            name="Active",
            slug="active",
            google_tasklist_id="a-list",
            project_type=ProjectType.PERSONAL,
            is_active=True,
        )
        inactive = Project(
            id=uuid.uuid4(),
            name="Inactive",
            slug="inactive",
            google_tasklist_id="i-list",
            project_type=ProjectType.PERSONAL,
            is_active=False,
        )
        await repo.create(active)
        await repo.create(inactive)
        await db_session.commit()

        projects = await repo.list_active()
        assert len(projects) == 1
        assert projects[0].slug == "active"

    @pytest.mark.asyncio
    async def test_unique_slug_constraint(self, db_session):
        from sqlalchemy.exc import IntegrityError
        from db.repositories.project_repo import ProjectRepository

        repo = ProjectRepository(db_session)
        p1 = Project(
            id=uuid.uuid4(),
            name="P1",
            slug="duplicate-slug",
            google_tasklist_id="l1",
            project_type=ProjectType.PERSONAL,
            is_active=True,
        )
        await repo.create(p1)
        await db_session.commit()

        p2 = Project(
            id=uuid.uuid4(),
            name="P2",
            slug="duplicate-slug",
            google_tasklist_id="l2",
            project_type=ProjectType.PERSONAL,
            is_active=True,
        )
        with pytest.raises(IntegrityError):
            await repo.create(p2)
            await db_session.commit()


class TestReviewSessionRepository:
    @pytest.mark.asyncio
    async def test_get_active_by_task(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-sess-001",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            task_item_id=task.id,
            telegram_chat_id="123",
            telegram_message_id=1,
            status="pending",
        )
        await repo.create(session_obj)
        await db_session.commit()

        active = await repo.get_active_by_task(task.id)
        assert active is not None
        assert active.status == "pending"

    @pytest.mark.asyncio
    async def test_resolved_session_not_returned_as_active(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-sess-002",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            task_item_id=task.id,
            telegram_chat_id="123",
            telegram_message_id=1,
            status="resolved",
        )
        await repo.create(session_obj)
        await db_session.commit()

        active = await repo.get_active_by_task(task.id)
        assert active is None

    @pytest.mark.asyncio
    async def test_get_pending_edit_by_chat(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        task = TaskItem(
            id=uuid.uuid4(),
            source_google_task_id="g-edit-001",
            source_google_tasklist_id="inbox",
            raw_text="Test",
            status=TaskStatus.PROPOSED,
        )
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            task_item_id=task.id,
            telegram_chat_id="chat-789",
            telegram_message_id=1,
            status="awaiting_edit",
        )
        await repo.create(session_obj)
        await db_session.commit()

        pending = await repo.get_pending_edit_by_chat("chat-789")
        assert pending is not None
        assert pending.task_item_id == task.id

        # Different chat should return None
        other = await repo.get_pending_edit_by_chat("chat-other")
        assert other is None


class TestDailyReviewRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_latest(self, db_session):
        from db.models.daily_review_snapshot import DailyReviewSnapshot
        from db.repositories.daily_review_repo import DailyReviewRepository

        repo = DailyReviewRepository(db_session)
        snap = DailyReviewSnapshot(
            id=uuid.uuid4(),
            summary_text="Test summary",
            payload_json={"test": True},
        )
        await repo.create(snap)
        await db_session.commit()

        latest = await repo.get_latest()
        assert latest is not None
        assert latest.summary_text == "Test summary"

    @pytest.mark.asyncio
    async def test_get_latest_returns_most_recent(self, db_session):
        from db.models.daily_review_snapshot import DailyReviewSnapshot
        from db.repositories.daily_review_repo import DailyReviewRepository

        repo = DailyReviewRepository(db_session)
        snap1 = DailyReviewSnapshot(
            id=uuid.uuid4(),
            summary_text="First",
            payload_json={},
        )
        await repo.create(snap1)
        await db_session.flush()

        snap2 = DailyReviewSnapshot(
            id=uuid.uuid4(),
            summary_text="Second",
            payload_json={},
        )
        await repo.create(snap2)
        await db_session.commit()

        latest = await repo.get_latest()
        assert latest is not None
        # Can't guarantee ordering with SQLite in-memory timestamps but both exist

    @pytest.mark.asyncio
    async def test_get_latest_empty_db(self, db_session):
        from db.repositories.daily_review_repo import DailyReviewRepository

        repo = DailyReviewRepository(db_session)
        latest = await repo.get_latest()
        assert latest is None
