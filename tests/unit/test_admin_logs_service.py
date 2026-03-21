"""Unit tests for AdminLogsService."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.admin_logs_service import AdminLogsService
from core.schemas.admin import EventListResult
from db.models.system_event import SystemEvent


@pytest.fixture
def mock_event_repo():
    """Create a mock SystemEventRepo."""
    return MagicMock()


@pytest.fixture
def admin_logs_service(mock_event_repo):
    """Create AdminLogsService instance with mocked repo."""
    return AdminLogsService(mock_event_repo)


@pytest.fixture
def sample_events():
    """Create sample SystemEvent objects for testing."""
    now = datetime.now()
    return [
        SystemEvent(
            id="event-1",
            event_type="task_created",
            severity="info",
            subsystem="task_intake",
            message="Task created",
            created_at=now,
        ),
        SystemEvent(
            id="event-2",
            event_type="classification_failed",
            severity="error",
            subsystem="llm",
            message="Classification failed",
            created_at=now - timedelta(hours=1),
        ),
    ]


class TestAdminLogsServiceListEvents:
    """Test list_events method."""

    async def test_list_events_returns_event_list_result(
        self, admin_logs_service, mock_event_repo, sample_events
    ):
        """Test that list_events returns EventListResult with correct items."""
        mock_event_repo.list_events = AsyncMock(return_value=sample_events)
        mock_event_repo.count_events = AsyncMock(return_value=2)

        result = await admin_logs_service.list_events(session=None)

        assert isinstance(result, EventListResult)
        assert result.items == sample_events
        assert result.total == 2
        assert result.page == 1
        assert result.per_page == 50

    async def test_list_events_with_event_type_filter(
        self, admin_logs_service, mock_event_repo, sample_events
    ):
        """Test that list_events with event_type filter delegates to repo correctly."""
        filtered_events = sample_events[:1]
        mock_event_repo.list_events = AsyncMock(return_value=filtered_events)
        mock_event_repo.count_events = AsyncMock(return_value=1)

        result = await admin_logs_service.list_events(session=None, event_type="task_created")

        mock_event_repo.list_events.assert_called_once_with("task_created", None, None, None, 50, 0)
        assert result.total == 1
        assert len(result.items) == 1

    async def test_list_events_with_severity_filter(
        self, admin_logs_service, mock_event_repo, sample_events
    ):
        """Test that list_events with severity filter."""
        error_events = [sample_events[1]]
        mock_event_repo.list_events = AsyncMock(return_value=error_events)
        mock_event_repo.count_events = AsyncMock(return_value=1)

        result = await admin_logs_service.list_events(session=None, severity="error")

        mock_event_repo.list_events.assert_called_once_with(None, "error", None, None, 50, 0)
        assert result.total == 1

    async def test_list_events_pagination_calculates_total_pages(
        self, admin_logs_service, mock_event_repo
    ):
        """Test that list_events pagination calculates total_pages correctly."""
        mock_event_repo.list_events = AsyncMock(return_value=[])
        mock_event_repo.count_events = AsyncMock(return_value=150)

        result = await admin_logs_service.list_events(session=None, page=2, per_page=50)

        assert result.total == 150
        assert result.total_pages == 3
        assert result.page == 2
        assert result.per_page == 50

    async def test_list_events_pagination_offset_calculation(
        self, admin_logs_service, mock_event_repo
    ):
        """Test that list_events calculates correct offset for pagination."""
        mock_event_repo.list_events = AsyncMock(return_value=[])
        mock_event_repo.count_events = AsyncMock(return_value=100)

        await admin_logs_service.list_events(session=None, page=3, per_page=25)

        # Expected offset: (3 - 1) * 25 = 50
        mock_event_repo.list_events.assert_called_once_with(None, None, None, None, 25, 50)

    async def test_get_severity_summary_returns_dict(self, admin_logs_service, mock_event_repo):
        """Test that get_severity_summary returns dict with severity counts."""
        severity_counts = {"error": 5, "warning": 12, "info": 42}
        mock_event_repo.count_by_severity = AsyncMock(return_value=severity_counts)

        result = await admin_logs_service.get_severity_summary(session=None)

        assert isinstance(result, dict)
        assert result == severity_counts
        assert result["error"] == 5
        assert result["warning"] == 12
        assert result["info"] == 42

    async def test_get_severity_summary_with_since_filter(
        self, admin_logs_service, mock_event_repo
    ):
        """Test that get_severity_summary passes since filter to repo."""
        severity_counts = {"error": 2, "warning": 5}
        mock_event_repo.count_by_severity = AsyncMock(return_value=severity_counts)
        since = datetime.now() - timedelta(hours=24)

        result = await admin_logs_service.get_severity_summary(session=None, since=since)

        mock_event_repo.count_by_severity.assert_called_once_with(since=since)
        assert result == severity_counts
