from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.admin_tasks_service import AdminTasksService, build_task_view
from core.domain.enums import WorkflowStatus
from core.schemas.admin import TaskDetailResult, TaskListResult, TaskView
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot
from db.models.task_revision import TaskRevision


def _make_record_and_snapshot(**overrides) -> tuple[TaskRecord, TaskSnapshot]:
    stable_id = overrides.pop("stable_id", uuid.uuid4())
    record = MagicMock(spec=TaskRecord)
    record.stable_id = stable_id
    record.processing_status = overrides.get("processing_status", WorkflowStatus.PENDING.value)
    record.state = overrides.get("state", "active")
    record.created_at = overrides.get(
        "created_at", datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    )
    record.updated_at = overrides.get(
        "updated_at", datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    )
    record.current_tasklist_id = overrides.get("current_tasklist_id", "list-1")
    record.current_task_id = overrides.get("current_task_id", "gtask-1")
    record.last_error = overrides.get("last_error", None)

    snapshot = MagicMock(spec=TaskSnapshot)
    snapshot.stable_id = stable_id
    snapshot.payload = overrides.get("payload", {"title": "buy milk", "notes": ""})
    snapshot.is_latest = True
    return record, snapshot


@pytest.fixture
def mock_record_repo():
    repo = MagicMock()
    repo.list_filtered = AsyncMock(return_value=[])
    repo.count_filtered = AsyncMock(return_value=0)
    repo.get_with_latest_snapshot = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_revision_repo():
    repo = MagicMock()
    repo.list_by_stable_id = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(mock_record_repo, mock_revision_repo):
    return AdminTasksService(record_repo=mock_record_repo, revision_repo=mock_revision_repo)


@pytest.fixture
def mock_session():
    return MagicMock()


class TestListTasks:
    @pytest.mark.asyncio
    async def test_list_tasks_returns_task_list_result(
        self, service, mock_record_repo, mock_session
    ):
        rows = [_make_record_and_snapshot(), _make_record_and_snapshot()]
        mock_record_repo.list_filtered.return_value = rows
        mock_record_repo.count_filtered.return_value = 2

        result = await service.list_tasks(session=mock_session)

        assert isinstance(result, TaskListResult)
        assert len(result.items) == 2
        assert all(isinstance(item, TaskView) for item in result.items)
        assert result.total == 2
        assert result.page == 1
        assert result.per_page == 25

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, service, mock_record_repo, mock_session):
        await service.list_tasks(session=mock_session, status=WorkflowStatus.APPLIED)

        mock_record_repo.list_filtered.assert_called_once_with(
            processing_status=WorkflowStatus.APPLIED,
            kind=None,
            project_id=None,
            search=None,
            limit=25,
            offset=0,
        )
        mock_record_repo.count_filtered.assert_called_once_with(
            processing_status=WorkflowStatus.APPLIED,
            kind=None,
            project_id=None,
            search=None,
        )

    @pytest.mark.asyncio
    async def test_list_tasks_with_kind_filter(self, service, mock_record_repo, mock_session):
        await service.list_tasks(session=mock_session, kind="idea")

        mock_record_repo.list_filtered.assert_called_once_with(
            processing_status=None,
            kind="idea",
            project_id=None,
            search=None,
            limit=25,
            offset=0,
        )
        mock_record_repo.count_filtered.assert_called_once_with(
            processing_status=None, kind="idea", project_id=None, search=None
        )

    @pytest.mark.asyncio
    async def test_list_tasks_with_search_parameter(self, service, mock_record_repo, mock_session):
        await service.list_tasks(session=mock_session, search="milk")

        mock_record_repo.list_filtered.assert_called_once_with(
            processing_status=None,
            kind=None,
            project_id=None,
            search="milk",
            limit=25,
            offset=0,
        )
        mock_record_repo.count_filtered.assert_called_once_with(
            processing_status=None, kind=None, project_id=None, search="milk"
        )

    @pytest.mark.asyncio
    async def test_list_tasks_with_project_id_filter(self, service, mock_record_repo, mock_session):
        pid = uuid.uuid4()
        await service.list_tasks(session=mock_session, project_id=pid)

        mock_record_repo.list_filtered.assert_called_once_with(
            processing_status=None,
            kind=None,
            project_id=pid,
            search=None,
            limit=25,
            offset=0,
        )
        mock_record_repo.count_filtered.assert_called_once_with(
            processing_status=None, kind=None, project_id=pid, search=None
        )

    @pytest.mark.asyncio
    async def test_list_tasks_pagination_total_pages(self, service, mock_record_repo, mock_session):
        mock_record_repo.count_filtered.return_value = 53

        result = await service.list_tasks(session=mock_session, page=3, per_page=10)

        assert result.total == 53
        assert result.page == 3
        assert result.per_page == 10
        assert result.total_pages == 6  # ceil(53/10)
        mock_record_repo.list_filtered.assert_called_once_with(
            processing_status=None, kind=None, project_id=None, search=None, limit=10, offset=20
        )

    @pytest.mark.asyncio
    async def test_list_tasks_pagination_total_pages_minimum_one(
        self, service, mock_record_repo, mock_session
    ):
        mock_record_repo.count_filtered.return_value = 0

        result = await service.list_tasks(session=mock_session)

        assert result.total_pages == 1


class TestGetTaskDetail:
    @pytest.mark.asyncio
    async def test_get_task_detail_returns_none_for_missing_task(
        self, service, mock_record_repo, mock_revision_repo, mock_session
    ):
        mock_record_repo.get_with_latest_snapshot.return_value = None

        result = await service.get_task_detail(session=mock_session, stable_id=uuid.uuid4())

        assert result is None
        mock_revision_repo.list_by_stable_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_task_detail_returns_task_and_revisions(
        self, service, mock_record_repo, mock_revision_repo, mock_session
    ):
        record, snapshot = _make_record_and_snapshot()
        revisions = [
            TaskRevision(
                id=uuid.uuid4(),
                revision_no=1,
                raw_text="original",
                proposal_json={},
                created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ),
            TaskRevision(
                id=uuid.uuid4(),
                revision_no=2,
                raw_text="edited",
                proposal_json={},
                created_at=datetime(2024, 6, 2, tzinfo=timezone.utc),
            ),
        ]
        mock_record_repo.get_with_latest_snapshot.return_value = (record, snapshot)
        mock_revision_repo.list_by_stable_id.return_value = revisions

        result = await service.get_task_detail(session=mock_session, stable_id=record.stable_id)

        assert isinstance(result, TaskDetailResult)
        assert isinstance(result.task, TaskView)
        assert result.task.id == record.stable_id
        assert result.revisions == revisions
        assert len(result.revisions) == 2
        mock_record_repo.get_with_latest_snapshot.assert_called_once_with(record.stable_id)
        mock_revision_repo.list_by_stable_id.assert_called_once_with(record.stable_id)
