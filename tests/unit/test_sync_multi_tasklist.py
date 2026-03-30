"""
Tests for multi-tasklist sync: sync_all(), moved detection, SyncCycleSummary,
and verification that sync does NOT trigger LLM or send Telegram proposals.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from apps.api.services.sync_service import (
    SyncService,
    SyncCycleSummary,
    TaskListSyncResult,
    compute_content_hash,
    MISSING_THRESHOLD,
)
from core.domain.enums import ProcessingReason, TaskRecordState, WorkflowStatus


def _make_gtask(
    id: str = "gtask-001",
    title: str = "Buy groceries",
    notes: str | None = None,
    status: str = "needsAction",
    tasklist_id: str = "list-A",
    updated: str | None = "2024-06-01T09:00:00.000Z",
    raw_payload: dict | None = None,
) -> SimpleNamespace:
    if raw_payload is None:
        raw_payload = {"id": id, "title": title, "status": status, "updated": updated}
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
    google_task_id: str = "gtask-001", content_hash: str = "abc123", **overrides
) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "google_task_id": google_task_id,
        "google_tasklist_id": "list-A",
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
    current_tasklist_id: str = "list-A",
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
    content_hash: str = "abc123", stable_id: uuid.UUID | None = None
) -> SimpleNamespace:
    return SimpleNamespace(id=1, stable_id=stable_id, content_hash=content_hash, is_latest=True)


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


# ---------- sync_all() tests ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_all_processes_multiple_tasklists(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [
        {"id": "list-A", "title": "Inbox"},
        {"id": "list-B", "title": "Work"},
        {"id": "list-C", "title": "Personal"},
    ]

    gtask_a = _make_gtask(id="gt-a1", title="Task A1", tasklist_id="list-A")
    gtask_b = _make_gtask(id="gt-b1", title="Task B1", tasklist_id="list-B")
    gtask_c = _make_gtask(id="gt-c1", title="Task C1", tasklist_id="list-C")

    google_tasks.list_tasks.side_effect = [[gtask_a], [gtask_b], [gtask_c]]

    source_a = _make_source_task(google_task_id="gt-a1")
    source_b = _make_source_task(google_task_id="gt-b1")
    source_c = _make_source_task(google_task_id="gt-c1")
    source_repo.upsert.side_effect = [(source_a, True), (source_b, True), (source_c, True)]

    rec_a = _make_task_record(current_tasklist_id="list-A", current_task_id="gt-a1")
    rec_b = _make_task_record(current_tasklist_id="list-B", current_task_id="gt-b1")
    rec_c = _make_task_record(current_tasklist_id="list-C", current_task_id="gt-c1")
    record_repo.create.side_effect = [rec_a, rec_b, rec_c]

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert summary.tasklists_scanned == 3
    assert summary.tasks_scanned == 3
    assert summary.new_count == 3
    assert summary.queued_count == 3
    assert len(summary.tasklist_results) == 3
    assert google_tasks.list_tasks.call_count == 3
    google_tasks.list_tasks.assert_any_call("list-A")
    google_tasks.list_tasks.assert_any_call("list-B")
    google_tasks.list_tasks.assert_any_call("list-C")


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_all_returns_correct_summary_structure(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [
        {"id": "list-X", "title": "My Tasks"},
    ]
    google_tasks.list_tasks.return_value = []

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert isinstance(summary, SyncCycleSummary)
    assert summary.tasklists_scanned == 1
    assert summary.tasks_scanned == 0
    assert summary.new_count == 0
    assert summary.updated_count == 0
    assert summary.moved_count == 0
    assert summary.deleted_count == 0
    assert summary.queued_count == 0
    assert len(summary.tasklist_results) == 1
    assert summary.tasklist_results[0].tasklist_id == "list-X"
    assert summary.tasklist_results[0].tasklist_title == "My Tasks"


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_all_snapshots_store_correct_tasklist_id(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [
        {"id": "list-work", "title": "Work"},
        {"id": "list-personal", "title": "Personal"},
    ]

    gtask_w = _make_gtask(id="gt-w1", title="Work task", tasklist_id="list-work")
    gtask_p = _make_gtask(id="gt-p1", title="Personal task", tasklist_id="list-personal")
    google_tasks.list_tasks.side_effect = [[gtask_w], [gtask_p]]

    source_w = _make_source_task(google_task_id="gt-w1")
    source_p = _make_source_task(google_task_id="gt-p1")
    source_repo.upsert.side_effect = [(source_w, True), (source_p, True)]

    rec_w = _make_task_record(current_tasklist_id="list-work", current_task_id="gt-w1")
    rec_p = _make_task_record(current_tasklist_id="list-personal", current_task_id="gt-p1")
    record_repo.create.side_effect = [rec_w, rec_p]

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_all()

    snapshot_calls = snapshot_repo.create.await_args_list
    assert len(snapshot_calls) == 2
    assert snapshot_calls[0].kwargs["tasklist_id"] == "list-work"
    assert snapshot_calls[1].kwargs["tasklist_id"] == "list-personal"


# ---------- Moved task detection ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_detects_moved_task(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [
        {"id": "list-new", "title": "New List"},
    ]

    gtask = _make_gtask(id="gt-moved", title="Moved task", tasklist_id="list-new")
    google_tasks.list_tasks.return_value = [gtask]

    source_task = _make_source_task(google_task_id="gt-moved")
    source_repo.upsert.return_value = (source_task, True)

    # Not found by pointer on new list
    record_repo.get_by_pointer.return_value = None

    # Found via move detection: same task_id on different list
    moved_record = _make_task_record(
        current_tasklist_id="list-old",
        current_task_id="gt-moved",
        state="active",
    )
    record_repo.list_active_and_missing.return_value = [moved_record]

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert summary.moved_count == 1
    assert summary.new_count == 0

    record_repo.update_pointer.assert_awaited()
    pointer_kwargs = record_repo.update_pointer.await_args_list[0]
    assert pointer_kwargs[0][0] == moved_record.stable_id
    assert pointer_kwargs[0][1] == "list-new"

    enqueue_kwargs = queue_repo.enqueue_by_stable_id.await_args.kwargs
    assert enqueue_kwargs["reason"] == ProcessingReason.TASK_MOVED


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_does_not_detect_move_for_same_tasklist(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [{"id": "list-A", "title": "A"}]
    gtask = _make_gtask(id="gt-x", title="Task X", tasklist_id="list-A")
    google_tasks.list_tasks.return_value = [gtask]

    source_task = _make_source_task(google_task_id="gt-x")
    source_repo.upsert.return_value = (source_task, True)

    record_repo.get_by_pointer.return_value = None

    # Record exists on same list — not a move, won't match
    existing_record = _make_task_record(
        current_tasklist_id="list-A", current_task_id="gt-x", state="active"
    )
    record_repo.list_active_and_missing.return_value = [existing_record]

    new_record = _make_task_record()
    record_repo.create.return_value = new_record

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert summary.moved_count == 0
    assert summary.new_count == 1


# ---------- Sync does NOT trigger LLM ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_does_not_call_llm(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [{"id": "list-A", "title": "A"}]
    google_tasks.list_tasks.return_value = [_make_gtask()]

    source_task = _make_source_task()
    source_repo.upsert.return_value = (source_task, True)
    record_repo.create.return_value = _make_task_record()

    svc = SyncService(session=mock_session, google_tasks=google_tasks)

    with patch("apps.api.services.sync_service.notes_codec") as mock_codec:
        mock_codec.parse.return_value = None
        await svc.sync_all()

    # SyncService has no LLM dependency — it shouldn't import or call anything LLM-related
    assert not hasattr(svc, "_llm")
    assert not hasattr(svc, "_classification")


# ---------- Sync does NOT send Telegram proposal cards ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_does_not_send_telegram_proposals(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [{"id": "list-A", "title": "A"}]
    google_tasks.list_tasks.return_value = [_make_gtask()]

    source_task = _make_source_task()
    source_repo.upsert.return_value = (source_task, True)
    record_repo.create.return_value = _make_task_record()

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    await svc.sync_all()

    # SyncService must not have any Telegram dependency
    assert not hasattr(svc, "_telegram")
    assert not hasattr(svc, "_review_queue")


# ---------- Duplicate sync idempotency ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_duplicate_sync_does_not_create_duplicate_work(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [{"id": "list-A", "title": "A"}]
    gtask = _make_gtask(id="gt-dup", title="Duplicate check")
    google_tasks.list_tasks.return_value = [gtask]

    content_hash = compute_content_hash(gtask.title, gtask.notes)
    existing_record = _make_task_record(
        state="active", current_tasklist_id="list-A", current_task_id="gt-dup"
    )
    record_repo.get_by_pointer.return_value = existing_record

    source_task = _make_source_task(google_task_id="gt-dup", content_hash=content_hash)
    source_repo.get_by_google_task_id.return_value = source_task
    source_repo.upsert.return_value = (source_task, False)

    existing_snapshot = _make_snapshot(
        content_hash=content_hash, stable_id=existing_record.stable_id
    )
    snapshot_repo.get_latest_by_stable_id.return_value = existing_snapshot

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert summary.new_count == 0
    assert summary.updated_count == 0
    assert summary.moved_count == 0
    queue_repo.enqueue_by_stable_id.assert_not_awaited()
    record_repo.create.assert_not_awaited()


# ---------- SyncCycleSummary dataclass ----------


class TestSyncCycleSummary:
    def test_add_tasklist_result(self):
        summary = SyncCycleSummary()
        r1 = TaskListSyncResult(
            tasklist_id="a",
            tasklist_title="A",
            tasks_seen=10,
            new_count=2,
            updated_count=1,
            moved_count=0,
        )
        r2 = TaskListSyncResult(
            tasklist_id="b",
            tasklist_title="B",
            tasks_seen=5,
            new_count=0,
            updated_count=0,
            moved_count=1,
        )
        summary.add_tasklist_result(r1)
        summary.add_tasklist_result(r2)

        assert summary.tasklists_scanned == 2
        assert summary.tasks_scanned == 15
        assert summary.new_count == 2
        assert summary.updated_count == 1
        assert summary.moved_count == 1
        assert len(summary.tasklist_results) == 2

    def test_total_synced_property(self):
        summary = SyncCycleSummary(new_count=3, updated_count=2, moved_count=1)
        assert summary.total_synced == 6

    def test_empty_summary(self):
        summary = SyncCycleSummary()
        assert summary.total_synced == 0
        assert summary.tasklists_scanned == 0
        assert summary.queued_count == 0


# ---------- Deleted detection across all lists ----------


@patch("apps.api.services.sync_service.ProcessingQueueRepository")
@patch("apps.api.services.sync_service.TaskSnapshotRepository")
@patch("apps.api.services.sync_service.TaskRecordRepository")
@patch("apps.api.services.sync_service.SourceTaskRepository")
@pytest.mark.asyncio
async def test_sync_all_deleted_detection_across_all_lists(
    mock_source_cls, mock_record_cls, mock_snapshot_cls, mock_queue_cls
):
    mock_session, google_tasks, source_repo, record_repo, snapshot_repo, queue_repo = _setup_mocks()
    mock_source_cls.return_value = source_repo
    mock_record_cls.return_value = record_repo
    mock_snapshot_cls.return_value = snapshot_repo
    mock_queue_cls.return_value = queue_repo

    google_tasks.list_tasklists.return_value = [
        {"id": "list-A", "title": "A"},
        {"id": "list-B", "title": "B"},
    ]
    google_tasks.list_tasks.side_effect = [[], []]

    gone_record = _make_task_record(
        state="missing", current_task_id="gt-gone", consecutive_misses=2
    )
    record_repo.list_active_and_missing.return_value = [gone_record]
    record_repo.increment_misses.return_value = MISSING_THRESHOLD

    svc = SyncService(session=mock_session, google_tasks=google_tasks)
    summary = await svc.sync_all()

    assert summary.deleted_count == 1
    record_repo.update_state.assert_awaited_once_with(
        gone_record.stable_id, TaskRecordState.DELETED
    )
