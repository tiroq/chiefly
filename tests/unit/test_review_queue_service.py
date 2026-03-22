from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ReviewQueueService = import_module("apps.api.services.review_queue_service").ReviewQueueService


def _make_review_session(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "task_item_id": uuid.uuid4(),
        "telegram_chat_id": "12345",
        "telegram_message_id": 0,
        "status": "queued",
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_task_item(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "raw_text": "Raw task text",
        "normalized_title": "Normalized task title",
        "kind": "task",
        "confidence_band": "medium",
        "next_action": "Do it",
        "due_hint": "tomorrow",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_telegram():
    telegram = MagicMock()
    telegram.send_proposal = AsyncMock(return_value=777)
    telegram.send_text = AsyncMock(return_value=888)
    return telegram


@pytest.fixture
def service(mock_session, mock_telegram):
    return ReviewQueueService(session=mock_session, telegram=mock_telegram)


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_returns_false_when_active_review_exists(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
    mock_telegram,
):
    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=True)
    session_repo.get_next_queued_for_update = AsyncMock()
    mock_session_repo_cls.return_value = session_repo

    result = await service.send_next()

    assert result is False
    session_repo.has_active_review.assert_awaited_once()
    session_repo.get_next_queued_for_update.assert_not_called()
    mock_task_repo_cls.assert_not_called()
    mock_project_repo_cls.assert_not_called()
    mock_telegram.send_proposal.assert_not_called()


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_returns_false_when_queue_is_empty(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
    mock_telegram,
):
    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=None)
    mock_session_repo_cls.return_value = session_repo

    result = await service.send_next()

    assert result is False
    session_repo.get_next_queued_for_update.assert_awaited_once()
    mock_task_repo_cls.assert_not_called()
    mock_project_repo_cls.assert_not_called()
    mock_telegram.send_proposal.assert_not_called()


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_sends_next_queued_item_and_updates_session(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
    mock_session,
    mock_telegram,
):
    queued_session = _make_review_session()
    task_item = _make_task_item(project_id=uuid.uuid4())
    project = SimpleNamespace(name="Personal")

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock(return_value=task_item)
    mock_task_repo_cls.return_value = task_repo

    project_repo = MagicMock()
    project_repo.get_by_id = AsyncMock(return_value=project)
    mock_project_repo_cls.return_value = project_repo

    result = await service.send_next()

    assert result is True
    assert queued_session.status == "pending"
    assert queued_session.telegram_message_id == 777
    session_repo.save.assert_awaited_once_with(queued_session)
    mock_session.commit.assert_awaited_once()
    mock_telegram.send_proposal.assert_awaited_once()
    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["task_id"] == str(task_item.id)
    assert sent_kwargs["raw_text"] == task_item.raw_text
    assert sent_kwargs["project_name"] == "Personal"


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_marks_missing_task_resolved_then_recurses(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
    mock_session,
    mock_telegram,
):
    missing_session = _make_review_session(task_item_id=uuid.uuid4())
    valid_session = _make_review_session(task_item_id=uuid.uuid4())
    valid_task = _make_task_item(id=valid_session.task_item_id, project_id=None)

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(side_effect=[False, False])
    session_repo.get_next_queued_for_update = AsyncMock(
        side_effect=[missing_session, valid_session]
    )
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock(side_effect=[None, valid_task])
    mock_task_repo_cls.return_value = task_repo

    project_repo = MagicMock()
    project_repo.get_by_id = AsyncMock(return_value=None)
    mock_project_repo_cls.return_value = project_repo

    result = await service.send_next()

    assert result is True
    assert missing_session.status == "resolved"
    assert valid_session.status == "pending"
    assert valid_session.telegram_message_id == 777
    assert session_repo.save.await_count == 2
    assert mock_session.commit.await_count == 2
    mock_telegram.send_proposal.assert_awaited_once()


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_sends_remaining_queue_notification(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
    mock_telegram,
):
    queued_session = _make_review_session()
    task_item = _make_task_item(project_id=None)

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=3)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock(return_value=task_item)
    mock_task_repo_cls.return_value = task_repo

    project_repo = MagicMock()
    project_repo.get_by_id = AsyncMock(return_value=None)
    mock_project_repo_cls.return_value = project_repo

    result = await service.send_next()

    assert result is True
    mock_telegram.send_text.assert_awaited_once_with(
        "📬 3 more item(s) in queue. Use /next after reviewing."
    )


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_returns_structure_with_items(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
):
    qs1 = _make_review_session(task_item_id=uuid.uuid4())
    qs2 = _make_review_session(task_item_id=uuid.uuid4())
    task1 = _make_task_item(id=qs1.task_item_id, normalized_title="First", raw_text="First raw")
    task2 = _make_task_item(id=qs2.task_item_id, normalized_title=None, raw_text="Second raw")

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[qs1, qs2])
    session_repo.has_active_review = AsyncMock(return_value=True)
    session_repo.count_queued = AsyncMock(return_value=2)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock(side_effect=[task1, task2])
    mock_task_repo_cls.return_value = task_repo

    result = await service.get_queue_status()

    assert result == {
        "has_active": True,
        "total_queued": 2,
        "items": ["First", "Second raw"],
    }
    session_repo.list_queued.assert_awaited_once_with(limit=10)
    mock_project_repo_cls.assert_not_called()


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_when_queue_is_empty(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
):
    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock()
    mock_task_repo_cls.return_value = task_repo

    result = await service.get_queue_status()

    assert result == {"has_active": False, "total_queued": 0, "items": []}
    task_repo.get_by_id.assert_not_called()
    mock_project_repo_cls.assert_not_called()


@patch("apps.api.services.review_queue_service.ProjectRepository")
@patch("apps.api.services.review_queue_service.TaskItemRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_preserves_fifo_queue_ordering_by_created_at(
    mock_session_repo_cls,
    mock_task_repo_cls,
    mock_project_repo_cls,
    service,
):
    now = datetime.now(timezone.utc)
    older_session = _make_review_session(created_at=now - timedelta(minutes=2))
    newer_session = _make_review_session(created_at=now - timedelta(minutes=1))
    older_task = _make_task_item(id=older_session.task_item_id, normalized_title="Older item")
    newer_task = _make_task_item(id=newer_session.task_item_id, normalized_title="Newer item")

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[older_session, newer_session])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=2)
    mock_session_repo_cls.return_value = session_repo

    task_repo = MagicMock()
    task_repo.get_by_id = AsyncMock(side_effect=[older_task, newer_task])
    mock_task_repo_cls.return_value = task_repo

    result = await service.get_queue_status()

    assert result["items"] == ["Older item", "Newer item"]
    mock_project_repo_cls.assert_not_called()
