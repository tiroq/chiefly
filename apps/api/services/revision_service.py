"""
Revision service - manages task revision history.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.domain.enums import ReviewAction, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.models.task_revision import TaskRevision
from db.repositories.task_revision_repo import TaskRevisionRepository

logger = get_logger(__name__)


class RevisionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TaskRevisionRepository(session)

    async def create_classification_revision(
        self,
        stable_id: uuid.UUID,
        raw_text: str,
        classification: TaskClassificationResult,
        project_id: uuid.UUID | None,
    ) -> TaskRevision:
        revision_no = await self._repo.get_next_revision_no_by_stable_id(stable_id)
        revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=stable_id,
            revision_no=revision_no,
            raw_text=raw_text,
            proposal_json=classification.model_dump(),
            final_title=classification.normalized_title,
            final_kind=classification.kind,
            final_project_id=project_id,
            final_next_action=classification.next_action,
        )
        return await self._repo.create(revision)

    async def create_decision_revision(
        self,
        stable_id: uuid.UUID,
        raw_text: str,
        decision: ReviewAction,
        classification: TaskClassificationResult,
        project_id: uuid.UUID | None,
        user_notes: str | None = None,
        final_kind: TaskKind | None = None,
    ) -> TaskRevision:
        revision_no = await self._repo.get_next_revision_no_by_stable_id(stable_id)
        revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=stable_id,
            revision_no=revision_no,
            raw_text=raw_text,
            proposal_json=classification.model_dump(),
            user_decision=decision,
            user_notes=user_notes,
            final_title=classification.normalized_title,
            final_kind=final_kind or classification.kind,
            final_project_id=project_id,
            final_next_action=classification.next_action,
        )
        return await self._repo.create(revision)

    async def list_revisions(self, stable_id: uuid.UUID) -> list[TaskRevision]:
        return await self._repo.list_by_stable_id(stable_id)
