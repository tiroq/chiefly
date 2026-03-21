from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.classification_service import ClassificationService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand, ProjectType, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.models.project import Project
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.prompt_version_repo import ProjectPromptVersionRepo


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
def projects() -> list[Project]:
    return [
        _make_project("NFT Gateway", "nft-gateway", ProjectType.CLIENT),
        _make_project("Personal", "personal"),
    ]


@pytest.fixture
def llm_result() -> TaskClassificationResult:
    return TaskClassificationResult(
        kind=TaskKind.TASK,
        normalized_title="Deploy NFT contract",
        project_guess="NFT Gateway",
        project_confidence=ConfidenceBand.HIGH,
        confidence=ConfidenceBand.HIGH,
    )


class TestClassificationWithPrompts:
    async def test_alias_repo_is_used_for_routing_aliases(
        self,
        projects: list[Project],
        llm_result: TaskClassificationResult,
    ) -> None:
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = llm_result.model_copy(
            update={"project_guess": "Personal"}
        )
        mock_alias_repo = AsyncMock(spec=ProjectAliasRepo)
        mock_alias_repo.get_all_aliases_map.return_value = {"deploy": projects[0].id}

        svc = ClassificationService(
            llm_service=mock_llm,
            routing_service=ProjectRoutingService(),
            alias_repo=mock_alias_repo,
        )

        _, project = await svc.classify("deploy nft contract", projects)

        assert mock_alias_repo.get_all_aliases_map.await_count == 2
        assert project is not None
        assert project.slug == "nft-gateway"

    async def test_no_active_prompts_uses_project_context(
        self,
        projects: list[Project],
        llm_result: TaskClassificationResult,
    ) -> None:
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = llm_result
        mock_repo = AsyncMock(spec=ProjectPromptVersionRepo)
        mock_repo.get_all_active.return_value = []

        svc = ClassificationService(
            llm_service=mock_llm,
            routing_service=ProjectRoutingService(),
            prompt_version_repo=mock_repo,
        )

        await svc.classify("deploy nft contract", projects)

        assert mock_repo.get_all_active.await_count == 2
        mock_llm.classify_task.assert_awaited_once()
        call = mock_llm.classify_task.await_args_list[0]
        assert call.args[0] == "deploy nft contract"
        assert "Available projects:" in call.args[1]
        assert "NFT Gateway" in call.args[1]
        assert "Personal" in call.args[1]
        assert call.kwargs == {"custom_instructions": None}

    async def test_active_prompt_for_matched_project_injects_custom_instructions(
        self,
        projects: list[Project],
        llm_result: TaskClassificationResult,
    ) -> None:
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.side_effect = [llm_result, llm_result]
        mock_repo = AsyncMock(spec=ProjectPromptVersionRepo)
        mock_repo.get_all_active.return_value = [
            MagicMock(
                project_id=projects[0].id,
                prompt_text="Prefer blockchain-specific wording and deployment checks.",
            )
        ]

        svc = ClassificationService(
            llm_service=mock_llm,
            routing_service=ProjectRoutingService(),
            prompt_version_repo=mock_repo,
        )

        await svc.classify("deploy nft contract", projects)

        assert mock_repo.get_all_active.await_count == 2
        assert mock_llm.classify_task.await_count == 2
        first_call = mock_llm.classify_task.await_args_list[0]
        second_call = mock_llm.classify_task.await_args_list[1]
        assert first_call.kwargs == {"custom_instructions": None}
        assert second_call.kwargs == {
            "custom_instructions": "Prefer blockchain-specific wording and deployment checks.",
        }

    async def test_active_prompts_for_other_projects_uses_single_pass_context(
        self,
        projects: list[Project],
        llm_result: TaskClassificationResult,
    ) -> None:
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.classify_task.return_value = llm_result
        mock_repo = AsyncMock(spec=ProjectPromptVersionRepo)
        mock_repo.get_all_active.return_value = [
            MagicMock(
                project_id=projects[1].id,
                prompt_text="Focus on errands and household context.",
            )
        ]

        svc = ClassificationService(
            llm_service=mock_llm,
            routing_service=ProjectRoutingService(),
            prompt_version_repo=mock_repo,
        )

        await svc.classify("deploy nft contract", projects)

        assert mock_repo.get_all_active.await_count == 2
        mock_llm.classify_task.assert_awaited_once()
        call = mock_llm.classify_task.await_args_list[0]
        assert call.args[0] == "deploy nft contract"
        assert "Available projects:" in call.args[1]
        assert "NFT Gateway" in call.args[1]
        assert "Personal" in call.args[1]
        assert call.kwargs == {"custom_instructions": None}
