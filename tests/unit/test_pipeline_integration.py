import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.classification_service import ClassificationService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand, ProjectType, TaskKind
from db.models.project import Project


def _make_project(
    name: str, slug: str, project_type: ProjectType = ProjectType.PERSONAL
) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        google_tasklist_id=f"{slug}-list",
        project_type=project_type,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def projects():
    return [
        _make_project("NFT Gateway", "nft-gateway", ProjectType.CLIENT),
        _make_project("Personal", "personal", ProjectType.PERSONAL),
        _make_project("Writing", "writing", ProjectType.WRITING),
    ]


@pytest.fixture
def llm_service():
    return LLMService(provider="openai", model="gpt-4o", api_key="test-key")


@pytest.fixture
def routing_service():
    return ProjectRoutingService()


class TestClassificationPipeline:
    @pytest.mark.asyncio
    async def test_classify_returns_legacy_result(self, llm_service, routing_service, projects):
        normalize_json = json.dumps(
            {
                "intent_summary": "Wait for Alex certificates",
                "is_multi_item": False,
                "entities": ["Alex", "certificates"],
                "language": "ru",
            }
        )
        classify_json = json.dumps(
            {
                "type": "waiting",
                "project": "NFT Gateway",
                "confidence": "high",
                "reasoning": "Waiting for external party",
                "title": "Wait for Alex to send certificates",
                "next_action": "Send follow-up to Alex",
            }
        )

        def mock_llm(prompt):
            if "task interpreter" in prompt.lower():
                return normalize_json
            return classify_json

        svc = ClassificationService(llm_service, routing_service)
        with patch.object(llm_service, "_call_llm_sync", side_effect=mock_llm):
            classification, project = await svc.classify("жду от alex сертификаты", projects)

        assert classification.kind == TaskKind.WAITING
        assert classification.normalized_title == "Wait for Alex to send certificates"
        assert classification.next_action == "Send follow-up to Alex"
        assert project is not None
        assert project.slug == "nft-gateway"

    @pytest.mark.asyncio
    async def test_classify_pipeline_returns_pipeline_result(
        self, llm_service, routing_service, projects
    ):
        normalize_json = json.dumps(
            {
                "intent_summary": "Buy groceries",
                "is_multi_item": False,
                "entities": ["groceries"],
                "language": "en",
            }
        )
        classify_json = json.dumps(
            {
                "type": "task",
                "project": "Personal",
                "confidence": "high",
                "reasoning": "Personal errand",
                "title": "Buy groceries from store",
                "next_action": "Make a shopping list",
            }
        )

        def mock_llm(prompt):
            if "task interpreter" in prompt.lower():
                return normalize_json
            return classify_json

        svc = ClassificationService(llm_service, routing_service)
        with patch.object(llm_service, "_call_llm_sync", side_effect=mock_llm):
            pipeline_result, project = await svc.classify_pipeline("buy groceries", projects)

        assert pipeline_result.type == TaskKind.TASK
        assert pipeline_result.title == "Buy groceries from store"
        assert pipeline_result.intent_summary == "Buy groceries"
        assert project is not None
        assert project.slug == "personal"

    @pytest.mark.asyncio
    async def test_classify_fallback_routes_to_personal(
        self, llm_service, routing_service, projects
    ):
        svc = ClassificationService(llm_service, routing_service)
        with patch.object(llm_service, "_call_llm_sync", side_effect=Exception("fail")):
            classification, project = await svc.classify("buy milk", projects)

        assert classification.confidence == ConfidenceBand.LOW
        assert project is not None
        assert project.slug == "personal"

    @pytest.mark.asyncio
    async def test_classify_with_aliases(self, llm_service, routing_service, projects):
        normalize_json = json.dumps(
            {
                "intent_summary": "Deploy NFT contract",
                "is_multi_item": False,
                "entities": ["NFT"],
                "language": "en",
            }
        )
        classify_json = json.dumps(
            {
                "type": "task",
                "project": "NFT Gateway",
                "confidence": "high",
                "reasoning": "NFT related",
                "title": "Deploy NFT smart contract",
                "next_action": "Review contract code",
            }
        )

        def mock_llm(prompt):
            if "task interpreter" in prompt.lower():
                return normalize_json
            return classify_json

        alias_repo = AsyncMock()
        alias_repo.get_all_aliases_map.return_value = {
            "nft": projects[0].id,
        }

        svc = ClassificationService(llm_service, routing_service, alias_repo=alias_repo)
        with patch.object(llm_service, "_call_llm_sync", side_effect=mock_llm):
            classification, project = await svc.classify("deploy nft contract", projects)

        assert project is not None
        assert project.slug == "nft-gateway"

    @pytest.mark.asyncio
    async def test_pipeline_preserves_backward_compatibility(
        self, llm_service, routing_service, projects
    ):
        normalize_json = json.dumps(
            {
                "intent_summary": "New app idea",
                "is_multi_item": False,
                "entities": [],
                "language": "en",
            }
        )
        classify_json = json.dumps(
            {
                "type": "idea",
                "project": "Writing",
                "confidence": "medium",
                "reasoning": "Not actionable yet",
                "title": "Explore AI assistant concept",
                "next_action": "Write rough concept doc",
            }
        )

        def mock_llm(prompt):
            if "task interpreter" in prompt.lower():
                return normalize_json
            return classify_json

        svc = ClassificationService(llm_service, routing_service)
        with patch.object(llm_service, "_call_llm_sync", side_effect=mock_llm):
            classification, project = await svc.classify("идея сделать ai ассистента", projects)

        assert classification.kind == TaskKind.IDEA
        assert classification.normalized_title == "Explore AI assistant concept"
        assert classification.substeps is not None
        assert classification.ambiguities is not None
        assert hasattr(classification, "project_guess")
        assert hasattr(classification, "project_confidence")

    @pytest.mark.asyncio
    async def test_pipeline_include_steps(self, llm_service, routing_service, projects):
        normalize_json = json.dumps(
            {
                "intent_summary": "Buy groceries",
                "is_multi_item": False,
                "entities": [],
                "language": "en",
            }
        )
        classify_json = json.dumps(
            {
                "type": "task",
                "project": "Personal",
                "confidence": "high",
                "reasoning": "r",
                "title": "Buy groceries",
                "next_action": "Make list",
            }
        )
        steps_json = json.dumps({"steps": ["Make list", "Go to store", "Buy items"]})

        # Route mock responses by prompt content since _call_and_parse retries
        # make counter-based approaches fragile.
        def mock_llm(prompt):
            if "breaking down" in prompt.lower():
                return steps_json
            if "task interpreter" in prompt.lower():
                return normalize_json
            return classify_json

        svc = ClassificationService(llm_service, routing_service)
        with patch.object(llm_service, "_call_llm_sync", side_effect=mock_llm):
            classification, project = await svc.classify("buy groceries", projects)

        assert len(classification.substeps) == 3
