from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.project_sync_service import ProjectSyncService
from core.utils.text import slugify
from db.models.project import Project


@pytest.fixture
def mock_google_tasks() -> Any:
    service = MagicMock()
    service.list_tasklists = MagicMock(return_value=[])
    return service


@pytest.fixture
def mock_project_repo() -> Any:
    repo = MagicMock()
    repo.get_by_google_tasklist_id = AsyncMock(return_value=None)
    repo.get_by_slug = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.create = AsyncMock()
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_session() -> Any:
    session = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def service(mock_google_tasks: Any, mock_project_repo: Any) -> ProjectSyncService:
    return ProjectSyncService(
        google_tasks=mock_google_tasks,
        project_repo=mock_project_repo,
    )


def _make_existing_project(name: str, tasklist_id: str) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=name,
        slug=slugify(name),
        google_tasklist_id=tasklist_id,
        project_type="personal",
        is_active=True,
    )


class TestSyncFromGoogle:
    @pytest.mark.asyncio
    async def test_sync_creates_new_project_for_unknown_tasklist(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-1", "title": "Finance"},
        ]

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result == {"created": ["Finance"], "updated": [], "deactivated": [], "skipped": []}
        mock_project_repo.get_by_google_tasklist_id.assert_awaited_once_with("list-1")
        mock_project_repo.create.assert_awaited_once()
        created_project = mock_project_repo.create.await_args.args[0]
        assert isinstance(created_project, Project)
        assert created_project.name == "Finance"
        assert created_project.slug == slugify("Finance")
        assert created_project.google_tasklist_id == "list-1"
        assert created_project.project_type == "personal"
        assert created_project.is_active is True

    @pytest.mark.asyncio
    async def test_sync_updates_project_name_when_google_title_changes(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Old Name", tasklist_id="list-1")
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-1", "title": "New Name"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result == {"created": [], "updated": ["New Name"], "deactivated": [], "skipped": []}
        assert existing.name == "New Name"
        assert existing.slug == slugify("New Name")
        mock_project_repo.save.assert_awaited_once_with(existing)
        mock_project_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_skips_tasklist_when_project_name_matches(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Fitness", tasklist_id="list-2")
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-2", "title": "Fitness"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result == {"created": [], "updated": [], "deactivated": [], "skipped": ["Fitness"]}
        mock_project_repo.save.assert_not_awaited()
        mock_project_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_creates_inbox_as_personal_project(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "inbox-list", "title": "Inbox"},
            {"id": "list-3", "title": "Work"},
        ]

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert "Inbox" in result["created"]
        assert "Work" in result["created"]
        assert mock_project_repo.create.await_count == 2

    @pytest.mark.asyncio
    async def test_sync_handles_empty_tasklists(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = []

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result == {"created": [], "updated": [], "deactivated": [], "skipped": []}
        mock_project_repo.get_by_google_tasklist_id.assert_not_awaited()
        mock_project_repo.create.assert_not_awaited()
        mock_project_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_returns_created_updated_and_skipped_lists(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        unchanged = _make_existing_project(name="Same Name", tasklist_id="list-keep")
        needs_update = _make_existing_project(name="Before", tasklist_id="list-update")

        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-create", "title": "Brand New"},
            {"id": "list-update", "title": "After"},
            {"id": "list-keep", "title": "Same Name"},
            {"id": "inbox-list", "title": "Inbox"},
        ]

        async def get_existing(tasklist_id: str):
            if tasklist_id == "list-update":
                return needs_update
            if tasklist_id == "list-keep":
                return unchanged
            return None

        mock_project_repo.get_by_google_tasklist_id.side_effect = get_existing

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result == {
            "created": ["Brand New", "Inbox"],
            "updated": ["After"],
            "deactivated": [],
            "skipped": ["Same Name"],
        }
        assert mock_project_repo.create.await_count == 2
        mock_project_repo.save.assert_awaited_once_with(needs_update)

    @pytest.mark.asyncio
    async def test_sync_commits_session_after_processing(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-1", "title": "Personal"},
        ]
        mock_project_repo.create = AsyncMock(side_effect=[MagicMock()])

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        mock_session.commit.assert_awaited_once()
