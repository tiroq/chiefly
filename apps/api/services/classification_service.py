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

    async def _build_project_context(
        self,
        available_projects: list[Project],
    ) -> str:
        aliases_by_project: dict[uuid.UUID, list[str]] = {}
        if self._alias_repo is not None:
            alias_map = await self._alias_repo.get_all_aliases_map()
            for alias_str, proj_id in alias_map.items():
                aliases_by_project.setdefault(proj_id, []).append(alias_str)

        prompt_versions: dict[uuid.UUID, object] = {}
        if self._prompt_version_repo is not None:
            active_versions = await self._prompt_version_repo.get_all_active()
            for version in active_versions:
                prompt_versions[version.project_id] = version

        lines = ["Available projects:"]
        for project in available_projects:
            line_parts = [f"\n- **{project.name}**"]

            if project.description:
                line_parts.append(f"  Description: {project.description}")

            proj_aliases = aliases_by_project.get(project.id, [])
            if proj_aliases:
                line_parts.append(f"  Also known as: {', '.join(proj_aliases)}")

            version = prompt_versions.get(project.id)
            if version is not None:
                desc = getattr(version, "description_text", None)
                if desc:
                    line_parts.append(f"  Detailed description: {desc}")
                examples = getattr(version, "examples_json", None)
                if examples and isinstance(examples, list):
                    examples_str = "; ".join(str(e) for e in examples[:5])
                    line_parts.append(f"  Example tasks: {examples_str}")

            lines.append("\n".join(line_parts))

        if len(lines) == 1:
            lines.append("- Personal")

        return "\n".join(lines)

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
        project_context = await self._build_project_context(available_projects)
        classification = await self._llm.classify_task(
            raw_text,
            project_context,
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
                            project_context,
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
