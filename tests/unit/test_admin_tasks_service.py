"""
Unit tests for AdminTasksService.
Tests task listing with filters, pagination, search, and task detail retrieval.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.admin_tasks_service import AdminTasksService
from core.domain.enums import TaskKind, TaskStatus
from core.schemas.admin import TaskDetailResult, TaskListResult
from db.models.task_item import TaskItem
from db.models.task_revision import TaskRevision


@pytest.fixture
def mock_task_repo():
    """Mock TaskItemRepository."""
    repo = MagicMock()
    repo.list_tasks_filtered = AsyncMock(return_value=[])
    repo.count_tasks_filtered = AsyncMock(return_value=0)
    repo.get_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_revision_repo():
    """Mock TaskRevisionRepository."""
    repo = MagicMock()
    repo.list_by_task = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(mock_task_repo, mock_revision_repo):
    """Create AdminTasksService with mocked repos."""
    return AdminTasksService(task_repo=mock_task_repo, revision_repo=mock_revision_repo)


@pytest.fixture
def mock_session():
    """Mock AsyncSession."""
    return MagicMock()


def _make_task(**overrides) -> TaskItem:
    """Helper to build a TaskItem with sensible defaults."""
    defaults = dict(
        id=uuid.uuid4(),
        source_google_task_id=f"gtask-{uuid.uuid4().hex[:8]}",
        source_google_tasklist_id="inbox-list",
        raw_text="buy milk",
        status=TaskStatus.NEW,
        is_processed=False,
        created_at=datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    task = TaskItem(**defaults)
    return task


class TestListTasks:
    """Tests for list_tasks method."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_task_list_result(self, service, mock_task_repo, mock_session):
        """list_tasks returns a TaskListResult with items and total."""
        tasks = [_make_task(), _make_task()]
        mock_task_repo.list_tasks_filtered.return_value = tasks
        mock_task_repo.count_tasks_filtered.return_value = 2

        result = await service.list_tasks(session=mock_session)

        assert isinstance(result, TaskListResult)
        assert result.items == tasks
        assert result.total == 2
        assert result.page == 1
        assert result.per_page == 25

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, service, mock_task_repo, mock_session):
        """list_tasks passes status filter to repo."""
        await service.list_tasks(session=mock_session, status=TaskStatus.ROUTED)

        mock_task_repo.list_tasks_filtered.assert_called_once_with(
            TaskStatus.ROUTED, None, None, None, 25, 0
        )
        mock_task_repo.count_tasks_filtered.assert_called_once_with(
            TaskStatus.ROUTED, None, None, None
        )

    @pytest.mark.asyncio
    async def test_list_tasks_with_kind_filter(self, service, mock_task_repo, mock_session):
        """list_tasks passes kind filter to repo."""
        await service.list_tasks(session=mock_session, kind=TaskKind.IDEA)

        mock_task_repo.list_tasks_filtered.assert_called_once_with(
            None, TaskKind.IDEA, None, None, 25, 0
        )
        mock_task_repo.count_tasks_filtered.assert_called_once_with(None, TaskKind.IDEA, None, None)

    @pytest.mark.asyncio
    async def test_list_tasks_with_search_parameter(self, service, mock_task_repo, mock_session):
        """list_tasks passes search term to repo."""
        await service.list_tasks(session=mock_session, search="milk")

        mock_task_repo.list_tasks_filtered.assert_called_once_with(None, None, None, "milk", 25, 0)
        mock_task_repo.count_tasks_filtered.assert_called_once_with(None, None, None, "milk")

    @pytest.mark.asyncio
    async def test_list_tasks_with_project_id_filter(self, service, mock_task_repo, mock_session):
        """list_tasks passes project_id filter to repo."""
        pid = uuid.uuid4()
        await service.list_tasks(session=mock_session, project_id=pid)

        mock_task_repo.list_tasks_filtered.assert_called_once_with(None, None, pid, None, 25, 0)
        mock_task_repo.count_tasks_filtered.assert_called_once_with(None, None, pid, None)

    @pytest.mark.asyncio
    async def test_list_tasks_pagination_total_pages(self, service, mock_task_repo, mock_session):
        """total_pages is calculated correctly from total and per_page."""
        mock_task_repo.count_tasks_filtered.return_value = 53

        result = await service.list_tasks(session=mock_session, page=3, per_page=10)

        assert result.total == 53
        assert result.page == 3
        assert result.per_page == 10
        assert result.total_pages == 6  # ceil(53/10)
        # verify offset: (3-1)*10 = 20
        mock_task_repo.list_tasks_filtered.assert_called_once_with(None, None, None, None, 10, 20)

    @pytest.mark.asyncio
    async def test_list_tasks_pagination_total_pages_minimum_one(
        self, service, mock_task_repo, mock_session
    ):
        """total_pages is at least 1 even when total is 0."""
        mock_task_repo.count_tasks_filtered.return_value = 0

        result = await service.list_tasks(session=mock_session)

        assert result.total_pages == 1


class TestGetTaskDetail:
    """Tests for get_task_detail method."""

    @pytest.mark.asyncio
    async def test_get_task_detail_returns_none_for_missing_task(
        self, service, mock_task_repo, mock_revision_repo, mock_session
    ):
        """get_task_detail returns None when task not found."""
        mock_task_repo.get_by_id.return_value = None

        result = await service.get_task_detail(session=mock_session, task_id=uuid.uuid4())

        assert result is None
        mock_revision_repo.list_by_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_task_detail_returns_task_and_revisions(
        self, service, mock_task_repo, mock_revision_repo, mock_session
    ):
        """get_task_detail returns TaskDetailResult with task and revisions."""
        task = _make_task()
        revisions = [
            TaskRevision(
                id=uuid.uuid4(),
                task_item_id=task.id,
                revision_no=1,
                raw_text="original",
                proposal_json={},
                created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ),
            TaskRevision(
                id=uuid.uuid4(),
                task_item_id=task.id,
                revision_no=2,
                raw_text="edited",
                proposal_json={},
                created_at=datetime(2024, 6, 2, tzinfo=timezone.utc),
            ),
        ]
        mock_task_repo.get_by_id.return_value = task
        mock_revision_repo.list_by_task.return_value = revisions

        result = await service.get_task_detail(session=mock_session, task_id=task.id)

        assert isinstance(result, TaskDetailResult)
        assert result.task is task
        assert result.revisions == revisions
        assert len(result.revisions) == 2
        mock_task_repo.get_by_id.assert_called_once_with(task.id)
        mock_revision_repo.list_by_task.assert_called_once_with(task.id)
