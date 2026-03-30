from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.project_sync_service import (
    EVENT_PROJECT_DELETED,
    EVENT_PROJECT_DISCOVERED,
    EVENT_PROJECT_REACTIVATED,
    EVENT_PROJECT_RENAMED,
    ProjectSyncService,
)
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
def mock_event_repo() -> Any:
    repo = MagicMock()
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def mock_session() -> Any:
    session = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def service(
    mock_google_tasks: Any,
    mock_project_repo: Any,
    mock_event_repo: Any,
) -> ProjectSyncService:
    return ProjectSyncService(
        google_tasks=mock_google_tasks,
        project_repo=mock_project_repo,
        event_repo=mock_event_repo,
    )


def _make_existing_project(
    name: str,
    tasklist_id: str,
    *,
    is_active: bool = True,
    deleted_at: datetime | None = None,
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    last_synced_name: str | None = None,
) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=name,
        slug=slugify(name),
        google_tasklist_id=tasklist_id,
        project_type="personal",
        is_active=is_active,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        deleted_at=deleted_at,
        last_synced_name=last_synced_name,
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
        mock_project_repo.save.assert_awaited_once_with(existing)
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
        assert mock_project_repo.save.await_count == 0

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
        assert mock_project_repo.save.await_count == 2

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


class TestLifecycleTimestamps:
    @pytest.mark.asyncio
    async def test_new_project_has_first_seen_at_and_last_seen_at(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "new-1", "title": "New Project"},
        ]

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        created_project = mock_project_repo.create.await_args.args[0]
        assert created_project.first_seen_at is not None
        assert created_project.last_seen_at is not None
        assert created_project.first_seen_at == created_project.last_seen_at
        assert created_project.deleted_at is None

    @pytest.mark.asyncio
    async def test_existing_project_updates_last_seen_at_on_every_sync(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        existing = _make_existing_project(
            name="Stable",
            tasklist_id="list-stable",
            first_seen_at=old_time,
            last_seen_at=old_time,
        )
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-stable", "title": "Stable"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert existing.last_seen_at is not None
        assert existing.last_seen_at > old_time
        assert existing.first_seen_at == old_time


class TestRenameTracking:
    @pytest.mark.asyncio
    async def test_rename_sets_last_synced_name_to_old_name(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Alpha", tasklist_id="list-alpha")
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-alpha", "title": "Beta"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert existing.last_synced_name == "Alpha"
        assert existing.name == "Beta"
        assert existing.slug == slugify("Beta")

    @pytest.mark.asyncio
    async def test_rename_preserves_project_identity(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        """Renaming must NOT create a new project — same id, same google_tasklist_id."""
        original_id = uuid.uuid4()
        existing = _make_existing_project(name="Original", tasklist_id="list-rename")
        existing.id = original_id
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-rename", "title": "Renamed"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        mock_project_repo.create.assert_not_awaited()
        mock_project_repo.save.assert_awaited_once_with(existing)
        assert existing.id == original_id
        assert existing.google_tasklist_id == "list-rename"

    @pytest.mark.asyncio
    async def test_rename_emits_project_renamed_event(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="OldTitle", tasklist_id="list-ev")
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-ev", "title": "NewTitle"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        calls = mock_event_repo.create.await_args_list
        rename_events = [c.args[0] for c in calls if c.args[0].event_type == EVENT_PROJECT_RENAMED]
        assert len(rename_events) == 1
        ev = rename_events[0]
        assert ev.payload_json["old_name"] == "OldTitle"
        assert ev.payload_json["new_name"] == "NewTitle"
        assert ev.project_id == existing.id


class TestDeactivation:
    @pytest.mark.asyncio
    async def test_missing_project_is_deactivated_with_deleted_at(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Gone", tasklist_id="list-gone")
        mock_google_tasks.list_tasklists.return_value = []
        mock_project_repo.list_all.return_value = [existing]

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result["deactivated"] == ["Gone"]
        assert existing.is_active is False
        assert existing.deleted_at is not None

    @pytest.mark.asyncio
    async def test_deactivation_emits_project_deleted_event(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Vanished", tasklist_id="list-vanish")
        mock_google_tasks.list_tasklists.return_value = []
        mock_project_repo.list_all.return_value = [existing]

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        calls = mock_event_repo.create.await_args_list
        delete_events = [c.args[0] for c in calls if c.args[0].event_type == EVENT_PROJECT_DELETED]
        assert len(delete_events) == 1
        assert delete_events[0].project_id == existing.id

    @pytest.mark.asyncio
    async def test_already_inactive_project_is_not_deactivated_again(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(
            name="AlreadyGone",
            tasklist_id="list-already",
            is_active=False,
            deleted_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        mock_google_tasks.list_tasklists.return_value = []
        mock_project_repo.list_all.return_value = [existing]

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result["deactivated"] == []
        calls = mock_event_repo.create.await_args_list
        delete_events = [c.args[0] for c in calls if c.args[0].event_type == EVENT_PROJECT_DELETED]
        assert len(delete_events) == 0


class TestReactivation:
    @pytest.mark.asyncio
    async def test_reactivation_clears_deleted_at_and_sets_is_active(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(
            name="Comeback",
            tasklist_id="list-cb",
            is_active=False,
            deleted_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-cb", "title": "Comeback"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        result = await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result["updated"] == ["Comeback"]
        assert existing.is_active is True
        assert existing.deleted_at is None

    @pytest.mark.asyncio
    async def test_reactivation_emits_project_reactivated_event(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(
            name="ReturnProject",
            tasklist_id="list-return",
            is_active=False,
            deleted_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-return", "title": "ReturnProject"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        calls = mock_event_repo.create.await_args_list
        react_events = [
            c.args[0] for c in calls if c.args[0].event_type == EVENT_PROJECT_REACTIVATED
        ]
        assert len(react_events) == 1
        assert react_events[0].project_id == existing.id


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_new_project_emits_project_discovered_event(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-disc", "title": "Discovered"},
        ]

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        calls = mock_event_repo.create.await_args_list
        disc_events = [c.args[0] for c in calls if c.args[0].event_type == EVENT_PROJECT_DISCOVERED]
        assert len(disc_events) == 1
        ev = disc_events[0]
        assert ev.subsystem == "project_sync"
        assert ev.payload_json["google_tasklist_id"] == "list-disc"
        assert "Discovered" in ev.message

    @pytest.mark.asyncio
    async def test_no_events_emitted_when_event_repo_is_none(
        self,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_session: Any,
    ):
        service_no_events = ProjectSyncService(
            google_tasks=mock_google_tasks,
            project_repo=mock_project_repo,
            event_repo=None,
        )
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-no-ev", "title": "NoEvent"},
        ]

        result = await service_no_events.sync_from_google(mock_session, inbox_list_id="inbox-list")

        assert result["created"] == ["NoEvent"]

    @pytest.mark.asyncio
    async def test_unchanged_project_emits_no_events(
        self,
        service: ProjectSyncService,
        mock_google_tasks: Any,
        mock_project_repo: Any,
        mock_event_repo: Any,
        mock_session: Any,
    ):
        existing = _make_existing_project(name="Stable", tasklist_id="list-stable")
        mock_google_tasks.list_tasklists.return_value = [
            {"id": "list-stable", "title": "Stable"},
        ]
        mock_project_repo.get_by_google_tasklist_id.return_value = existing

        await service.sync_from_google(mock_session, inbox_list_id="inbox-list")

        mock_event_repo.create.assert_not_awaited()


class TestSyncWorkerProjectIntegration:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "project_result",
        [
            {"created": ["New"], "updated": [], "deactivated": [], "skipped": []},
            {"created": [], "updated": ["Renamed"], "deactivated": [], "skipped": []},
            {"created": [], "updated": [], "deactivated": ["Deleted"], "skipped": []},
        ],
        ids=["new-project", "renamed-project", "deleted-project"],
    )
    async def test_sync_worker_includes_project_changes_in_telegram_message(self, project_result):
        from unittest.mock import patch

        from apps.api.services.sync_service import SyncCycleSummary

        summary = SyncCycleSummary(
            tasklists_scanned=2,
            tasks_scanned=5,
            new_count=0,
            updated_count=0,
            moved_count=0,
            deleted_count=0,
            queued_count=0,
        )

        with (
            patch("apps.api.workers.sync_worker.get_settings") as mock_settings,
            patch("apps.api.workers.sync_worker.GoogleTasksService") as mock_gts,
            patch("apps.api.workers.sync_worker.TelegramService") as mock_tg,
            patch("apps.api.workers.sync_worker.SyncService") as mock_sync,
            patch("apps.api.workers.sync_worker.TaskChangeMonitor") as mock_monitor,
            patch("apps.api.workers.sync_worker.AlertService") as mock_alert,
            patch("apps.api.workers.sync_worker.get_session_factory") as mock_factory,
            patch("apps.api.workers.sync_worker.ProjectSyncService") as mock_ps,
            patch("apps.api.workers.sync_worker.ProjectRepository"),
            patch("apps.api.workers.sync_worker.SystemEventRepo"),
        ):
            settings = MagicMock(
                google_credentials_file="creds.json",
                telegram_bot_token="token",
                telegram_chat_id="chat",
                google_tasks_inbox_list_id="inbox-id",
            )
            mock_settings.return_value = settings
            mock_gts.return_value = MagicMock()

            telegram = MagicMock()
            telegram.send_text = AsyncMock()
            telegram.aclose = AsyncMock()
            mock_tg.return_value = telegram

            project_sync_instance = MagicMock()
            project_sync_instance.sync_from_google = AsyncMock(return_value=project_result)
            mock_ps.return_value = project_sync_instance

            sync_service = MagicMock()
            sync_service.sync_all = AsyncMock(return_value=summary)
            mock_sync.return_value = sync_service

            change_monitor = MagicMock()
            change_monitor.capture_baseline = AsyncMock()
            change_monitor.detect_changes = AsyncMock(return_value=[])
            change_monitor.log_all_changes = AsyncMock()
            mock_monitor.return_value = change_monitor

            mock_alert.return_value = MagicMock()

            session = MagicMock()
            session.rollback = AsyncMock()
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value = MagicMock(return_value=ctx)

            from apps.api.workers.sync_worker import run_sync

            await run_sync()

            project_sync_instance.sync_from_google.assert_awaited_once()
            telegram.send_text.assert_awaited_once()
            msg = telegram.send_text.await_args[0][0]

            if project_result["created"]:
                assert "New projects" in msg
            if project_result["updated"]:
                assert "Updated projects" in msg
            if project_result["deactivated"]:
                assert "Removed projects" in msg
