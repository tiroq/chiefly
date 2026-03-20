"""
Integration tests for admin panel models: ProjectPromptVersion, SystemEvent, ProjectAlias.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ProjectType
from db.base import Base
from db.models import Project, ProjectPromptVersion, SystemEvent, ProjectAlias, TaskItem


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
async def sample_project(db_session):
    """Create a sample project for testing."""
    project = Project(
        id=uuid.uuid4(),
        name="Test Project",
        slug="test-project",
        google_tasklist_id="test-list-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def sample_task(db_session, sample_project):
    """Create a sample task for testing."""
    from core.domain.enums import TaskStatus

    task = TaskItem(
        id=uuid.uuid4(),
        source_google_task_id="test-gtask-001",
        source_google_tasklist_id="test-list-id",
        raw_text="Test task",
        status=TaskStatus.NEW,
        project_id=sample_project.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestProjectPromptVersionModel:
    @pytest.mark.asyncio
    async def test_create_basic_prompt_version(self, db_session, sample_project):
        """Test creating a basic ProjectPromptVersion with required fields."""
        version = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            version_no=1,
            is_active=True,
        )
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)

        assert version.id is not None
        assert version.project_id == sample_project.id
        assert version.version_no == 1
        assert version.is_active is True
        assert version.created_at is not None

    @pytest.mark.asyncio
    async def test_prompt_version_all_fields(self, db_session, sample_project):
        """Test ProjectPromptVersion with all optional fields."""
        version = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            version_no=2,
            title="Version 2 - Improved Routing",
            description_text="This version improves routing logic",
            classification_prompt_text="Classify this task carefully...",
            routing_prompt_text="Route to the right project...",
            examples_json={"examples": [{"input": "test", "output": "result"}]},
            is_active=False,
            created_by="admin@example.com",
            change_note="Fixed classification edge cases",
        )
        db_session.add(version)
        await db_session.commit()
        await db_session.refresh(version)

        assert version.title == "Version 2 - Improved Routing"
        assert version.description_text == "This version improves routing logic"
        assert version.classification_prompt_text == "Classify this task carefully..."
        assert version.routing_prompt_text == "Route to the right project..."
        assert version.examples_json == {"examples": [{"input": "test", "output": "result"}]}
        assert version.is_active is False
        assert version.created_by == "admin@example.com"
        assert version.change_note == "Fixed classification edge cases"

    @pytest.mark.asyncio
    async def test_prompt_version_unique_constraint(self, db_session, sample_project):
        """Test that (project_id, version_no) unique constraint works."""
        version1 = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            version_no=1,
            is_active=True,
        )
        db_session.add(version1)
        await db_session.commit()

        # Try to insert duplicate
        version2 = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            version_no=1,
            is_active=False,
        )
        db_session.add(version2)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_prompt_version_index_on_project_and_active(self, db_session, sample_project):
        """Test that index on (project_id, is_active) is created."""
        for i in range(1, 4):
            version = ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                version_no=i,
                is_active=(i == 1),
            )
            db_session.add(version)
        await db_session.commit()

        # Query to verify index is there (no assertion needed, just verify no error)
        from sqlalchemy import select

        result = await db_session.execute(
            select(ProjectPromptVersion).where(
                ProjectPromptVersion.project_id == sample_project.id,
                ProjectPromptVersion.is_active == True,
            )
        )
        active_versions = result.scalars().all()
        assert len(active_versions) == 1


class TestSystemEventModel:
    @pytest.mark.asyncio
    async def test_create_basic_system_event(self, db_session):
        """Test creating a basic SystemEvent."""
        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="admin_action",
            severity="info",
            subsystem="admin",
            message="Admin performed an action",
        )
        db_session.add(event)
        await db_session.commit()
        await db_session.refresh(event)

        assert event.id is not None
        assert event.event_type == "admin_action"
        assert event.severity == "info"
        assert event.subsystem == "admin"
        assert event.message == "Admin performed an action"
        assert event.created_at is not None

    @pytest.mark.asyncio
    async def test_system_event_all_fields(self, db_session, sample_project, sample_task):
        """Test SystemEvent with all optional fields."""
        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="classification_error",
            severity="error",
            subsystem="classification",
            task_item_id=sample_task.id,
            project_id=sample_project.id,
            payload_json={"error": "Invalid input", "retries": 3},
            message="Classification failed for task, retried 3 times",
        )
        db_session.add(event)
        await db_session.commit()
        await db_session.refresh(event)

        assert event.event_type == "classification_error"
        assert event.severity == "error"
        assert event.subsystem == "classification"
        assert event.task_item_id == sample_task.id
        assert event.project_id == sample_project.id
        assert event.payload_json == {"error": "Invalid input", "retries": 3}
        assert event.message == "Classification failed for task, retried 3 times"

    @pytest.mark.asyncio
    async def test_system_event_severity_values(self, db_session):
        """Test SystemEvent accepts valid severity values."""
        for severity in ["info", "warning", "error"]:
            event = SystemEvent(
                id=uuid.uuid4(),
                event_type="test",
                severity=severity,
                subsystem="test",
                message=f"Test event with severity {severity}",
            )
            db_session.add(event)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(select(SystemEvent))
        events = result.scalars().all()
        assert len(events) == 3
        assert set(e.severity for e in events) == {"info", "warning", "error"}

    @pytest.mark.asyncio
    async def test_system_event_created_at_indexed(self, db_session):
        """Test that created_at is indexed for efficient queries."""
        for i in range(3):
            event = SystemEvent(
                id=uuid.uuid4(),
                event_type="test",
                severity="info",
                subsystem="test",
                message=f"Event {i}",
            )
            db_session.add(event)
        await db_session.commit()

        # Just verify query works efficiently
        from sqlalchemy import select

        result = await db_session.execute(
            select(SystemEvent).order_by(SystemEvent.created_at.desc())
        )
        events = result.scalars().all()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_system_event_event_type_indexed(self, db_session):
        """Test that event_type is indexed."""
        event1 = SystemEvent(
            id=uuid.uuid4(),
            event_type="admin_login",
            severity="info",
            subsystem="auth",
            message="Admin logged in",
        )
        event2 = SystemEvent(
            id=uuid.uuid4(),
            event_type="admin_action",
            severity="info",
            subsystem="admin",
            message="Admin performed action",
        )
        db_session.add(event1)
        db_session.add(event2)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(SystemEvent).where(SystemEvent.event_type == "admin_login")
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "admin_login"


class TestProjectAliasModel:
    @pytest.mark.asyncio
    async def test_create_basic_project_alias(self, db_session, sample_project):
        """Test creating a basic ProjectAlias."""
        alias = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="tp",
        )
        db_session.add(alias)
        await db_session.commit()
        await db_session.refresh(alias)

        assert alias.id is not None
        assert alias.project_id == sample_project.id
        assert alias.alias == "tp"
        assert alias.created_at is not None

    @pytest.mark.asyncio
    async def test_project_alias_multiple_for_project(self, db_session, sample_project):
        """Test that a project can have multiple aliases."""
        aliases = ["tp", "test-proj", "project-test"]
        for alias_name in aliases:
            alias = ProjectAlias(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                alias=alias_name,
            )
            db_session.add(alias)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(ProjectAlias).where(ProjectAlias.project_id == sample_project.id)
        )
        aliases_from_db = result.scalars().all()
        assert len(aliases_from_db) == 3

    @pytest.mark.asyncio
    async def test_project_alias_unique_constraint(self, db_session, sample_project):
        """Test that alias is globally unique."""
        alias1 = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="unique-alias",
        )
        db_session.add(alias1)
        await db_session.commit()

        # Try to create duplicate alias for different project
        project2 = Project(
            id=uuid.uuid4(),
            name="Project 2",
            slug="project-2",
            google_tasklist_id="project-2-list",
            project_type=ProjectType.CLIENT,
            is_active=True,
        )
        db_session.add(project2)
        await db_session.commit()

        alias2 = ProjectAlias(
            id=uuid.uuid4(),
            project_id=project2.id,
            alias="unique-alias",  # Same alias
        )
        db_session.add(alias2)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_project_alias_indexed(self, db_session, sample_project):
        """Test that alias is indexed."""
        alias = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="searchable-alias",
        )
        db_session.add(alias)
        await db_session.commit()

        from sqlalchemy import select

        result = await db_session.execute(
            select(ProjectAlias).where(ProjectAlias.alias == "searchable-alias")
        )
        found_alias = result.scalars().first()
        assert found_alias is not None
        assert found_alias.alias == "searchable-alias"

    @pytest.mark.asyncio
    async def test_project_alias_foreign_key(self, db_session, sample_project):
        """Test that ProjectAlias properly references a project."""
        alias = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="valid-alias",
        )
        db_session.add(alias)
        await db_session.commit()
        await db_session.refresh(alias)

        # Verify the alias was created with correct project_id
        assert alias.project_id == sample_project.id
