"""
Integration tests for admin-panel repositories:
  - ProjectPromptVersionRepo
  - SystemEventRepo
  - ProjectAliasRepo

TDD: Written FIRST (RED), then implementations make them GREEN.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ProjectType
from db.base import Base
from db.models import Project, ProjectAlias, ProjectPromptVersion, SystemEvent


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
async def sample_project(db_session: AsyncSession) -> Project:
    """Create a project that FK columns can reference."""
    project = Project(
        id=uuid.uuid4(),
        name="Test Project",
        slug="test-project",
        google_tasklist_id="gtl-001",
        project_type=ProjectType.PERSONAL,
        is_active=True,
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def second_project(db_session: AsyncSession) -> Project:
    """A second project for cross-project queries."""
    project = Project(
        id=uuid.uuid4(),
        name="Second Project",
        slug="second-project",
        google_tasklist_id="gtl-002",
        project_type=ProjectType.CLIENT,
        is_active=True,
    )
    db_session.add(project)
    await db_session.flush()
    return project


# ── ProjectPromptVersionRepo ─────────────────────────────────────────────────


class TestProjectPromptVersionRepo:
    @pytest.mark.asyncio
    async def test_create_and_get_by_id(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        version_id = uuid.uuid4()
        pv = ProjectPromptVersion(
            id=version_id,
            project_id=sample_project.id,
            version_no=1,
            title="v1",
            classification_prompt_text="Classify this",
            is_active=True,
        )
        created = await repo.create(pv)
        await db_session.commit()

        fetched = await repo.get_by_id(version_id)
        assert fetched is not None
        assert fetched.title == "v1"
        assert fetched.version_no == 1
        assert fetched.is_active is True

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        fetched = await repo.get_by_id(uuid.uuid4())
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_by_project_ordered_desc(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        for i in [1, 3, 2]:
            pv = ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                version_no=i,
                is_active=False,
            )
            await repo.create(pv)
        await db_session.commit()

        versions = await repo.list_by_project(sample_project.id)
        assert [v.version_no for v in versions] == [3, 2, 1]

    @pytest.mark.asyncio
    async def test_list_by_project_with_limit_offset(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        for i in range(1, 6):
            pv = ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                version_no=i,
                is_active=False,
            )
            await repo.create(pv)
        await db_session.commit()

        # limit=2, offset=1 → skip newest, get next 2
        versions = await repo.list_by_project(sample_project.id, limit=2, offset=1)
        assert len(versions) == 2
        assert versions[0].version_no == 4
        assert versions[1].version_no == 3

    @pytest.mark.asyncio
    async def test_get_active_for_project(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        # Create inactive version
        await repo.create(
            ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                version_no=1,
                is_active=False,
            )
        )
        # Create active version
        active_id = uuid.uuid4()
        await repo.create(
            ProjectPromptVersion(
                id=active_id,
                project_id=sample_project.id,
                version_no=2,
                is_active=True,
            )
        )
        await db_session.commit()

        active = await repo.get_active_for_project(sample_project.id)
        assert active is not None
        assert active.id == active_id
        assert active.is_active is True

    @pytest.mark.asyncio
    async def test_get_active_for_project_none(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        # No versions at all
        active = await repo.get_active_for_project(sample_project.id)
        assert active is None

    @pytest.mark.asyncio
    async def test_get_all_active(self, db_session, sample_project, second_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        # Active version for project 1
        await repo.create(
            ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=sample_project.id,
                version_no=1,
                is_active=True,
            )
        )
        # Inactive version for project 2
        await repo.create(
            ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=second_project.id,
                version_no=1,
                is_active=False,
            )
        )
        # Active version for project 2
        await repo.create(
            ProjectPromptVersion(
                id=uuid.uuid4(),
                project_id=second_project.id,
                version_no=2,
                is_active=True,
            )
        )
        await db_session.commit()

        all_active = await repo.get_all_active()
        assert len(all_active) == 2

    @pytest.mark.asyncio
    async def test_get_next_version_no_empty(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        next_no = await repo.get_next_version_no(sample_project.id)
        assert next_no == 1

    @pytest.mark.asyncio
    async def test_get_next_version_no_increments(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        for i in [1, 2, 3]:
            await repo.create(
                ProjectPromptVersion(
                    id=uuid.uuid4(),
                    project_id=sample_project.id,
                    version_no=i,
                    is_active=False,
                )
            )
        await db_session.flush()

        next_no = await repo.get_next_version_no(sample_project.id)
        assert next_no == 4

    @pytest.mark.asyncio
    async def test_save_updates_fields(self, db_session, sample_project):
        from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

        repo = ProjectPromptVersionRepo(db_session)
        pv = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            version_no=1,
            title="Original",
            is_active=False,
        )
        await repo.create(pv)
        await db_session.commit()

        pv.title = "Updated"
        pv.is_active = True
        await repo.save(pv)
        await db_session.commit()

        fetched = await repo.get_by_id(pv.id)
        assert fetched is not None
        assert fetched.title == "Updated"
        assert fetched.is_active is True


# ── SystemEventRepo ──────────────────────────────────────────────────────────


class TestSystemEventRepo:
    @pytest.mark.asyncio
    async def test_create_event(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="intake.started",
            severity="info",
            subsystem="intake",
            message="Task intake started",
        )
        created = await repo.create(event)
        await db_session.commit()
        assert created.id is not None
        assert created.event_type == "intake.started"

    @pytest.mark.asyncio
    async def test_list_events_no_filter(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        now = datetime.now(tz=timezone.utc)
        for i in range(3):
            await repo.create(
                SystemEvent(
                    id=uuid.uuid4(),
                    event_type="test",
                    severity="info",
                    subsystem="test",
                    message=f"Event {i}",
                    created_at=now - timedelta(minutes=i),
                )
            )
        await db_session.commit()

        events = await repo.list_events()
        assert len(events) == 3
        # Ordered by created_at DESC
        assert events[0].message == "Event 0"
        assert events[2].message == "Event 2"

    @pytest.mark.asyncio
    async def test_list_events_filter_by_type(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="intake.started",
                severity="info",
                subsystem="intake",
                message="A",
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="llm.error",
                severity="error",
                subsystem="llm",
                message="B",
            )
        )
        await db_session.commit()

        events = await repo.list_events(event_type="llm.error")
        assert len(events) == 1
        assert events[0].message == "B"

    @pytest.mark.asyncio
    async def test_list_events_filter_by_severity(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="t", severity="warning", subsystem="s", message="W"
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="t", severity="info", subsystem="s", message="I"
            )
        )
        await db_session.commit()

        events = await repo.list_events(severity="warning")
        assert len(events) == 1
        assert events[0].message == "W"

    @pytest.mark.asyncio
    async def test_list_events_filter_by_subsystem(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="t", severity="info", subsystem="intake", message="A"
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="t", severity="info", subsystem="llm", message="B"
            )
        )
        await db_session.commit()

        events = await repo.list_events(subsystem="intake")
        assert len(events) == 1
        assert events[0].message == "A"

    @pytest.mark.asyncio
    async def test_list_events_filter_since(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        now = datetime.now(tz=timezone.utc)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="t",
                severity="info",
                subsystem="s",
                message="old",
                created_at=now - timedelta(hours=2),
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="t",
                severity="info",
                subsystem="s",
                message="new",
                created_at=now,
            )
        )
        await db_session.commit()

        events = await repo.list_events(since=now - timedelta(hours=1))
        assert len(events) == 1
        assert events[0].message == "new"

    @pytest.mark.asyncio
    async def test_list_events_combined_filters(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        now = datetime.now(tz=timezone.utc)
        # Matches all filters
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="intake.started",
                severity="error",
                subsystem="intake",
                message="target",
                created_at=now,
            )
        )
        # Wrong severity
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="intake.started",
                severity="info",
                subsystem="intake",
                message="decoy",
                created_at=now,
            )
        )
        await db_session.commit()

        events = await repo.list_events(
            event_type="intake.started", severity="error", subsystem="intake"
        )
        assert len(events) == 1
        assert events[0].message == "target"

    @pytest.mark.asyncio
    async def test_list_events_limit_offset(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        now = datetime.now(tz=timezone.utc)
        for i in range(5):
            await repo.create(
                SystemEvent(
                    id=uuid.uuid4(),
                    event_type="t",
                    severity="info",
                    subsystem="s",
                    message=f"E{i}",
                    created_at=now - timedelta(minutes=i),
                )
            )
        await db_session.commit()

        events = await repo.list_events(limit=2, offset=1)
        assert len(events) == 2
        assert events[0].message == "E1"
        assert events[1].message == "E2"

    @pytest.mark.asyncio
    async def test_count_events_no_filter(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        for _ in range(3):
            await repo.create(
                SystemEvent(
                    id=uuid.uuid4(), event_type="t", severity="info", subsystem="s", message="m"
                )
            )
        await db_session.commit()

        count = await repo.count_events()
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_events_with_filter(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="a", severity="error", subsystem="s", message="m"
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(), event_type="b", severity="info", subsystem="s", message="m"
            )
        )
        await db_session.commit()

        count = await repo.count_events(severity="error")
        assert count == 1

    @pytest.mark.asyncio
    async def test_count_by_severity(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        for severity, n in [("info", 3), ("warning", 2), ("error", 1)]:
            for _ in range(n):
                await repo.create(
                    SystemEvent(
                        id=uuid.uuid4(),
                        event_type="t",
                        severity=severity,
                        subsystem="s",
                        message="m",
                    )
                )
        await db_session.commit()

        counts = await repo.count_by_severity()
        assert counts["info"] == 3
        assert counts["warning"] == 2
        assert counts["error"] == 1

    @pytest.mark.asyncio
    async def test_count_by_severity_with_since(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        now = datetime.now(tz=timezone.utc)
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="t",
                severity="error",
                subsystem="s",
                message="old",
                created_at=now - timedelta(hours=2),
            )
        )
        await repo.create(
            SystemEvent(
                id=uuid.uuid4(),
                event_type="t",
                severity="error",
                subsystem="s",
                message="new",
                created_at=now,
            )
        )
        await db_session.commit()

        counts = await repo.count_by_severity(since=now - timedelta(hours=1))
        assert counts.get("error", 0) == 1

    @pytest.mark.asyncio
    async def test_count_by_severity_empty(self, db_session):
        from db.repositories.system_event_repo import SystemEventRepo

        repo = SystemEventRepo(db_session)
        counts = await repo.count_by_severity()
        # Should return empty dict or at least no crash
        assert isinstance(counts, dict)


# ── ProjectAliasRepo ─────────────────────────────────────────────────────────


class TestProjectAliasRepo:
    @pytest.mark.asyncio
    async def test_create_and_get_by_alias(self, db_session, sample_project):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        alias = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="nft-gw",
        )
        await repo.create(alias)
        await db_session.commit()

        fetched = await repo.get_by_alias("nft-gw")
        assert fetched is not None
        assert fetched.alias == "nft-gw"

    @pytest.mark.asyncio
    async def test_get_by_alias_case_insensitive(self, db_session, sample_project):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        alias = ProjectAlias(
            id=uuid.uuid4(),
            project_id=sample_project.id,
            alias="MyAlias",
        )
        await repo.create(alias)
        await db_session.commit()

        # Search with different casing
        fetched = await repo.get_by_alias("myalias")
        assert fetched is not None
        assert fetched.alias == "MyAlias"

        fetched2 = await repo.get_by_alias("MYALIAS")
        assert fetched2 is not None

    @pytest.mark.asyncio
    async def test_get_by_alias_not_found(self, db_session):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        fetched = await repo.get_by_alias("nonexistent")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_by_project(self, db_session, sample_project, second_project):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        await repo.create(
            ProjectAlias(id=uuid.uuid4(), project_id=sample_project.id, alias="alias-a")
        )
        await repo.create(
            ProjectAlias(id=uuid.uuid4(), project_id=sample_project.id, alias="alias-b")
        )
        await repo.create(
            ProjectAlias(id=uuid.uuid4(), project_id=second_project.id, alias="alias-c")
        )
        await db_session.commit()

        aliases = await repo.list_by_project(sample_project.id)
        assert len(aliases) == 2
        alias_strs = {a.alias for a in aliases}
        assert alias_strs == {"alias-a", "alias-b"}

    @pytest.mark.asyncio
    async def test_delete(self, db_session, sample_project):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        alias_id = uuid.uuid4()
        await repo.create(
            ProjectAlias(id=alias_id, project_id=sample_project.id, alias="to-delete")
        )
        await db_session.commit()

        await repo.delete(alias_id)
        await db_session.commit()

        fetched = await repo.get_by_alias("to-delete")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_all_aliases_map(self, db_session, sample_project, second_project):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        await repo.create(
            ProjectAlias(id=uuid.uuid4(), project_id=sample_project.id, alias="alpha")
        )
        await repo.create(ProjectAlias(id=uuid.uuid4(), project_id=sample_project.id, alias="beta"))
        await repo.create(
            ProjectAlias(id=uuid.uuid4(), project_id=second_project.id, alias="gamma")
        )
        await db_session.commit()

        alias_map = await repo.get_all_aliases_map()
        assert isinstance(alias_map, dict)
        assert len(alias_map) == 3
        assert alias_map["alpha"] == sample_project.id
        assert alias_map["beta"] == sample_project.id
        assert alias_map["gamma"] == second_project.id

    @pytest.mark.asyncio
    async def test_get_all_aliases_map_empty(self, db_session):
        from db.repositories.project_alias_repo import ProjectAliasRepo

        repo = ProjectAliasRepo(db_session)
        alias_map = await repo.get_all_aliases_map()
        assert alias_map == {}
