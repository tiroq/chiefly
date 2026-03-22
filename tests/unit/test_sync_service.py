"""
Unit tests for SyncService — task_records + task_snapshots ingestion from Google Tasks.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from apps.api.services.sync_service import SyncService, compute_content_hash, MISSING_THRESHOLD
from core.domain.enums import ProcessingReason, TaskRecordState, WorkflowStatus


def _make_gtask(
    id: str = "gtask-001",
    title: str = "Buy groceries",
    notes: str | None = None,
    status: str = "needsAction",
    tasklist_id: str = "inbox-list",
    updated: str | None = "2024-06-01T09:00:00.000Z",
    raw_payload: dict | None = None,
) -> SimpleNamespace:
    if raw_payload is None:
        raw_payload = {
            "id": id,
            "title": title,
            "status": status,
            "updated": updated,
        }
        if notes:
            raw_payload["notes"] = notes
    return SimpleNamespace(
        id=id,
        title=title,
        notes=notes,
        status=status,
        tasklist_id=tasklist_id,
        updated=updated,
        raw_payload=raw_payload,
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


def _make_task_record(
    stable_id: uuid.UUID | None = None,
    state: str = "active",
    processing_status: str = "pending",
    current_tasklist_id: str = "inbox-list",
    current_task_id: str = "gtask-001",
    consecutive_misses: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        stable_id=stable_id or uuid.uuid4(),
        state=state,
        processing_status=processing_status,
        current_tasklist_id=current_tasklist_id,
        current_task_id=current_task_id,
        consecutive_misses=consecutive_misses,
        last_seen_at=datetime.now(tz=timezone.utc),
    )


def _make_snapshot(
    content_hash: str = "abc123",
    stable_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        stable_id=stable_id,
        content_hash=content_hash,
        is_latest=True,
    )


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


def _setup_mocks():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    google_tasks = MagicMock()

    source_repo = MagicMock()
    source_repo.get_by_google_task_id = AsyncMock(return_value=None)
    source_repo.upsert = AsyncMock()

    record_repo = MagicMock()
    record_repo.get_by_pointer = AsyncMock(return_value=None)
    record_repo.create = AsyncMock()
    record_repo.mark_seen = AsyncMock()
    record_repo.reset_misses = AsyncMock()
    record_repo.update_state = AsyncMock()
    record_repo.update_pointer = AsyncMock()
    record_repo.list_active_and_missing = AsyncMock(return_value=[])
    record_repo.increment_misses = AsyncMock(return_value=1)

    snapshot_repo = MagicMock()
    snapshot_repo.create = AsyncMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)

    queue_repo = MagicMock()
    queue_repo.enqueue_by_stable_id = AsyncMock()

    return mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_new_task_without_envelope(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    source_task = _make_source_task(google_task_id=gtask.id)
    source_repo.upsert.return_value = (source_task, True)

    new_record = _make_task_record(state="unadopted")
    record_repo.create.return_value = new_record

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    record_repo.create.assert_awaited_once()
    create_kwargs = record_repo.create.await_args.kwargs
    assert create_kwargs["state"] == TaskRecordState.UNADOPTED
    assert create_kwargs["processing_status"] == WorkflowStatus.PENDING
    assert create_kwargs["current_tasklist_id"] == "inbox-list"
    assert create_kwargs["current_task_id"] == gtask.id

    snapshot_repo.create.assert_awaited_once()
    queue_repo.enqueue_by_stable_id.assert_awaited_once()
    enqueue_kwargs = queue_repo.enqueue_by_stable_id.await_args.kwargs
    assert enqueue_kwargs["reason"] == ProcessingReason.NEW_TASK
    assert enqueue_kwargs["stable_id"] == new_record.stable_id


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_new_task_with_envelope(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    stable_id = uuid.uuid4()
    notes = f'User notes\n--- chiefly:v1 ---\n{{"stable_id":"{stable_id}","project":"inbox"}}\n--- /chiefly ---'
    gtask = _make_gtask(notes=notes)
    google_tasks.list_tasks.return_value = [gtask]

    source_task = _make_source_task(google_task_id=gtask.id)
    source_repo.upsert.return_value = (source_task, True)

    new_record = _make_task_record(stable_id=stable_id, state="active")
    record_repo.create.return_value = new_record

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    create_kwargs = record_repo.create.await_args.kwargs
    assert create_kwargs["stable_id"] == stable_id
    assert create_kwargs["state"] == TaskRecordState.ACTIVE


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_existing_task_unchanged(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    content_hash = compute_content_hash(gtask.title, gtask.notes)
    existing_record = _make_task_record(state="active")
    record_repo.get_by_pointer.return_value = existing_record

    source_task = _make_source_task(google_task_id=gtask.id, content_hash=content_hash)
    source_repo.get_by_google_task_id.return_value = source_task
    source_repo.upsert.return_value = (source_task, False)

    existing_snapshot = _make_snapshot(
        content_hash=content_hash, stable_id=existing_record.stable_id
    )
    snapshot_repo.get_latest_by_stable_id.return_value = existing_snapshot

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 0
    record_repo.mark_seen.assert_awaited_once_with(existing_record.stable_id)
    record_repo.reset_misses.assert_awaited_once_with(existing_record.stable_id)
    queue_repo.enqueue_by_stable_id.assert_not_awaited()
    record_repo.create.assert_not_awaited()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_existing_task_content_changed(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask(title="Buy groceries updated", notes="Get milk too")
    google_tasks.list_tasks.return_value = [gtask]

    existing_record = _make_task_record(state="active")
    record_repo.get_by_pointer.return_value = existing_record

    source_task = _make_source_task(google_task_id=gtask.id, content_hash="old_hash")
    source_repo.get_by_google_task_id.return_value = source_task
    source_repo.upsert.return_value = (source_task, False)

    old_snapshot = _make_snapshot(content_hash="old_hash", stable_id=existing_record.stable_id)
    snapshot_repo.get_latest_by_stable_id.return_value = old_snapshot

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    snapshot_repo.create.assert_awaited_once()
    queue_repo.enqueue_by_stable_id.assert_awaited_once()
    enqueue_kwargs = queue_repo.enqueue_by_stable_id.await_args.kwargs
    assert enqueue_kwargs["reason"] == ProcessingReason.SOURCE_CHANGED
    assert enqueue_kwargs["stable_id"] == existing_record.stable_id


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_skips_empty_title(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasks.return_value = [
        _make_gtask(title="", id="gtask-empty"),
        _make_gtask(title="Valid task", id="gtask-valid"),
    ]

    source_task = _make_source_task(google_task_id="gtask-valid")
    source_repo.upsert.return_value = (source_task, True)

    new_record = _make_task_record()
    record_repo.create.return_value = new_record

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 1
    source_repo.get_by_google_task_id.assert_awaited_once_with("gtask-valid")


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_empty_list(mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasks.return_value = []

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 0
    mock_session.commit.assert_awaited_once()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_missing_detection_marks_missing(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasks.return_value = []

    missing_record = _make_task_record(state="active", current_task_id="gtask-gone")
    record_repo.list_active_and_missing.return_value = [missing_record]
    record_repo.increment_misses.return_value = 1

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    record_repo.increment_misses.assert_awaited_once_with(missing_record.stable_id)
    record_repo.update_state.assert_awaited_once_with(
        missing_record.stable_id, TaskRecordState.MISSING
    )


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_missing_detection_marks_deleted_after_threshold(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasks.return_value = []

    missing_record = _make_task_record(
        state="missing", current_task_id="gtask-gone", consecutive_misses=2
    )
    record_repo.list_active_and_missing.return_value = [missing_record]
    record_repo.increment_misses.return_value = MISSING_THRESHOLD

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    record_repo.update_state.assert_awaited_once_with(
        missing_record.stable_id, TaskRecordState.DELETED
    )


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_task_reappears_after_missing(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    content_hash = compute_content_hash(gtask.title, gtask.notes)
    existing_record = _make_task_record(state="missing")
    record_repo.get_by_pointer.return_value = existing_record

    source_task = _make_source_task(google_task_id=gtask.id, content_hash=content_hash)
    source_repo.get_by_google_task_id.return_value = source_task
    source_repo.upsert.return_value = (source_task, False)

    existing_snapshot = _make_snapshot(
        content_hash=content_hash, stable_id=existing_record.stable_id
    )
    snapshot_repo.get_latest_by_stable_id.return_value = existing_snapshot

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    record_repo.update_state.assert_awaited_once_with(
        existing_record.stable_id, TaskRecordState.ACTIVE
    )
    record_repo.reset_misses.assert_awaited_once_with(existing_record.stable_id)


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_multiple_tasks_mixed(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    new_gtask = _make_gtask(id="gtask-new", title="New task")
    changed_gtask = _make_gtask(id="gtask-changed", title="Changed task")
    unchanged_gtask = _make_gtask(id="gtask-same", title="Same task")
    google_tasks.list_tasks.return_value = [new_gtask, changed_gtask, unchanged_gtask]

    unchanged_hash = compute_content_hash(unchanged_gtask.title, unchanged_gtask.notes)

    changed_record = _make_task_record(state="active", current_task_id="gtask-changed")
    same_record = _make_task_record(state="active", current_task_id="gtask-same")

    record_repo.get_by_pointer.side_effect = [None, changed_record, same_record]

    new_record = _make_task_record(state="unadopted")
    record_repo.create.return_value = new_record

    source_new = _make_source_task(google_task_id="gtask-new")
    source_changed = _make_source_task(google_task_id="gtask-changed", content_hash="old_hash")
    source_same = _make_source_task(google_task_id="gtask-same", content_hash=unchanged_hash)

    source_repo.get_by_google_task_id.side_effect = [None, source_changed, source_same]
    source_repo.upsert.side_effect = [
        (source_new, True),
        (source_changed, False),
        (source_same, False),
    ]

    old_snapshot = _make_snapshot(content_hash="old_hash", stable_id=changed_record.stable_id)
    same_snapshot = _make_snapshot(content_hash=unchanged_hash, stable_id=same_record.stable_id)
    snapshot_repo.get_latest_by_stable_id.side_effect = [old_snapshot, same_snapshot]

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    result = await svc.sync_inbox("inbox-list")

    assert result == 2
    assert queue_repo.enqueue_by_stable_id.await_count == 2


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_dual_writes_source_tasks(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    source_task = _make_source_task(google_task_id=gtask.id)
    source_repo.upsert.return_value = (source_task, True)

    new_record = _make_task_record()
    record_repo.create.return_value = new_record

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    source_repo.get_by_google_task_id.assert_awaited_once_with(gtask.id)
    source_repo.upsert.assert_awaited_once()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_already_missing_stays_missing_until_threshold(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasks.return_value = []

    missing_record = _make_task_record(
        state="missing", current_task_id="gtask-gone", consecutive_misses=1
    )
    record_repo.list_active_and_missing.return_value = [missing_record]
    record_repo.increment_misses.return_value = 2

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    record_repo.increment_misses.assert_awaited_once_with(missing_record.stable_id)
    record_repo.update_state.assert_not_awaited()


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_task_reappears_after_deleted(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    gtask = _make_gtask()
    google_tasks.list_tasks.return_value = [gtask]

    content_hash = compute_content_hash(gtask.title, gtask.notes)
    deleted_record = _make_task_record(state="deleted", consecutive_misses=5)
    record_repo.get_by_pointer.return_value = deleted_record

    source_task = _make_source_task(google_task_id=gtask.id, content_hash=content_hash)
    source_repo.get_by_google_task_id.return_value = source_task
    source_repo.upsert.return_value = (source_task, False)

    existing_snapshot = _make_snapshot(
        content_hash=content_hash, stable_id=deleted_record.stable_id
    )
    snapshot_repo.get_latest_by_stable_id.return_value = existing_snapshot

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_inbox("inbox-list")

    record_repo.update_state.assert_awaited_once_with(
        deleted_record.stable_id, TaskRecordState.ACTIVE
    )
