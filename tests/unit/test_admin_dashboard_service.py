from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.schemas.admin import DashboardStats
from db.models.system_event import SystemEvent


@pytest.fixture
def mock_project_repo():
    repo = MagicMock()
    repo.list_active = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_event_repo():
    repo = MagicMock()
    repo.list_events = AsyncMock(return_value=[])
    repo.count_events = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.fixture
def service(mock_project_repo, mock_event_repo):
    from apps.api.services.admin_dashboard_service import AdminDashboardService

    return AdminDashboardService(
        project_repo=mock_project_repo,
        event_repo=mock_event_repo,
    )


def _mock_scalar_one(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _mock_rows(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestGetDashboardStats:
    async def test_returns_dashboard_stats_object(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(0),  # total_tasks (TaskRecord count)
                _mock_rows([]),  # tasks_by_status (processing_status)
                _mock_scalar_one(0),  # tasks_today
                _mock_rows([]),  # tasks_by_kind (JSONB)
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert isinstance(result, DashboardStats)

    async def test_total_tasks_is_correct_count(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(42),
                _mock_rows([]),
                _mock_scalar_one(0),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.total_tasks == 42

    async def test_tasks_by_status_is_dict_with_status_keys(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(15),
                _mock_rows(
                    [
                        ("pending", 5),
                        ("processing", 3),
                        ("applied", 7),
                    ]
                ),
                _mock_scalar_one(2),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.tasks_by_status == {
            "pending": 5,
            "processing": 3,
            "applied": 7,
        }

    async def test_recent_events_limited_to_10(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        events = [
            SystemEvent(
                id=uuid.uuid4(),
                event_type="test",
                severity="info",
                subsystem="test",
                message=f"Event {i}",
                created_at=datetime.now(timezone.utc),
            )
            for i in range(10)
        ]
        mock_event_repo.list_events.return_value = events

        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(0),
                _mock_rows([]),
                _mock_scalar_one(0),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.recent_events == events
        assert len(result.recent_events) == 10
        mock_event_repo.list_events.assert_called_once_with(limit=10)

    async def test_error_count_24h_counts_only_error_severity(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_event_repo.count_events.return_value = 7

        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(0),
                _mock_rows([]),
                _mock_scalar_one(0),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.error_count_24h == 7
        mock_event_repo.count_events.assert_called_once()
        call_kwargs = mock_event_repo.count_events.call_args
        assert call_kwargs.kwargs["severity"] == "error"
        since_arg = call_kwargs.kwargs["since"]
        expected_since = datetime.now(timezone.utc) - timedelta(hours=24)
        assert abs((since_arg - expected_since).total_seconds()) < 5

    async def test_active_projects_count(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        from db.models.project import Project

        mock_project_repo.list_active.return_value = [
            MagicMock(spec=Project),
            MagicMock(spec=Project),
            MagicMock(spec=Project),
        ]

        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(0),
                _mock_rows([]),
                _mock_scalar_one(0),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.active_projects == 3
        mock_project_repo.list_active.assert_called_once()

    async def test_tasks_today_count(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(100),
                _mock_rows([]),
                _mock_scalar_one(5),
                _mock_rows([]),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.tasks_today == 5

    async def test_tasks_by_kind_mapping(
        self, service, mock_session, mock_project_repo, mock_event_repo
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(10),
                _mock_rows([]),
                _mock_scalar_one(0),
                _mock_rows(
                    [
                        ("task", 6),
                        ("idea", 4),
                    ]
                ),
            ]
        )

        result = await service.get_dashboard_stats(mock_session)

        assert result.tasks_by_kind == {
            "task": 6,
            "idea": 4,
        }


class TestDashboardStatsDefaults:
    def test_default_values(self):
        stats = DashboardStats()

        assert stats.total_tasks == 0
        assert stats.tasks_by_status == {}
        assert stats.tasks_today == 0
        assert stats.active_projects == 0
        assert stats.recent_events == []
        assert stats.error_count_24h == 0
        assert stats.tasks_by_kind == {}
