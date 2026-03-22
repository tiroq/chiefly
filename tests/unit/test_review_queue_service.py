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
        "stable_id": uuid.uuid4(),
        "telegram_chat_id": "12345",
        "telegram_message_id": 0,
        "status": "queued",
        "proposed_changes": {
            "normalized_title": "Buy groceries",
            "kind": "task",
            "confidence": "high",
            "next_action": "Go to store",
            "due_hint": "tomorrow",
            "project_name": "Personal",
            "project_id": str(uuid.uuid4()),
        },
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_snapshot(**overrides):
    defaults = {
        "id": 1,
        "stable_id": uuid.uuid4(),
        "payload": {"title": "Raw task text from Google"},
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


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_returns_false_when_active_review_exists(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
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
    mock_snapshot_repo_cls.assert_not_called()
    mock_telegram.send_proposal.assert_not_called()


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_returns_false_when_queue_is_empty(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
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
    mock_snapshot_repo_cls.assert_not_called()
    mock_telegram.send_proposal.assert_not_called()


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_reads_proposed_changes_and_sends_proposal(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_session,
    mock_telegram,
):
    """send_next reads classification data from proposed_changes JSON, not TaskItem."""
    stable_id = uuid.uuid4()
    queued_session = _make_review_session(
        stable_id=stable_id,
        proposed_changes={
            "normalized_title": "Buy groceries",
            "kind": "task",
            "confidence": "high",
            "next_action": "Go to store",
            "due_hint": "tomorrow",
            "project_name": "Personal",
            "project_id": str(uuid.uuid4()),
        },
    )
    snapshot = _make_snapshot(stable_id=stable_id, payload={"title": "buy groceries raw"})

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=snapshot)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    result = await service.send_next()

    assert result is True
    assert queued_session.status == "pending"
    assert queued_session.telegram_message_id == 777
    session_repo.save.assert_awaited_once_with(queued_session)
    mock_session.commit.assert_awaited_once()

    mock_telegram.send_proposal.assert_awaited_once()
    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["task_id"] == str(stable_id)
    assert sent_kwargs["raw_text"] == "buy groceries raw"
    assert sent_kwargs["project_name"] == "Personal"
    cls = sent_kwargs["classification"]
    assert cls.normalized_title == "Buy groceries"
    assert cls.kind.value == "task"
    assert cls.confidence.value == "high"
    assert cls.next_action == "Go to store"
    assert cls.due_hint == "tomorrow"


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_uses_stable_id_in_callback(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_telegram,
):
    """Telegram callback buttons encode stable_id only."""
    stable_id = uuid.uuid4()
    queued_session = _make_review_session(
        stable_id=stable_id,
    )

    snapshot = _make_snapshot(stable_id=stable_id)

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=snapshot)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    await service.send_next()

    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["task_id"] == str(stable_id)


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_skips_session_with_empty_proposed_changes(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_session,
    mock_telegram,
):
    """Sessions with no proposed_changes are marked resolved and skipped."""
    empty_session = _make_review_session(proposed_changes={})
    valid_session = _make_review_session(
        proposed_changes={
            "normalized_title": "Valid task",
            "kind": "task",
            "confidence": "medium",
            "project_name": "Work",
        },
    )

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(side_effect=[False, False])
    session_repo.get_next_queued_for_update = AsyncMock(side_effect=[empty_session, valid_session])
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    result = await service.send_next()

    assert result is True
    assert empty_session.status == "resolved"
    assert valid_session.status == "pending"
    assert session_repo.save.await_count == 2
    assert mock_session.commit.await_count == 2
    mock_telegram.send_proposal.assert_awaited_once()


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_falls_back_to_normalized_title_when_no_snapshot(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_telegram,
):
    """When snapshot is not available, raw_text falls back to normalized_title from proposed_changes."""
    queued_session = _make_review_session(
        stable_id=uuid.uuid4(),
        proposed_changes={
            "normalized_title": "Fallback title",
            "kind": "task",
            "confidence": "medium",
        },
    )

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    await service.send_next()

    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["raw_text"] == "Fallback title"


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_sends_remaining_queue_notification(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_telegram,
):
    queued_session = _make_review_session()

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=3)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(
        return_value=_make_snapshot(stable_id=queued_session.stable_id)
    )
    mock_snapshot_repo_cls.return_value = snapshot_repo

    result = await service.send_next()

    assert result is True
    mock_telegram.send_text.assert_awaited_once_with(
        "📬 3 more item(s) in queue. Use /next after reviewing."
    )


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_handles_invalid_kind_gracefully(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_telegram,
):
    """Invalid kind in proposed_changes defaults to TASK."""
    queued_session = _make_review_session(
        proposed_changes={
            "normalized_title": "Test",
            "kind": "invalid_kind_value",
            "confidence": "medium",
        },
    )

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    await service.send_next()

    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["classification"].kind.value == "task"


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_handles_invalid_confidence_gracefully(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
    mock_telegram,
):
    """Invalid confidence in proposed_changes defaults to MEDIUM."""
    queued_session = _make_review_session(
        proposed_changes={
            "normalized_title": "Test",
            "kind": "task",
            "confidence": "bogus",
        },
    )

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued_session)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    await service.send_next()

    sent_kwargs = mock_telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["classification"].confidence.value == "medium"


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_reads_titles_from_proposed_changes(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
):
    """get_queue_status reads normalized_title from proposed_changes, not TaskItem."""
    qs1 = _make_review_session(
        proposed_changes={"normalized_title": "First task"},
    )
    qs2 = _make_review_session(
        proposed_changes={"normalized_title": "Second task"},
    )

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[qs1, qs2])
    session_repo.has_active_review = AsyncMock(return_value=True)
    session_repo.count_queued = AsyncMock(return_value=2)
    mock_session_repo_cls.return_value = session_repo

    result = await service.get_queue_status()

    assert result == {
        "has_active": True,
        "total_queued": 2,
        "items": ["First task", "Second task"],
    }
    session_repo.list_queued.assert_awaited_once_with(limit=10)


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_falls_back_to_snapshot_title(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
):
    """When proposed_changes has no title, falls back to snapshot payload title."""
    stable_id = uuid.uuid4()
    qs = _make_review_session(
        stable_id=stable_id,
        proposed_changes={},
    )

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[qs])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=1)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(
        return_value=_make_snapshot(stable_id=stable_id, payload={"title": "Snapshot fallback"})
    )
    mock_snapshot_repo_cls.return_value = snapshot_repo

    result = await service.get_queue_status()

    assert result["items"] == ["Snapshot fallback"]
    snapshot_repo.get_latest_by_stable_id.assert_awaited_once_with(stable_id)


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_when_queue_is_empty(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
):
    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    result = await service.get_queue_status()

    assert result == {"has_active": False, "total_queued": 0, "items": []}
    mock_snapshot_repo_cls.assert_not_called()


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_preserves_fifo_ordering(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
):
    now = datetime.now(timezone.utc)
    older = _make_review_session(
        created_at=now - timedelta(minutes=2),
        proposed_changes={"normalized_title": "Older item"},
    )
    newer = _make_review_session(
        created_at=now - timedelta(minutes=1),
        proposed_changes={"normalized_title": "Newer item"},
    )

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[older, newer])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=2)
    mock_session_repo_cls.return_value = session_repo

    result = await service.get_queue_status()

    assert result["items"] == ["Older item", "Newer item"]
    mock_snapshot_repo_cls.assert_not_called()


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_get_queue_status_skips_items_with_no_title_anywhere(
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
    service,
):
    """Items with no title in proposed_changes AND no snapshot are excluded from items list."""
    qs_with_title = _make_review_session(
        proposed_changes={"normalized_title": "Has title"},
    )
    qs_no_title = _make_review_session(
        stable_id=uuid.uuid4(),
        proposed_changes={},
    )

    session_repo = MagicMock()
    session_repo.list_queued = AsyncMock(return_value=[qs_with_title, qs_no_title])
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.count_queued = AsyncMock(return_value=2)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    result = await service.get_queue_status()

    assert result["items"] == ["Has title"]
    assert result["total_queued"] == 2
