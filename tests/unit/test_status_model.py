"""
Status model semantics tests.

These tests document and protect the cleaned-up processing/review
status model. They ensure:
  - WorkflowStatus covers all lifecycle states including FAILED and DISCARDED
  - ReviewSessionStatus covers all review lifecycle states
  - 'pending' (not-yet-processed) and 'active' (shown in Telegram) are distinct
  - processing does not block on active review
  - repository queries correctly distinguish states
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.enums import (
    ProcessingStatus,
    ReviewSessionStatus,
    WorkflowStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# A. Enum completeness and non-ambiguity
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflowStatusEnum:
    def test_has_all_lifecycle_states(self):
        values = {s.value for s in WorkflowStatus}
        # Processing pipeline states
        assert "pending" in values
        assert "processing" in values
        assert "awaiting_review" in values
        # Resolution states
        assert "applied" in values
        assert "discarded" in values
        # Failure state
        assert "failed" in values

    def test_pending_means_not_yet_processed(self):
        assert WorkflowStatus.PENDING.value == "pending"
        # Distinct from review-active state
        assert WorkflowStatus.PENDING != ReviewSessionStatus.ACTIVE

    def test_failed_is_distinct_from_discarded(self):
        assert WorkflowStatus.FAILED != WorkflowStatus.DISCARDED
        assert WorkflowStatus.FAILED.value == "failed"
        assert WorkflowStatus.DISCARDED.value == "discarded"

    def test_failed_is_not_awaiting_review(self):
        assert WorkflowStatus.FAILED != WorkflowStatus.AWAITING_REVIEW

    def test_discarded_is_not_applied(self):
        assert WorkflowStatus.DISCARDED != WorkflowStatus.APPLIED


class TestReviewSessionStatusEnum:
    def test_has_all_review_lifecycle_states(self):
        values = {s.value for s in ReviewSessionStatus}
        assert "queued" in values
        assert "active" in values
        assert "send_failed" in values
        assert "skipped" in values
        assert "resolved" in values

    def test_pending_is_not_a_valid_review_session_status(self):
        """'pending' was the old name for the active review state.
        After the rename, it must NOT appear as a ReviewSessionStatus value."""
        values = {s.value for s in ReviewSessionStatus}
        assert "pending" not in values

    def test_active_is_the_visible_review_state(self):
        assert ReviewSessionStatus.ACTIVE.value == "active"

    def test_queued_means_waiting_not_yet_shown(self):
        assert ReviewSessionStatus.QUEUED.value == "queued"

    def test_active_is_distinct_from_queued(self):
        assert ReviewSessionStatus.ACTIVE != ReviewSessionStatus.QUEUED

    def test_resolved_is_terminal(self):
        """resolved covers both confirm and discard outcomes."""
        assert ReviewSessionStatus.RESOLVED.value == "resolved"

    def test_failed_processing_is_not_a_review_session_state(self):
        """Processing failure (WorkflowStatus.FAILED) must never be confused
        with a review session outcome."""
        review_values = {s.value for s in ReviewSessionStatus}
        assert WorkflowStatus.FAILED.value not in review_values

    def test_skipped_is_not_resolved(self):
        assert ReviewSessionStatus.SKIPPED != ReviewSessionStatus.RESOLVED


# ─────────────────────────────────────────────────────────────────────────────
# B. Processing worker — no longer blocked by active review
# ─────────────────────────────────────────────────────────────────────────────


def _make_session_ctx():
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_processing_worker_does_not_call_has_active_review(mock_settings, mock_factory):
    """The active-review gate was removed. run_processing() must not consult
    ReviewSessionRepository at the entry point — it drives processing fully
    independent of review queue state."""
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()
    mock_factory.return_value = MagicMock(return_value=_make_session_ctx())

    with (
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
    ):
        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=None)
        mock_queue_cls.return_value = queue_repo

        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock()
        mock_review_cls.return_value = review_repo

        await run_processing()

        # queue is still checked (correct — we need to claim work)
        queue_repo.claim_next.assert_awaited_once()
        # but the active-review gate must NOT be consulted at top-level
        review_repo.has_active_review.assert_not_called()


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_processing_worker_claims_work_regardless_of_active_review(
    mock_settings, mock_factory
):
    """Even when an active review exists (has_active_review=True conceptually),
    the processing worker must still try to claim the next queue item."""
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()
    mock_factory.return_value = MagicMock(return_value=_make_session_ctx())

    with patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls:
        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=None)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        queue_repo.claim_next.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# C. send_next() is gated on active review (correct — only delivery is blocked)
# ─────────────────────────────────────────────────────────────────────────────


@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@pytest.mark.asyncio
async def test_send_next_blocks_on_active_review(mock_session_repo_cls):
    """Telegram delivery (send_next) must still block if an item is active.
    Only processing is decoupled — not the delivery gate."""
    from apps.api.services.review_queue_service import ReviewQueueService, SendNextResult

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=True)
    mock_session_repo_cls.return_value = session_repo

    session = MagicMock()
    telegram = MagicMock()
    svc = ReviewQueueService(session=session, telegram=telegram)

    result = await svc.send_next()

    assert result == SendNextResult.ACTIVE_EXISTS
    session_repo.has_active_review.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# D. Repository query semantics
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_active_review_queries_active_not_queued():
    """has_active_review() must only return True when a session is ACTIVE
    (currently visible in Telegram), not merely queued."""
    from db.repositories.review_session_repo import ReviewSessionRepository

    mock_session = MagicMock()
    # Simulate: only a queued session exists (no active)
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(return_value=mock_result)

    repo = ReviewSessionRepository(mock_session)
    result = await repo.has_active_review()
    assert result is False

    # Verify the query was against telegram_review_sessions.status
    stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(stmt)
    # The column being filtered is the 'status' column
    assert "telegram_review_sessions.status" in stmt_str
    # The query must not be a simple count-all (it has a WHERE clause)
    assert "WHERE" in stmt_str.upper()


@pytest.mark.asyncio
async def test_count_queued_queries_only_queued_status():
    """count_queued() must only count QUEUED sessions, not ACTIVE ones."""
    from db.repositories.review_session_repo import ReviewSessionRepository

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 3
    mock_session.execute = AsyncMock(return_value=mock_result)

    repo = ReviewSessionRepository(mock_session)
    count = await repo.count_queued()
    assert count == 3

    # Verify the query targets the status column
    stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(stmt)
    assert "telegram_review_sessions.status" in stmt_str
    # The compiled form uses bind parameters so we check it has a WHERE clause
    assert "WHERE" in stmt_str.upper()


@pytest.mark.asyncio
async def test_get_active_by_stable_id_queries_status_column():
    """get_active_by_stable_id() must filter on the status column."""
    from db.repositories.review_session_repo import ReviewSessionRepository

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    repo = ReviewSessionRepository(mock_session)
    result = await repo.get_active_by_stable_id(uuid.uuid4())
    assert result is None

    stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(stmt)
    assert "telegram_review_sessions.status" in stmt_str


# ─────────────────────────────────────────────────────────────────────────────
# E. Model separation: buffered pre-processing semantics
# ─────────────────────────────────────────────────────────────────────────────


def test_review_session_status_supports_buffer_semantics():
    """A task can be processed (creating a QUEUED session) while another
    task's session is ACTIVE. This is the key invariant for buffered
    pre-processing: QUEUED != ACTIVE."""
    assert ReviewSessionStatus.QUEUED != ReviewSessionStatus.ACTIVE
    # A QUEUED session is not being reviewed yet
    assert ReviewSessionStatus.QUEUED.value == "queued"
    # An ACTIVE session is currently visible to the user
    assert ReviewSessionStatus.ACTIVE.value == "active"


def test_workflow_status_failure_semantics():
    """Processing failure is tracked on the TaskRecord, not on review sessions.
    These are orthogonal concerns."""
    # FAILED is a WorkflowStatus (processing pipeline failure)
    assert WorkflowStatus.FAILED.value == "failed"
    # FAILED must not appear in ReviewSessionStatus
    review_values = {s.value for s in ReviewSessionStatus}
    assert "failed" not in review_values


def test_workflow_status_discard_semantics():
    """User discarding a proposal is tracked as DISCARDED on the TaskRecord.
    The review session itself becomes RESOLVED (same terminal status for both
    confirm and discard)."""
    assert WorkflowStatus.DISCARDED.value == "discarded"
    # Both confirm and discard produce a RESOLVED review session
    assert ReviewSessionStatus.RESOLVED.value == "resolved"
    # Discard is distinct from processing failure
    assert WorkflowStatus.DISCARDED != WorkflowStatus.FAILED
