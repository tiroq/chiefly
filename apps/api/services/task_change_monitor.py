"""
Task Change Monitor - detects and tracks all changes to tasks during pull operations.
Monitors both default tasklist sync and project sync operations for comprehensive change awareness.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.system_event_service import SystemEventService
from core.domain import notes_codec
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot as DbTaskSnapshot
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class ChangeType(str, Enum):
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_MOVED_TO_PROJECT = "task_moved_to_project"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_PROPERTIES_CHANGED = "task_properties_changed"
    TASK_MARKED_COMPLETED = "task_marked_completed"
    PROJECT_UPDATED = "project_updated"


@dataclass
class TaskStateCapture:
    stable_id: uuid.UUID
    title: str
    processing_status: str
    project_id: uuid.UUID | None
    kind: str | None
    confidence_band: str | None
    updated_at: datetime
    current_tasklist_id: str | None
    current_task_id: str | None


@dataclass
class TaskChange:
    change_type: ChangeType
    task_id: uuid.UUID
    task_title: str
    project_id: uuid.UUID | None
    before: TaskStateCapture | None
    after: TaskStateCapture | None
    description: str
    details: dict[str, Any]
    timestamp: datetime


class TaskChangeMonitor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._event_repo = SystemEventRepo(session)
        self._event_service = SystemEventService(self._event_repo)
        self._baseline_captures: dict[uuid.UUID, TaskStateCapture] = {}
        self._detected_changes: list[TaskChange] = []

    async def _load_records_with_snapshots(
        self,
    ) -> list[tuple[TaskRecord, DbTaskSnapshot | None]]:
        stmt = (
            select(TaskRecord, DbTaskSnapshot)
            .outerjoin(
                DbTaskSnapshot,
                (DbTaskSnapshot.stable_id == TaskRecord.stable_id)
                & (DbTaskSnapshot.is_latest == True),  # noqa: E712
            )
            .order_by(TaskRecord.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def capture_baseline(self) -> None:
        rows = await self._load_records_with_snapshots()
        self._baseline_captures = {}
        for record, snapshot in rows:
            capture = self._record_to_capture(record, snapshot)
            self._baseline_captures[record.stable_id] = capture
        logger.info("baseline_captured", task_count=len(self._baseline_captures))

    async def detect_changes(self) -> list[TaskChange]:
        self._detected_changes = []
        current_rows = await self._load_records_with_snapshots()

        current_by_id: dict[uuid.UUID, tuple[TaskRecord, DbTaskSnapshot | None]] = {
            record.stable_id: (record, snapshot) for record, snapshot in current_rows
        }

        for stable_id, (record, snapshot) in current_by_id.items():
            if stable_id not in self._baseline_captures:
                await self._handle_task_created(record, snapshot)
            else:
                baseline = self._baseline_captures[stable_id]
                await self._handle_task_updated(baseline, record, snapshot)

        for stable_id, baseline in self._baseline_captures.items():
            if stable_id not in current_by_id:
                await self._handle_task_removed(baseline)

        logger.info("changes_detected", count=len(self._detected_changes))
        return self._detected_changes

    async def log_all_changes(self) -> None:
        for change in self._detected_changes:
            await self._event_service.log_event(
                session=self._session,
                event_type=change.change_type.value,
                severity="info",
                subsystem="task_monitor",
                message=change.description,
                stable_id=change.task_id,
                project_id=change.project_id,
                payload={
                    "change_type": change.change_type.value,
                    "details": change.details,
                    "before": self._capture_to_dict(change.before) if change.before else None,
                    "after": self._capture_to_dict(change.after) if change.after else None,
                },
            )

    async def _handle_task_created(
        self, record: TaskRecord, snapshot: DbTaskSnapshot | None
    ) -> None:
        after = self._record_to_capture(record, snapshot)
        title = after.title
        change = TaskChange(
            change_type=ChangeType.TASK_CREATED,
            task_id=record.stable_id,
            task_title=title,
            project_id=after.project_id,
            before=None,
            after=after,
            description=f"Task created: {title}",
            details={
                "title": title,
                "project_id": str(after.project_id) if after.project_id else None,
                "kind": after.kind,
                "status": after.processing_status,
            },
            timestamp=datetime.now(timezone.utc),
        )
        self._detected_changes.append(change)
        logger.info(
            "task_created_detected",
            stable_id=record.stable_id,
            title=title,
            project_id=after.project_id,
        )

    async def _handle_task_removed(self, baseline: TaskStateCapture) -> None:
        change = TaskChange(
            change_type=ChangeType.TASK_CREATED,
            task_id=baseline.stable_id,
            task_title=baseline.title,
            project_id=baseline.project_id,
            before=baseline,
            after=None,
            description=f"Task removed: {baseline.title}",
            details={
                "title": baseline.title,
                "project_id": str(baseline.project_id) if baseline.project_id else None,
                "was_status": baseline.processing_status,
            },
            timestamp=datetime.now(timezone.utc),
        )
        self._detected_changes.append(change)
        logger.info(
            "task_removed_detected",
            stable_id=baseline.stable_id,
            title=baseline.title,
        )

    async def _handle_task_updated(
        self,
        baseline: TaskStateCapture,
        record: TaskRecord,
        snapshot: DbTaskSnapshot | None,
    ) -> None:
        after = self._record_to_capture(record, snapshot)
        changes_detail: dict[str, Any] = {}
        detected_changes: list[tuple[str, TaskChange]] = []
        title = after.title

        if baseline.processing_status != after.processing_status:
            changes_detail["status"] = {
                "before": baseline.processing_status,
                "after": after.processing_status,
            }
            detected_changes.append(
                (
                    "status_changed",
                    TaskChange(
                        change_type=ChangeType.TASK_STATUS_CHANGED,
                        task_id=record.stable_id,
                        task_title=title,
                        project_id=after.project_id,
                        before=baseline,
                        after=after,
                        description=f"Task status changed: {baseline.processing_status} → {after.processing_status}",
                        details=changes_detail,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            )

        if baseline.project_id != after.project_id:
            changes_detail["project_id"] = {
                "before": str(baseline.project_id) if baseline.project_id else None,
                "after": str(after.project_id) if after.project_id else None,
            }
            detected_changes.append(
                (
                    "moved",
                    TaskChange(
                        change_type=ChangeType.TASK_MOVED_TO_PROJECT,
                        task_id=record.stable_id,
                        task_title=title,
                        project_id=after.project_id,
                        before=baseline,
                        after=after,
                        description="Task moved to different project",
                        details=changes_detail,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            )

        property_changes: dict[str, Any] = {}
        if baseline.title != title:
            property_changes["title"] = {"before": baseline.title, "after": title}
        if baseline.kind != after.kind:
            property_changes["kind"] = {"before": baseline.kind, "after": after.kind}
        if baseline.confidence_band != after.confidence_band:
            property_changes["confidence"] = {
                "before": baseline.confidence_band,
                "after": after.confidence_band,
            }

        if property_changes:
            changes_detail.update(property_changes)
            detected_changes.append(
                (
                    "properties_changed",
                    TaskChange(
                        change_type=ChangeType.TASK_PROPERTIES_CHANGED,
                        task_id=record.stable_id,
                        task_title=title,
                        project_id=after.project_id,
                        before=baseline,
                        after=after,
                        description="Task properties updated",
                        details=changes_detail,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            )

        for change_key, change in detected_changes:
            self._detected_changes.append(change)
            logger.info(
                "task_change_detected",
                stable_id=record.stable_id,
                change_type=change_key,
                title=title,
            )

    def _record_to_capture(
        self, record: TaskRecord, snapshot: DbTaskSnapshot | None
    ) -> TaskStateCapture:
        payload = snapshot.payload if snapshot and snapshot.payload else {}
        notes_text = payload.get("notes", "")
        meta = notes_codec.parse(notes_text) or {}

        title = payload.get("title", "")
        if not title:
            title = "[No title]"

        project_id: uuid.UUID | None = None
        pid_str = meta.get("project_id")
        if pid_str:
            try:
                project_id = uuid.UUID(str(pid_str))
            except ValueError:
                pass

        return TaskStateCapture(
            stable_id=record.stable_id,
            title=title,
            processing_status=record.processing_status or "pending",
            project_id=project_id,
            kind=meta.get("kind") or payload.get("kind"),
            confidence_band=meta.get("confidence"),
            updated_at=record.updated_at,
            current_tasklist_id=record.current_tasklist_id,
            current_task_id=record.current_task_id,
        )

    def _capture_to_dict(self, capture: TaskStateCapture | None) -> dict[str, Any] | None:
        if not capture:
            return None
        return {
            "stable_id": str(capture.stable_id),
            "title": capture.title,
            "processing_status": capture.processing_status,
            "project_id": str(capture.project_id) if capture.project_id else None,
            "kind": capture.kind,
            "confidence_band": capture.confidence_band,
            "updated_at": capture.updated_at.isoformat(),
        }

    def get_changes_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for change in self._detected_changes:
            change_type = change.change_type.value
            summary[change_type] = summary.get(change_type, 0) + 1
        return summary

    def get_changes_by_project(self) -> dict[uuid.UUID | None, list[TaskChange]]:
        by_project: dict[uuid.UUID | None, list[TaskChange]] = {}
        for change in self._detected_changes:
            project_id = change.project_id
            if project_id not in by_project:
                by_project[project_id] = []
            by_project[project_id].append(change)
        return by_project

    def clear_baseline(self) -> None:
        self._baseline_captures.clear()

    def clear_changes(self) -> None:
        self._detected_changes.clear()
