"""
Classification service - wraps LLM service and handles the classification pipeline.
"""

from __future__ import annotations

import uuid

from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.schemas.llm import TaskClassificationResult
from db.models.project import Project
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.prompt_version_repo import ProjectPromptVersionRepo

logger = get_logger(__name__)


class ClassificationService:
    def __init__(
        self,
        llm_service: LLMService,
        routing_service: ProjectRoutingService,
        prompt_version_repo: ProjectPromptVersionRepo | None = None,
        alias_repo: ProjectAliasRepo | None = None,
    ) -> None:
        self._llm = llm_service
        self._routing = routing_service
        self._prompt_version_repo = prompt_version_repo
        self._alias_repo = alias_repo

    async def classify(
        self,
        raw_text: str,
        available_projects: list[Project],
    ) -> tuple[TaskClassificationResult, Project | None]:
        """
        Classify raw text and route to a project.

        Returns (classification_result, routed_project).
        """
        routing_aliases: dict[str, uuid.UUID] = {}
        if self._alias_repo is not None:
            routing_aliases = await self._alias_repo.get_all_aliases_map()
        project_names = [p.name for p in available_projects]
        classification = await self._llm.classify_task(
            raw_text,
            project_names,
            custom_instructions=None,
        )

        if self._prompt_version_repo is not None:
            active_prompt_versions = await self._prompt_version_repo.get_all_active()
            active_prompt_map: dict[uuid.UUID, str] = {}
            for version in active_prompt_versions:
                prompt_text = getattr(version, "prompt_text", None) or getattr(
                    version, "classification_prompt_text", None
                )
                if prompt_text:
                    active_prompt_map[version.project_id] = prompt_text

            if active_prompt_map:
                matched_project, _ = self._routing.route(
                    raw_text=raw_text,
                    llm_project_guess=classification.project_guess,
                    llm_project_confidence=classification.project_confidence,
                    available_projects=available_projects,
                    aliases=routing_aliases,
                )
                if matched_project is not None:
                    custom_instructions = active_prompt_map.get(matched_project.id)
                    if custom_instructions is not None:
                        classification = await self._llm.classify_task(
                            raw_text,
                            project_names,
                            custom_instructions=custom_instructions,
                        )

        project, confidence = self._routing.route(
            raw_text=raw_text,
            llm_project_guess=classification.project_guess,
            llm_project_confidence=classification.project_confidence,
            available_projects=available_projects,
            aliases=routing_aliases,
        )

        # Override confidence band from routing
        classification = classification.model_copy(update={"project_confidence": confidence})

        logger.info(
            "classification_complete",
            kind=classification.kind,
            project=project.name if project else None,
            confidence=classification.confidence,
        )

        return classification, project
