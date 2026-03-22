from __future__ import annotations

import uuid

from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand
from core.schemas.llm import PipelineResult, TaskClassificationResult
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

    async def _get_custom_instructions(
        self,
        project: Project | None,
    ) -> str | None:
        if project is None or self._prompt_version_repo is None:
            return None
        active_versions = await self._prompt_version_repo.get_all_active()
        for version in active_versions:
            if version.project_id == project.id:
                return getattr(version, "prompt_text", None) or getattr(
                    version, "classification_prompt_text", None
                )
        return None

    async def _get_routing_aliases(self) -> dict[str, uuid.UUID]:
        if self._alias_repo is not None:
            return await self._alias_repo.get_all_aliases_map()
        return {}

    def _route_project(
        self,
        raw_text: str,
        project_guess: str | None,
        project_confidence: ConfidenceBand,
        available_projects: list[Project],
        routing_aliases: dict[str, uuid.UUID],
    ) -> tuple[Project | None, ConfidenceBand]:
        return self._routing.route(
            raw_text=raw_text,
            llm_project_guess=project_guess,
            llm_project_confidence=project_confidence,
            available_projects=available_projects,
            aliases=routing_aliases,
        )

    async def classify_pipeline(
        self,
        raw_text: str,
        available_projects: list[Project],
        include_description: bool = False,
        include_steps: bool = False,
    ) -> tuple[PipelineResult, Project | None]:
        routing_aliases = await self._get_routing_aliases()
        project_context = await self._build_project_context(available_projects)

        default_project_name = "Personal"
        for p in available_projects:
            if p.slug == "personal":
                default_project_name = p.name
                break

        pipeline_result = await self._llm.run_pipeline(
            raw_text=raw_text,
            project_context=project_context,
            include_description=include_description,
            include_steps=include_steps,
            project_fallback=default_project_name,
        )

        project, confidence = self._route_project(
            raw_text=raw_text,
            project_guess=pipeline_result.project,
            project_confidence=pipeline_result.confidence,
            available_projects=available_projects,
            routing_aliases=routing_aliases,
        )

        if project is not None:
            custom_instructions = await self._get_custom_instructions(project)
            if custom_instructions is not None:
                pipeline_result = await self._llm.run_pipeline(
                    raw_text=raw_text,
                    project_context=project_context,
                    custom_instructions=custom_instructions,
                    include_description=include_description,
                    include_steps=include_steps,
                    project_fallback=default_project_name,
                )
                project, confidence = self._route_project(
                    raw_text=raw_text,
                    project_guess=pipeline_result.project,
                    project_confidence=pipeline_result.confidence,
                    available_projects=available_projects,
                    routing_aliases=routing_aliases,
                )

        pipeline_result = pipeline_result.model_copy(update={"confidence": confidence})

        logger.info(
            "pipeline_classification_complete",
            type=pipeline_result.type,
            project=project.name if project else None,
            confidence=pipeline_result.confidence,
        )

        return pipeline_result, project

    async def classify(
        self,
        raw_text: str,
        available_projects: list[Project],
    ) -> tuple[TaskClassificationResult, Project | None]:
        pipeline_result, project = await self.classify_pipeline(
            raw_text=raw_text,
            available_projects=available_projects,
            include_description=False,
            include_steps=True,
        )

        classification = pipeline_result.to_legacy()
        return classification, project
