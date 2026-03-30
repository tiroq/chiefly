from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.review_queue_service import ReviewQueueService
from apps.api.services.telegram_service import _build_proposal_text
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult


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
            "project_name": "Personal",
        },
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_classification() -> TaskClassificationResult:
    return TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Buy groceries",
        confidence=ConfidenceBand.HIGH,
        project_confidence=ConfidenceBand.HIGH,
    )


def test_build_proposal_text_includes_queue_position_when_provided():
    text = _build_proposal_text("raw", _make_classification(), "Personal", queue_position=3)
    assert "📋 Queue position: 3" in text


@patch("apps.api.services.review_queue_service.TaskSnapshotRepository")
@patch("apps.api.services.review_queue_service.ReviewSessionRepository")
@patch("apps.api.services.review_queue_service.is_review_paused", return_value=False)
@pytest.mark.asyncio
async def test_send_next_passes_queue_position_to_proposal(
    _mock_is_paused,
    mock_session_repo_cls,
    mock_snapshot_repo_cls,
):
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()

    telegram = MagicMock()
    telegram.send_proposal = AsyncMock(return_value=777)
    telegram.send_text = AsyncMock()

    service = ReviewQueueService(session=mock_session, telegram=telegram)
    queued = _make_review_session()

    session_repo = MagicMock()
    session_repo.has_active_review = AsyncMock(return_value=False)
    session_repo.get_next_queued_for_update = AsyncMock(return_value=queued)
    session_repo.save = AsyncMock()
    session_repo.count_queued = AsyncMock(return_value=0)
    mock_session_repo_cls.return_value = session_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=None)
    mock_snapshot_repo_cls.return_value = snapshot_repo

    await service.send_next()

    sent_kwargs = telegram.send_proposal.await_args.kwargs
    assert sent_kwargs["queue_position"] == 1
