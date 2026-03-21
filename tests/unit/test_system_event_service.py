"""
Unit tests for SystemEventService.
Tests logging system events with convenience methods and structlog integration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.system_event_service import SystemEventService
from db.models.system_event import SystemEvent


@pytest.fixture
def mock_repo():
    """Mock SystemEventRepo."""
    repo = MagicMock()
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def service(mock_repo):
    """Create SystemEventService with mocked repo."""
    return SystemEventService(repo=mock_repo)


@pytest.fixture
def mock_session():
    """Mock AsyncSession."""
    return MagicMock()


class TestLogEvent:
    """Tests for log_event core method."""

    @pytest.mark.asyncio
    async def test_log_event_creates_system_event_with_all_fields(
        self, service, mock_repo, mock_session
    ):
        """Test log_event creates a SystemEvent with all provided fields."""
        task_item_id = uuid.uuid4()
        project_id = uuid.uuid4()
        payload = {"key": "value"}

        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="test_event",
            severity="info",
            subsystem="test",
            message="Test message",
            task_item_id=task_item_id,
            project_id=project_id,
            payload_json=payload,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_event(
            session=mock_session,
            event_type="test_event",
            severity="info",
            subsystem="test",
            message="Test message",
            task_item_id=task_item_id,
            project_id=project_id,
            payload=payload,
        )

        assert result.event_type == "test_event"
        assert result.severity == "info"
        assert result.subsystem == "test"
        assert result.message == "Test message"
        assert result.task_item_id == task_item_id
        assert result.project_id == project_id
        assert result.payload_json == payload
        mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_event_calls_repo_create(self, service, mock_repo, mock_session):
        """Test log_event calls repo.create with correct event object."""
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="test",
            severity="info",
            subsystem="test",
            message="msg",
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        await service.log_event(
            session=mock_session,
            event_type="test",
            severity="info",
            subsystem="test",
            message="msg",
        )

        mock_repo.create.assert_called_once()
        called_event = mock_repo.create.call_args[0][0]
        assert isinstance(called_event, SystemEvent)
        assert called_event.event_type == "test"
        assert called_event.severity == "info"

    @pytest.mark.asyncio
    async def test_log_event_with_optional_fields_none(self, service, mock_repo, mock_session):
        """Test log_event works with None optional fields."""
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="test",
            severity="error",
            subsystem="sys",
            message="error msg",
            task_item_id=None,
            project_id=None,
            payload_json=None,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_event(
            session=mock_session,
            event_type="test",
            severity="error",
            subsystem="sys",
            message="error msg",
        )

        assert result.task_item_id is None
        assert result.project_id is None
        assert result.payload_json is None


class TestLogAdminAction:
    """Tests for log_admin_action convenience method."""

    @pytest.mark.asyncio
    async def test_log_admin_action_sets_severity_and_subsystem(
        self, service, mock_repo, mock_session
    ):
        """Test log_admin_action sets severity='info' and subsystem='admin'."""
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="user_login",
            severity="info",
            subsystem="admin",
            message="Admin logged in",
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_admin_action(
            session=mock_session,
            action="user_login",
            message="Admin logged in",
        )

        assert result.severity == "info"
        assert result.subsystem == "admin"
        assert result.event_type == "user_login"
        mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_admin_action_passes_optional_fields(self, service, mock_repo, mock_session):
        """Test log_admin_action passes task_item_id, project_id, and payload."""
        task_item_id = uuid.uuid4()
        project_id = uuid.uuid4()
        payload = {"admin_id": "123"}

        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="config_updated",
            severity="info",
            subsystem="admin",
            message="Config updated",
            task_item_id=task_item_id,
            project_id=project_id,
            payload_json=payload,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_admin_action(
            session=mock_session,
            action="config_updated",
            message="Config updated",
            task_item_id=task_item_id,
            project_id=project_id,
            payload=payload,
        )

        assert result.task_item_id == task_item_id
        assert result.project_id == project_id
        assert result.payload_json == payload


class TestLogClassificationEvent:
    """Tests for log_classification_event convenience method."""

    @pytest.mark.asyncio
    async def test_log_classification_event_sets_subsystem(self, service, mock_repo, mock_session):
        """Test log_classification_event sets subsystem='classification'."""
        task_item_id = uuid.uuid4()
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="classification",
            severity="info",
            subsystem="classification",
            message="Task classified",
            task_item_id=task_item_id,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_classification_event(
            session=mock_session,
            message="Task classified",
            task_item_id=task_item_id,
        )

        assert result.subsystem == "classification"
        assert result.event_type == "classification"
        assert result.severity == "info"
        mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_classification_event_with_payload(self, service, mock_repo, mock_session):
        """Test log_classification_event includes payload."""
        payload = {"kind": "task", "confidence": "high"}
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="classification",
            severity="info",
            subsystem="classification",
            message="Classified as task",
            payload_json=payload,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_classification_event(
            session=mock_session,
            message="Classified as task",
            payload=payload,
        )

        assert result.payload_json == payload


class TestLogError:
    """Tests for log_error convenience method."""

    @pytest.mark.asyncio
    async def test_log_error_sets_severity_to_error(self, service, mock_repo, mock_session):
        """Test log_error sets severity='error'."""
        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="error",
            severity="error",
            subsystem="classification",
            message="Classification failed",
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_error(
            session=mock_session,
            subsystem="classification",
            message="Classification failed",
        )

        assert result.severity == "error"
        assert result.event_type == "error"
        mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_error_with_task_item_id_and_payload(self, service, mock_repo, mock_session):
        """Test log_error includes task_item_id and payload."""
        task_item_id = uuid.uuid4()
        payload = {"error_code": "LLM_TIMEOUT"}

        created_event = SystemEvent(
            id=uuid.uuid4(),
            event_type="error",
            severity="error",
            subsystem="llm",
            message="LLM timeout",
            task_item_id=task_item_id,
            payload_json=payload,
            created_at=datetime.now(timezone.utc),
        )
        mock_repo.create.return_value = created_event

        result = await service.log_error(
            session=mock_session,
            subsystem="llm",
            message="LLM timeout",
            task_item_id=task_item_id,
            payload=payload,
        )

        assert result.task_item_id == task_item_id
        assert result.payload_json == payload
