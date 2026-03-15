"""
Test configuration and shared fixtures.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


@pytest.fixture
def sample_uuid() -> uuid.UUID:
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def utcnow() -> datetime:
    return datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_google_tasks():
    from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService

    svc = MagicMock(spec=GoogleTasksService)
    svc.list_tasks.return_value = [
        GoogleTask(
            id="gtask-001",
            title="жду от alex сертификаты",
            notes=None,
            status="needsAction",
            tasklist_id="inbox-list-id",
        )
    ]
    svc.move_task.return_value = GoogleTask(
        id="gtask-002",
        title="Wait for Alex to send certificates",
        notes=None,
        status="needsAction",
        tasklist_id="target-list-id",
    )
    svc.patch_task.return_value = MagicMock()
    return svc


@pytest.fixture
def mock_telegram():
    from apps.api.services.telegram_service import TelegramService

    svc = AsyncMock(spec=TelegramService)
    svc.send_proposal.return_value = 42
    svc.send_text.return_value = 43
    return svc


@pytest.fixture
def mock_llm():
    from apps.api.services.llm_service import LLMService
    from core.domain.enums import ConfidenceBand, TaskKind
    from core.schemas.llm import TaskClassificationResult

    svc = MagicMock(spec=LLMService)
    svc.classify_task.return_value = TaskClassificationResult(
        kind=TaskKind.WAITING,
        normalized_title="Wait for Alex to send certificates",
        project_guess="NFT Gateway",
        project_confidence=ConfidenceBand.HIGH,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        substeps=[],
        ambiguities=[],
    )
    svc.generate_daily_review.return_value = "Daily review summary text"
    return svc


@pytest.fixture
def sample_project():
    from db.models.project import Project
    from core.domain.enums import ProjectType

    return Project(
        id=uuid.uuid4(),
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-tasklist-id",
        project_type=ProjectType.CLIENT,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def personal_project():
    from db.models.project import Project
    from core.domain.enums import ProjectType

    return Project(
        id=uuid.uuid4(),
        name="Personal",
        slug="personal",
        google_tasklist_id="personal-tasklist-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
