"""Unit tests for run_processing() worker."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.enums import ProcessingReason, ProcessingStatus, TaskStatus


def _make_source_task(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "google_task_id": "gtask-001",
        "google_tasklist_id": "inbox-list",
        "title_raw": "Buy groceries",
        "notes_raw": None,
        "google_status": "needsAction",
        "google_updated_at": None,
        "content_hash": "abc123def456",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_queue_entry(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "source_task_id": uuid.uuid4(),
        "task_item_id": None,
        "processing_status": ProcessingStatus.LOCKED,
        "processing_reason": ProcessingReason.NEW_TASK,
        "content_hash_at_processing": None,
        "retry_count": 0,
        "max_retries": 3,
        "error_message": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_skips_when_active_review(mock_settings, mock_factory):
    """Processing worker does nothing when a review session is active."""
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = MagicMock(return_value=ctx)

    with patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls:
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=True)
        mock_review_cls.return_value = review_repo

        await run_processing()

        review_repo.has_active_review.assert_awaited_once()


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_returns_when_queue_empty(mock_settings, mock_factory):
    """Processing worker returns early when no pending queue entries."""
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()

    session_calls = []

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session_calls.append(mock_session)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=None)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        queue_repo.claim_next.assert_awaited_once()


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_calls_process_entry(mock_settings, mock_factory, mock_process_entry):
    """Processing worker claims an entry and calls _process_entry."""
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    sessions = []

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        sessions.append(mock_session)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.return_value = None
    mock_process_entry.side_effect = None

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        mock_process_entry.assert_awaited_once()
        call_args = mock_process_entry.await_args
        assert call_args[0][1] == entry.id
        assert call_args[0][2] == entry.source_task_id


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_fails_entry_on_exception(
    mock_settings, mock_factory, mock_process_entry
):
    """Processing worker marks entry as failed when _process_entry raises."""
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    fail_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RuntimeError("LLM timeout")

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.fail = fail_mock
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        fail_mock.assert_awaited_once()
        fail_args = fail_mock.await_args
        assert fail_args[0][0] == entry.id
        assert "LLM timeout" in fail_args[0][1]
