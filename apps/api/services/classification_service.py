"""
Classification service - wraps LLM service and handles the classification pipeline.
"""

from __future__ import annotations

from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from core.schemas.llm import TaskClassificationResult
from db.models.project import Project

logger = get_logger(__name__)


class ClassificationService:
    def __init__(
        self,
        llm_service: LLMService,
        routing_service: ProjectRoutingService,
    ) -> None:
        self._llm = llm_service
        self._routing = routing_service

    async def classify(
        self,
        raw_text: str,
        available_projects: list[Project],
    ) -> tuple[TaskClassificationResult, Project | None]:
        """
        Classify raw text and route to a project.

        Returns (classification_result, routed_project).
        """
        project_names = [p.name for p in available_projects]
        classification = await self._llm.classify_task(raw_text, project_names)

        project, confidence = self._routing.route(
            raw_text=raw_text,
            llm_project_guess=classification.project_guess,
            llm_project_confidence=classification.project_confidence,
            available_projects=available_projects,
        )

        # Override confidence band from routing
        classification = classification.model_copy(
            update={"project_confidence": confidence}
        )

        logger.info(
            "classification_complete",
            kind=classification.kind,
            project=project.name if project else None,
            confidence=classification.confidence,
        )

        return classification, project
