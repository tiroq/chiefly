"""
SystemEventService - convenience methods for logging system events.
Wraps SystemEventRepo with typed methods for common logging scenarios.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from db.models.system_event import SystemEvent
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class SystemEventService:
    """Service for logging system events with convenience methods."""

    def __init__(self, repo: SystemEventRepo) -> None:
        """Initialize with SystemEventRepo."""
        self._repo: SystemEventRepo = repo

    async def log_event(
        self,
        session: AsyncSession,
        event_type: str,
        severity: str,
        subsystem: str,
        message: str,
        task_item_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SystemEvent:
        """
        Log a system event.

        Args:
            session: Database session (passed per-method, not stored)
            event_type: Type of event (e.g., "classification", "user_login")
            severity: Severity level ("info", "warning", "error")
            subsystem: Subsystem that generated the event (e.g., "admin", "classification")
            message: Human-readable event message
            task_item_id: Optional task item ID
            project_id: Optional project ID
            payload: Optional JSON payload with additional context

        Returns:
            Created SystemEvent
        """
        event = SystemEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            severity=severity,
            subsystem=subsystem,
            message=message,
            task_item_id=task_item_id,
            project_id=project_id,
            payload_json=payload,
        )
        logger.info(
            "system_event",
            event_type=event_type,
            severity=severity,
            subsystem=subsystem,
            message=message,
        )
        return await self._repo.create(event)

    async def log_admin_action(
        self,
        session: AsyncSession,
        action: str,
        message: str,
        task_item_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SystemEvent:
        """
        Log an admin action.

        Sets severity='info' and subsystem='admin' by default.

        Args:
            session: Database session
            action: Admin action type
            message: Action description
            task_item_id: Optional task item ID
            project_id: Optional project ID
            payload: Optional additional context

        Returns:
            Created SystemEvent
        """
        return await self.log_event(
            session,
            action,
            "info",
            "admin",
            message,
            task_item_id,
            project_id,
            payload,
        )

    async def log_classification_event(
        self,
        session: AsyncSession,
        message: str,
        task_item_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SystemEvent:
        """
        Log a classification event.

        Sets event_type='classification', severity='info', subsystem='classification'.

        Args:
            session: Database session
            message: Classification event description
            task_item_id: Optional task item ID
            project_id: Optional project ID
            payload: Optional classification result details

        Returns:
            Created SystemEvent
        """
        return await self.log_event(
            session,
            "classification",
            "info",
            "classification",
            message,
            task_item_id,
            project_id,
            payload,
        )

    async def log_error(
        self,
        session: AsyncSession,
        subsystem: str,
        message: str,
        task_item_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SystemEvent:
        """
        Log an error event.

        Sets event_type='error' and severity='error' by default.

        Args:
            session: Database session
            subsystem: Subsystem where error occurred
            message: Error description
            task_item_id: Optional task item ID
            payload: Optional error details

        Returns:
            Created SystemEvent
        """
        return await self.log_event(
            session,
            "error",
            "error",
            subsystem,
            message,
            task_item_id,
            None,
            payload,
        )
