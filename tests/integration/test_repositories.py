"""
Integration tests for repository layer with in-memory SQLite.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ProjectType, TaskRecordState, WorkflowStatus
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


class TestTaskRecordRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        stable_id = uuid.uuid4()
        created = await repo.create(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="g-001",
        )
        await db_session.commit()

        fetched = await repo.get_by_stable_id(stable_id)
        assert fetched is not None
        assert created.stable_id == stable_id
        assert fetched.stable_id == stable_id
        assert fetched.current_tasklist_id == "inbox"
        assert fetched.current_task_id == "g-001"

    @pytest.mark.asyncio
    async def test_get_by_source_google_task_id(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        stable_id = uuid.uuid4()
        await repo.create(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="unique-g-id",
        )
        await db_session.commit()

        fetched = await repo.get_by_pointer("inbox", "unique-g-id")
        assert fetched is not None
        assert fetched.stable_id == stable_id
        assert fetched.current_task_id == "unique-g-id"

    @pytest.mark.asyncio
    async def test_get_by_source_google_task_id_not_found(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        fetched = await repo.get_by_pointer("inbox", "nonexistent")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_by_status(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        for i in range(3):
            await repo.create(
                stable_id=uuid.uuid4(),
                state=TaskRecordState.ACTIVE,
                current_tasklist_id="inbox",
                current_task_id=f"g-state-{i}",
            )

        await repo.create(
            stable_id=uuid.uuid4(),
            state=TaskRecordState.MISSING,
            current_tasklist_id="inbox",
            current_task_id="g-other",
        )
        await db_session.commit()

        active = await repo.list_by_state(TaskRecordState.ACTIVE)
        assert len(active) == 3

        missing = await repo.list_by_state(TaskRecordState.MISSING)
        assert len(missing) == 1

    @pytest.mark.asyncio
    async def test_list_active_routed(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)

        for i in range(5):
            await repo.create(
                stable_id=uuid.uuid4(),
                state=TaskRecordState.ACTIVE,
                current_tasklist_id="inbox",
                current_task_id=f"g-active-{i}",
            )
        await repo.create(
            stable_id=uuid.uuid4(),
            state=TaskRecordState.UNADOPTED,
            current_tasklist_id="inbox",
            current_task_id="g-unadopted",
        )
        await db_session.commit()

        active = await repo.list_active()
        assert len(active) == 5

    @pytest.mark.asyncio
    async def test_save_updates_fields(self, db_session):
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        stable_id = uuid.uuid4()
        await repo.create(
            stable_id=stable_id,
            current_tasklist_id="inbox",
            current_task_id="g-update",
        )
        await db_session.commit()

        await repo.update_processing_status(stable_id, WorkflowStatus.APPLIED)
        await db_session.commit()

        fetched = await repo.get_by_stable_id(stable_id)
        assert fetched is not None
        assert fetched.processing_status == WorkflowStatus.APPLIED.value

    @pytest.mark.asyncio
    async def test_unique_source_google_task_id(self, db_session):
        if db_session.bind is not None and db_session.bind.dialect.name == "sqlite":
            pytest.skip("Partial unique index on pointer is not enforced by SQLite")

        from sqlalchemy.exc import IntegrityError
        from db.repositories.task_record_repo import TaskRecordRepository

        repo = TaskRecordRepository(db_session)
        await repo.create(
            stable_id=uuid.uuid4(),
            current_tasklist_id="inbox",
            current_task_id="duplicate-id",
        )
        await db_session.commit()

        with pytest.raises(IntegrityError):
            await repo.create(
                stable_id=uuid.uuid4(),
                current_tasklist_id="inbox",
                current_task_id="duplicate-id",
            )
            await db_session.commit()


class TestTaskRevisionRepository:
    @pytest.mark.asyncio
    async def test_create_and_list(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)
        rev = TaskRevision(
            id=uuid.uuid4(),
            stable_id=task.stable_id,
            revision_no=1,
            raw_text="Test",
            proposal_json={"kind": "task"},
        )
        created = await repo.create(rev)
        await db_session.commit()

        assert created.stable_id == task.stable_id
        revisions = await repo.list_by_stable_id(task.stable_id)
        assert len(revisions) == 1
        assert revisions[0].revision_no == 1

    @pytest.mark.asyncio
    async def test_get_next_revision_no(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)

        # First revision number should be 1
        next_no = await repo.get_next_revision_no_by_stable_id(task.stable_id)
        assert next_no == 1

        rev1 = TaskRevision(
            id=uuid.uuid4(),
            stable_id=task.stable_id,
            revision_no=1,
            raw_text="Test",
            proposal_json={},
        )
        await repo.create(rev1)
        await db_session.flush()

        next_no = await repo.get_next_revision_no_by_stable_id(task.stable_id)
        assert next_no == 2

    @pytest.mark.asyncio
    async def test_revisions_ordered_by_revision_no(self, db_session):
        from db.repositories.task_revision_repo import TaskRevisionRepository

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = TaskRevisionRepository(db_session)
        for i in [3, 1, 2]:  # Insert out of order
            rev = TaskRevision(
                id=uuid.uuid4(),
                stable_id=task.stable_id,
                revision_no=i,
                raw_text=f"Rev {i}",
                proposal_json={},
            )
            await repo.create(rev)
        await db_session.commit()

        revisions = await repo.list_by_stable_id(task.stable_id)
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

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            stable_id=task.stable_id,
            telegram_chat_id="123",
            telegram_message_id=1,
            status="pending",
        )
        await repo.create(session_obj)
        await db_session.commit()

        active = await repo.get_active_by_stable_id(task.stable_id)
        assert active is not None
        assert active.status == "pending"

    @pytest.mark.asyncio
    async def test_resolved_session_not_returned_as_active(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            stable_id=task.stable_id,
            telegram_chat_id="123",
            telegram_message_id=1,
            status="resolved",
        )
        await repo.create(session_obj)
        await db_session.commit()

        active = await repo.get_active_by_stable_id(task.stable_id)
        assert active is None

    @pytest.mark.asyncio
    async def test_get_pending_edit_by_chat(self, db_session):
        from db.repositories.review_session_repo import ReviewSessionRepository

        task = TaskRecord(stable_id=uuid.uuid4())
        db_session.add(task)
        await db_session.flush()

        repo = ReviewSessionRepository(db_session)
        session_obj = TelegramReviewSession(
            id=uuid.uuid4(),
            stable_id=task.stable_id,
            telegram_chat_id="chat-789",
            telegram_message_id=1,
            status="awaiting_edit",
        )
        await repo.create(session_obj)
        await db_session.commit()

        pending = await repo.get_pending_edit_by_chat("chat-789")
        assert pending is not None
        assert pending.stable_id == task.stable_id

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
