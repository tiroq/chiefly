"""
Integration tests for the classification service with mocked LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from apps.api.services.classification_service import ClassificationService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand, ProjectType, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.models.project import Project


def _make_project(name: str, slug: str, ptype: ProjectType = ProjectType.PERSONAL) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        google_tasklist_id=f"{slug}-list",
        project_type=ptype,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def projects():
    return [
        _make_project("NFT Gateway", "nft-gateway", ProjectType.CLIENT),
        _make_project("Personal", "personal"),
        _make_project("Family", "family", ProjectType.FAMILY),
    ]


class TestClassificationService:
    @pytest.mark.asyncio
    async def test_classify_routes_to_project(self, projects):
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = TaskClassificationResult(
            kind=TaskKind.TASK,
            normalized_title="Deploy NFT contract",
            project_guess="NFT Gateway",
            project_confidence=ConfidenceBand.HIGH,
            confidence=ConfidenceBand.HIGH,
        )
        routing = ProjectRoutingService()
        svc = ClassificationService(mock_llm, routing)

        result, project = await svc.classify("deploy nft contract", projects)
        assert result.kind == TaskKind.TASK
        assert project is not None
        assert project.slug == "nft-gateway"

    @pytest.mark.asyncio
    async def test_classify_keyword_overrides_llm_guess(self, projects):
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = TaskClassificationResult(
            kind=TaskKind.TASK,
            normalized_title="Call kids school",
            project_guess="Personal",
            project_confidence=ConfidenceBand.HIGH,
            confidence=ConfidenceBand.HIGH,
        )
        routing = ProjectRoutingService()
        svc = ClassificationService(mock_llm, routing)

        result, project = await svc.classify("Call kids school", projects)
        # Keyword "kids" should route to "family" despite LLM saying Personal
        assert project is not None
        assert project.slug == "family"

    @pytest.mark.asyncio
    async def test_classify_fallback_to_personal(self, projects):
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = TaskClassificationResult(
            kind=TaskKind.TASK,
            normalized_title="Buy milk",
            project_guess=None,
            project_confidence=ConfidenceBand.LOW,
            confidence=ConfidenceBand.MEDIUM,
        )
        routing = ProjectRoutingService()
        svc = ClassificationService(mock_llm, routing)

        result, project = await svc.classify("buy milk", projects)
        assert project is not None
        assert project.slug == "personal"

    @pytest.mark.asyncio
    async def test_classify_no_projects_available(self):
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = TaskClassificationResult(
            kind=TaskKind.IDEA,
            normalized_title="New feature",
            confidence=ConfidenceBand.LOW,
        )
        routing = ProjectRoutingService()
        svc = ClassificationService(mock_llm, routing)

        result, project = await svc.classify("new feature", [])
        assert project is None

    @pytest.mark.asyncio
    async def test_classify_passes_project_names_to_llm(self, projects):
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = TaskClassificationResult(
            kind=TaskKind.TASK,
            normalized_title="Test",
            confidence=ConfidenceBand.MEDIUM,
        )
        routing = ProjectRoutingService()
        svc = ClassificationService(mock_llm, routing)

        await svc.classify("test text", projects)
        call_args = mock_llm.classify_task.call_args
        project_names = call_args[0][1]  # second positional arg
        assert "NFT Gateway" in project_names
        assert "Personal" in project_names
        assert "Family" in project_names
