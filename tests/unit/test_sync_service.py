"""
Unit tests for SyncService — source task ingestion from Google Tasks.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.sync_service import SyncService, compute_content_hash
from core.domain.enums import ProcessingReason


def _make_gtask(
    id: str = "gtask-001",
    title: str = "Buy groceries",
    notes: str | None = None,
    status: str = "needsAction",
    tasklist_id: str = "inbox-list",
    updated: str | None = "2024-06-01T09:00:00.000Z",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title,
        notes=notes,
        status=status,
        tasklist_id=tasklist_id,
        updated=updated,
    )


def _make_source_task(
    google_task_id: str = "gtask-001",
    content_hash: str = "abc123",
    **overrides,
) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "google_task_id": google_task_id,
        "google_tasklist_id": "inbox-list",
        "title_raw": "Buy groceries",
        "notes_raw": None,
        "google_status": "needsAction",
        "google_updated_at": None,
        "content_hash": content_hash,
        "is_deleted": False,
        "synced_at": datetime.now(tz=timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestComputeContentHash:
    def test_title_only(self):
        h = compute_content_hash("Buy groceries", None)
        expected = hashlib.sha256("buy groceries".encode("utf-8")).hexdigest()
        assert h == expected

    def test_title_and_notes(self):
        h = compute_content_hash("Buy groceries", "From Costco")
        expected = hashlib.sha256("buy groceries\nfrom costco".encode("utf-8")).hexdigest()
        assert h == expected

    def test_strips_whitespace(self):
        h1 = compute_content_hash("  Buy groceries  ", "  From Costco  ")
        h2 = compute_content_hash("Buy groceries", "From Costco")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = compute_content_hash("BUY GROCERIES", "FROM COSTCO")
        h2 = compute_content_hash("buy groceries", "from costco")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_content_hash("Buy groceries", None)
        h2 = compute_content_hash("Call dentist", None)
        assert h1 != h2

    def test_hash_is_64_chars_hex(self):
        h = compute_content_hash("test", None)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_new_task(mock_source_repo_cls, mock_queue_repo_cls):
    """New task from Google is inserted into source_tasks and enqueued for processing."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    google_tasks = MagicMock()
    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(return_value=None)

    new_source_task = _make_source_task(
        google_task_id=gtask.id,
        content_hash=compute_content_hash(gtask.title, gtask.notes),
    )
    source_repo.upsert = AsyncMock(return_value=(new_source_task, True))
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    queue_repo.enqueue = AsyncMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    source_repo.get_by_google_task_id.assert_awaited_once_with(gtask.id)
    source_repo.upsert.assert_awaited_once()
    queue_repo.enqueue.assert_awaited_once()
    enqueue_kwargs = queue_repo.enqueue.await_args.kwargs
    assert enqueue_kwargs["source_task_id"] == new_source_task.id
    assert enqueue_kwargs["reason"] == ProcessingReason.NEW_TASK
    mock_session.commit.assert_awaited_once()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_changed_task(mock_source_repo_cls, mock_queue_repo_cls):
    """Existing task with different content_hash is updated and re-enqueued."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    google_tasks = MagicMock()
    gtask = _make_gtask(title="Buy groceries updated", notes="Get milk too")
    google_tasks.list_tasks.return_value = [gtask]

    existing = _make_source_task(
        google_task_id=gtask.id,
        content_hash="old_hash_that_does_not_match",
    )

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(return_value=existing)
    source_repo.upsert = AsyncMock(return_value=(existing, False))
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    queue_repo.enqueue = AsyncMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    source_repo.upsert.assert_awaited_once()
    queue_repo.enqueue.assert_awaited_once()
    enqueue_kwargs = queue_repo.enqueue.await_args.kwargs
    assert enqueue_kwargs["source_task_id"] == existing.id
    assert enqueue_kwargs["reason"] == ProcessingReason.SOURCE_CHANGED


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_unchanged_task_not_enqueued(mock_source_repo_cls, mock_queue_repo_cls):
    """Task with same content_hash is not re-enqueued."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    google_tasks = MagicMock()
    gtask = _make_gtask(title="Buy groceries")
    google_tasks.list_tasks.return_value = [gtask]

    matching_hash = compute_content_hash(gtask.title, gtask.notes)
    existing = _make_source_task(
        google_task_id=gtask.id,
        content_hash=matching_hash,
    )

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(return_value=existing)
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    queue_repo.enqueue = AsyncMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 0
    source_repo.upsert.assert_not_called()
    queue_repo.enqueue.assert_not_called()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_skips_empty_title(mock_source_repo_cls, mock_queue_repo_cls):
    """Tasks with no title are skipped entirely."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    google_tasks = MagicMock()
    google_tasks.list_tasks.return_value = [
        _make_gtask(title="", id="gtask-empty"),
        _make_gtask(title="Valid task", id="gtask-valid"),
    ]

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(return_value=None)
    new_task = _make_source_task(google_task_id="gtask-valid")
    source_repo.upsert = AsyncMock(return_value=(new_task, True))
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    queue_repo.enqueue = AsyncMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    source_repo.get_by_google_task_id.assert_awaited_once_with("gtask-valid")


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_empty_list(mock_source_repo_cls, mock_queue_repo_cls):
    """Empty Google Tasks list results in 0 synced."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()

    google_tasks = MagicMock()
    google_tasks.list_tasks.return_value = []

    source_repo = MagicMock()
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 0
    mock_session.commit.assert_awaited_once()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_inbox_multiple_tasks_mixed(mock_source_repo_cls, mock_queue_repo_cls):
    """Multiple tasks: one new, one changed, one unchanged."""
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    new_gtask = _make_gtask(id="gtask-new", title="New task")
    changed_gtask = _make_gtask(id="gtask-changed", title="Changed task")
    unchanged_gtask = _make_gtask(id="gtask-same", title="Same task")

    google_tasks = MagicMock()
    google_tasks.list_tasks.return_value = [new_gtask, changed_gtask, unchanged_gtask]

    unchanged_hash = compute_content_hash(unchanged_gtask.title, unchanged_gtask.notes)
    existing_changed = _make_source_task(google_task_id="gtask-changed", content_hash="old_hash")
    existing_same = _make_source_task(google_task_id="gtask-same", content_hash=unchanged_hash)

    new_source = _make_source_task(google_task_id="gtask-new")

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(
        side_effect=[None, existing_changed, existing_same]
    )
    source_repo.upsert = AsyncMock(side_effect=[(new_source, True), (existing_changed, False)])
    mock_source_repo_cls.return_value = source_repo

    queue_repo = MagicMock()
    queue_repo.enqueue = AsyncMock()
    mock_queue_repo_cls.return_value = queue_repo

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 2
    assert queue_repo.enqueue.await_count == 2
