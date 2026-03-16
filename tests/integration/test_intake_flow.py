"""
Integration tests for the task intake flow.
Uses mocked Google Tasks, LLM, and Telegram services.
Uses in-memory SQLite for DB tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ConfidenceBand, ProjectType, TaskKind, TaskStatus
from core.schemas.llm import TaskClassificationResult
from db.base import Base
from db.models import Project, TaskItem


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_session(db_session):
    """Session with a pre-seeded project."""
    project = Project(
        id=uuid.uuid4(),
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-tasklist-id",
        project_type=ProjectType.CLIENT,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    personal = Project(
        id=uuid.uuid4(),
        name="Personal",
        slug="personal",
        google_tasklist_id="personal-tasklist-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(project)
    db_session.add(personal)
    await db_session.commit()
    return db_session


@pytest.fixture
def classification_result():
    return TaskClassificationResult(
        kind=TaskKind.WAITING,
        normalized_title="Wait for Alex to send certificates",
        project_guess="NFT Gateway",
        project_confidence=ConfidenceBand.HIGH,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        substeps=[],
        ambiguities=[],
    )


@pytest.fixture
def google_task():
    from apps.api.services.google_tasks_service import GoogleTask
    return GoogleTask(
        id="gtask-001",
        title="жду от alex сертификаты",
        notes=None,
        status="needsAction",
        tasklist_id="inbox-list-id",
    )


@pytest.mark.asyncio
async def test_intake_creates_task_item(seeded_session, google_task, classification_result):
    """Test that intake creates a TaskItem record from a Google Task."""
    from apps.api.services.classification_service import ClassificationService
    from apps.api.services.google_tasks_service import GoogleTasksService
    from apps.api.services.intake_service import IntakeService
    from apps.api.services.llm_service import LLMService
    from apps.api.services.project_routing_service import ProjectRoutingService
    from apps.api.services.telegram_service import TelegramService
    from db.repositories.task_item_repo import TaskItemRepository

    mock_google = MagicMock(spec=GoogleTasksService)
    mock_google.list_tasks.return_value = [google_task]

    mock_llm = AsyncMock(spec=LLMService)
    mock_llm.classify_task.return_value = classification_result

    mock_tg = AsyncMock(spec=TelegramService)
    mock_tg.send_proposal.return_value = 42

    routing = ProjectRoutingService()
    classification = ClassificationService(mock_llm, routing)

    with patch("apps.api.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            google_tasks_inbox_list_id="inbox-list-id",
            telegram_chat_id="123456",
            llm_model="gpt-4o",
        )
        service = IntakeService(
            session=seeded_session,
            google_tasks=mock_google,
            classification=classification,
            telegram=mock_tg,
        )
        count = await service.poll_and_process()

    assert count == 1
    repo = TaskItemRepository(seeded_session)
    task = await repo.get_by_source_google_task_id("gtask-001")
    assert task is not None
    assert task.raw_text == "жду от alex сертификаты"
    assert task.status == TaskStatus.PROPOSED
    assert task.normalized_title == "Wait for Alex to send certificates"
    assert task.kind == TaskKind.WAITING


@pytest.mark.asyncio
async def test_intake_is_idempotent(seeded_session, google_task, classification_result):
    """Test that running intake twice for the same task doesn't create duplicates."""
    from apps.api.services.classification_service import ClassificationService
    from apps.api.services.google_tasks_service import GoogleTasksService
    from apps.api.services.intake_service import IntakeService
    from apps.api.services.llm_service import LLMService
    from apps.api.services.project_routing_service import ProjectRoutingService
    from apps.api.services.telegram_service import TelegramService
    from db.repositories.task_item_repo import TaskItemRepository

    mock_google = MagicMock(spec=GoogleTasksService)
    mock_google.list_tasks.return_value = [google_task]

    mock_llm = AsyncMock(spec=LLMService)
    mock_llm.classify_task.return_value = classification_result

    mock_tg = AsyncMock(spec=TelegramService)
    mock_tg.send_proposal.return_value = 42

    routing = ProjectRoutingService()
    classification = ClassificationService(mock_llm, routing)

    with patch("apps.api.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            google_tasks_inbox_list_id="inbox-list-id",
            telegram_chat_id="123456",
            llm_model="gpt-4o",
        )
        service = IntakeService(
            session=seeded_session,
            google_tasks=mock_google,
            classification=classification,
            telegram=mock_tg,
        )
        # Run twice
        count1 = await service.poll_and_process()
        count2 = await service.poll_and_process()

    assert count1 == 1
    assert count2 == 0  # Second run is idempotent

    # Only one task item created
    mock_tg.send_proposal.assert_called_once()


@pytest.mark.asyncio
async def test_intake_skips_empty_title(seeded_session):
    """Tasks with empty titles are skipped."""
    from apps.api.services.classification_service import ClassificationService
    from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
    from apps.api.services.intake_service import IntakeService
    from apps.api.services.llm_service import LLMService
    from apps.api.services.project_routing_service import ProjectRoutingService
    from apps.api.services.telegram_service import TelegramService

    empty_task = GoogleTask(
        id="gtask-empty", title="", notes=None, status="needsAction", tasklist_id="inbox"
    )

    mock_google = MagicMock(spec=GoogleTasksService)
    mock_google.list_tasks.return_value = [empty_task]

    mock_llm = AsyncMock(spec=LLMService)
    mock_tg = AsyncMock(spec=TelegramService)

    with patch("apps.api.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            google_tasks_inbox_list_id="inbox-list-id",
            telegram_chat_id="123456",
            llm_model="gpt-4o",
        )
        service = IntakeService(
            session=seeded_session,
            google_tasks=mock_google,
            classification=ClassificationService(mock_llm, ProjectRoutingService()),
            telegram=mock_tg,
        )
        count = await service.poll_and_process()

    assert count == 0
    mock_tg.send_proposal.assert_not_called()
