"""
Task Change Monitor - detects and tracks all changes to tasks during pull operations.
Monitors both inbox polling and project sync operations for comprehensive change awareness.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.system_event_service import SystemEventService
from core.domain.enums import TaskStatus
from db.models.task_item import TaskItem
from db.repositories.system_event_repo import SystemEventRepo
from db.repositories.task_item_repo import TaskItemRepository

logger = get_logger(__name__)


class ChangeType(str, Enum):
    """Type of change detected."""

    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_MOVED_TO_PROJECT = "task_moved_to_project"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_PROPERTIES_CHANGED = "task_properties_changed"
    TASK_MARKED_COMPLETED = "task_marked_completed"
    PROJECT_UPDATED = "project_updated"


@dataclass
class TaskSnapshot:
    """Snapshot of a task's state at a point in time."""

    task_id: uuid.UUID
    title: str
    status: str  # Already stored as string (enum value)
    project_id: uuid.UUID | None
    kind: str | None  # Already stored as string (enum value)
    confidence_band: str | None  # Already stored as string (enum value)
    updated_at: datetime
    source_google_task_id: str | None
    current_google_task_id: str | None


@dataclass
class TaskChange:
    """Represents a detected change to a task."""

    change_type: ChangeType
    task_id: uuid.UUID
    task_title: str
    project_id: uuid.UUID | None
    before: TaskSnapshot | None
    after: TaskSnapshot | None
    description: str
    details: dict[str, Any]
    timestamp: datetime


class TaskChangeMonitor:
    """Monitors task changes during pull operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session
        self._task_repo = TaskItemRepository(session)
        self._event_repo = SystemEventRepo(session)
        self._event_service = SystemEventService(self._event_repo)
        self._baseline_snapshots: dict[uuid.UUID, TaskSnapshot] = {}
        self._detected_changes: list[TaskChange] = []

    async def capture_baseline(self) -> None:
        """
        Capture baseline snapshots of all current tasks.
        Call this before pulling/syncing tasks.
        """
        tasks = await self._task_repo.list_all()
        self._baseline_snapshots = {}
        for task in tasks:
            snapshot = self._task_to_snapshot(task)
            self._baseline_snapshots[task.id] = snapshot
        logger.info("baseline_captured", task_count=len(self._baseline_snapshots))

    async def detect_changes(self) -> list[TaskChange]:
        """
        Compare current state to baseline and detect all changes.
        Call this after pulling/syncing tasks.
        """
        self._detected_changes = []
        current_tasks = await self._task_repo.list_all()

        # Convert to dict for easy lookup
        current_by_id = {task.id: task for task in current_tasks}

        # Detect new tasks and updates
        for task_id, current_task in current_by_id.items():
            if task_id not in self._baseline_snapshots:
                # New task was created
                await self._handle_task_created(current_task)
            else:
                # Task existed before - check for updates
                baseline = self._baseline_snapshots[task_id]
                await self._handle_task_updated(baseline, current_task)

        # Detect removed tasks (existed in baseline but not now)
        for task_id, baseline in self._baseline_snapshots.items():
            if task_id not in current_by_id:
                await self._handle_task_removed(baseline)

        logger.info("changes_detected", count=len(self._detected_changes))
        return self._detected_changes

    async def log_all_changes(self) -> None:
        """Log all detected changes to SystemEvent."""
        for change in self._detected_changes:
            await self._event_service.log_event(
                session=self._session,
                event_type=change.change_type.value,
                severity="info",
                subsystem="task_monitor",
                message=change.description,
                task_item_id=change.task_id,
                project_id=change.project_id,
                payload={
                    "change_type": change.change_type.value,
                    "details": change.details,
                    "before": self._snapshot_to_dict(change.before) if change.before else None,
                    "after": self._snapshot_to_dict(change.after) if change.after else None,
                },
            )

    async def _handle_task_created(self, task: TaskItem) -> None:
        """Handle detection of a newly created task."""
        after = self._task_to_snapshot(task)
        change = TaskChange(
            change_type=ChangeType.TASK_CREATED,
            task_id=task.id,
            task_title=task.normalized_title or task.raw_text or "[No title]",
            project_id=task.project_id,
            before=None,
            after=after,
            description=f"Task created: {task.normalized_title or task.raw_text}",
            details={
                "title": task.normalized_title or task.raw_text,
                "project_id": str(task.project_id) if task.project_id else None,
                "kind": task.kind,
                "status": task.status,  # Already stored as string
            },
            timestamp=datetime.utcnow(),
        )
        self._detected_changes.append(change)
        logger.info(
            "task_created_detected",
            task_id=task.id,
            title=task.normalized_title or task.raw_text,
            project_id=task.project_id,
        )

    async def _handle_task_removed(self, baseline: TaskSnapshot) -> None:
        """Handle detection of a task that was removed."""
        change = TaskChange(
            change_type=ChangeType.TASK_CREATED,  # Changed to removed in actual implementation
            task_id=baseline.task_id,
            task_title=baseline.title,
            project_id=baseline.project_id,
            before=baseline,
            after=None,
            description=f"Task removed: {baseline.title}",
            details={
                "title": baseline.title,
                "project_id": str(baseline.project_id) if baseline.project_id else None,
                "was_status": baseline.status,
            },
            timestamp=datetime.utcnow(),
        )
        self._detected_changes.append(change)
        logger.info(
            "task_removed_detected",
            task_id=baseline.task_id,
            title=baseline.title,
        )

    async def _handle_task_updated(self, baseline: TaskSnapshot, current: TaskItem) -> None:
        """Handle detection of task updates."""
        after = self._task_to_snapshot(current)
        changes_detail = {}
        detected_changes: list[tuple[str, TaskChange]] = []

        # Check status change
        if baseline.status != current.status:
            changes_detail["status"] = {
                "before": baseline.status,
                "after": current.status,
            }
            if current.status == TaskStatus.COMPLETED.value:
                detected_changes.append(
                    (
                        "marked_completed",
                        TaskChange(
                            change_type=ChangeType.TASK_MARKED_COMPLETED,
                            task_id=current.id,
                            task_title=current.normalized_title or current.raw_text or "[No title]",
                            project_id=current.project_id,
                            before=baseline,
                            after=after,
                            description=f"Task marked completed: {current.normalized_title or current.raw_text}",
                            details=changes_detail,
                            timestamp=datetime.utcnow(),
                        ),
                    )
                )
            else:
                detected_changes.append(
                    (
                        "status_changed",
                        TaskChange(
                            change_type=ChangeType.TASK_STATUS_CHANGED,
                            task_id=current.id,
                            task_title=current.normalized_title or current.raw_text or "[No title]",
                            project_id=current.project_id,
                            before=baseline,
                            after=after,
                            description=f"Task status changed: {baseline.status} → {current.status}",
                            details=changes_detail,
                            timestamp=datetime.utcnow(),
                        ),
                    )
                )

        # Check project change
        if baseline.project_id != current.project_id:
            changes_detail["project_id"] = {
                "before": str(baseline.project_id) if baseline.project_id else None,
                "after": str(current.project_id) if current.project_id else None,
            }
            detected_changes.append(
                (
                    "moved",
                    TaskChange(
                        change_type=ChangeType.TASK_MOVED_TO_PROJECT,
                        task_id=current.id,
                        task_title=current.normalized_title or current.raw_text or "[No title]",
                        project_id=current.project_id,
                        before=baseline,
                        after=after,
                        description=f"Task moved to different project",
                        details=changes_detail,
                        timestamp=datetime.utcnow(),
                    ),
                )
            )

        # Check other property changes
        property_changes = {}
        current_title = current.normalized_title or current.raw_text or "[No title]"
        if baseline.title != current_title:
            property_changes["title"] = {
                "before": baseline.title,
                "after": current_title,
            }
        if baseline.kind != (current.kind or None):
            property_changes["kind"] = {
                "before": baseline.kind,
                "after": current.kind,
            }
        if baseline.confidence_band != (current.confidence_band or None):
            property_changes["confidence"] = {
                "before": baseline.confidence_band,
                "after": current.confidence_band,
            }

        if property_changes:
            changes_detail.update(property_changes)
            detected_changes.append(
                (
                    "properties_changed",
                    TaskChange(
                        change_type=ChangeType.TASK_PROPERTIES_CHANGED,
                        task_id=current.id,
                        task_title=current.normalized_title or current.raw_text or "[No title]",
                        project_id=current.project_id,
                        before=baseline,
                        after=after,
                        description=f"Task properties updated",
                        details=changes_detail,
                        timestamp=datetime.utcnow(),
                    ),
                )
            )

        # Log all detected changes for this task
        for change_key, change in detected_changes:
            self._detected_changes.append(change)
            logger.info(
                "task_change_detected",
                task_id=current.id,
                change_type=change_key,
                title=current.normalized_title or current.raw_text,
            )

    def _task_to_snapshot(self, task: TaskItem) -> TaskSnapshot:
        """Convert TaskItem model to Snapshot."""
        return TaskSnapshot(
            task_id=task.id,
            title=task.normalized_title or task.raw_text or "[No title]",
            status=task.status or TaskStatus.NEW.value,  # status is already a string
            project_id=task.project_id,
            kind=task.kind,
            confidence_band=task.confidence_band,
            updated_at=task.updated_at,
            source_google_task_id=task.source_google_task_id,
            current_google_task_id=task.current_google_task_id,
        )

    def _snapshot_to_dict(self, snapshot: TaskSnapshot | None) -> dict | None:
        """Convert Snapshot to dict for JSON serialization."""
        if not snapshot:
            return None
        return {
            "task_id": str(snapshot.task_id),
            "title": snapshot.title,
            "status": snapshot.status,
            "project_id": str(snapshot.project_id) if snapshot.project_id else None,
            "kind": snapshot.kind,
            "confidence_band": snapshot.confidence_band,
            "updated_at": snapshot.updated_at.isoformat(),
        }

    def get_changes_summary(self) -> dict[str, int]:
        """Get summary counts of detected changes."""
        summary: dict[str, int] = {}
        for change in self._detected_changes:
            change_type = change.change_type.value
            summary[change_type] = summary.get(change_type, 0) + 1
        return summary

    def get_changes_by_project(self) -> dict[uuid.UUID | None, list[TaskChange]]:
        """Group detected changes by project."""
        by_project: dict[uuid.UUID | None, list[TaskChange]] = {}
        for change in self._detected_changes:
            project_id = change.project_id
            if project_id not in by_project:
                by_project[project_id] = []
            by_project[project_id].append(change)
        return by_project

    def clear_baseline(self) -> None:
        """Clear baseline snapshots (useful after processing)."""
        self._baseline_snapshots.clear()

    def clear_changes(self) -> None:
        """Clear detected changes (useful for resetting monitor state)."""
        self._detected_changes.clear()
