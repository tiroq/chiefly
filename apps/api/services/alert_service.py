"""
Alert Service - sends notifications about task changes to users.
Handles Telegram notifications, UI updates, and alert aggregation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.task_change_monitor import ChangeType, TaskChange
from apps.api.services.telegram_service import TelegramService
from db.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)


class AlertService:
    """Handles notifications and alerts for task changes."""

    def __init__(
        self,
        telegram: TelegramService,
        session: AsyncSession,
    ) -> None:
        """Initialize with dependencies."""
        self._telegram = telegram
        self._session = session
        self._project_repo = ProjectRepository(session)

    async def alert_task_changes(
        self,
        changes: list[TaskChange],
        operation: str = "pull",
    ) -> dict[str, Any]:
        """
        Send alerts for all detected task changes.

        Args:
            changes: List of detected TaskChange objects
            operation: Type of operation that triggered changes ("inbox_poll", "project_sync", etc.)

        Returns:
            Alert summary with counts and status
        """
        if not changes:
            logger.info("no_changes_to_alert")
            return {
                "sent": False,
                "changes_count": 0,
                "reason": "no_changes_detected",
            }

        summary = self._summarize_changes(changes)
        alert_message = self._format_changes_message(changes, summary, operation)

        try:
            await self._telegram.send_text(alert_message)
            logger.info(
                "task_changes_alert_sent",
                operation=operation,
                changes_count=len(changes),
                summary=summary,
            )
            return {
                "sent": True,
                "changes_count": len(changes),
                "summary": summary,
                "message_sent_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(
                "task_changes_alert_failed",
                error=str(e),
                operation=operation,
                changes_count=len(changes),
            )
            return {
                "sent": False,
                "changes_count": len(changes),
                "error": str(e),
            }

    async def alert_task_created(self, change: TaskChange) -> bool:
        """Send alert for a single task creation."""
        message = self._format_single_task_alert(change, "📝 Task Created")
        try:
            await self._telegram.send_text(message)
            logger.info("task_created_alert_sent", task_id=change.task_id)
            return True
        except Exception as e:
            logger.error("task_created_alert_failed", error=str(e), task_id=change.task_id)
            return False

    async def alert_task_updated(self, change: TaskChange) -> bool:
        """Send alert for a task update."""
        emoji = "✏️"
        if change.change_type == ChangeType.TASK_MARKED_COMPLETED:
            emoji = "✅"
        elif change.change_type == ChangeType.TASK_MOVED_TO_PROJECT:
            emoji = "📤"
        elif change.change_type == ChangeType.TASK_STATUS_CHANGED:
            emoji = "🔄"

        message = self._format_single_task_alert(change, f"{emoji} Task Updated")
        try:
            await self._telegram.send_text(message)
            logger.info("task_updated_alert_sent", task_id=change.task_id)
            return True
        except Exception as e:
            logger.error("task_updated_alert_failed", error=str(e), task_id=change.task_id)
            return False

    def _summarize_changes(self, changes: list[TaskChange]) -> dict[str, int]:
        """Create summary counts of change types."""
        summary: dict[str, int] = {}
        for change in changes:
            change_type = change.change_type.value
            summary[change_type] = summary.get(change_type, 0) + 1
        return summary

    def _format_changes_message(
        self,
        changes: list[TaskChange],
        summary: dict[str, int],
        operation: str,
    ) -> str:
        """Format alert message for multiple changes."""
        lines = [
            "🔔 <b>Task Changes Detected</b>",
            f"<i>From {operation} operation</i>",
            "",
        ]

        # Add summary counts
        emoji_map = {
            "task_created": "📝",
            "task_updated": "✏️",
            "task_moved_to_project": "📤",
            "task_status_changed": "🔄",
            "task_marked_completed": "✅",
            "task_properties_changed": "⚙️",
        }

        for change_type, count in summary.items():
            emoji = emoji_map.get(change_type, "•")
            formatted_type = change_type.replace("_", " ").title()
            lines.append(f"{emoji} {formatted_type}: {count}")

        lines.append(f"")
        lines.append(f"📊 <b>Total Changes: {len(changes)}</b>")
        lines.append(f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Add first 3 changes as examples
        if changes:
            lines.append("")
            lines.append("<b>Recent items:</b>")
            for i, change in enumerate(changes[:3], 1):
                emoji = emoji_map.get(change.change_type.value, "•")
                title_preview = (change.task_title[:50] + "...") if len(change.task_title) > 50 else change.task_title
                lines.append(f"{emoji} {i}. {title_preview}")

            if len(changes) > 3:
                lines.append(f"… and {len(changes) - 3} more")

        return "\n".join(lines)

    def _format_single_task_alert(self, change: TaskChange, header: str) -> str:
        """Format alert message for a single task change."""
        lines = [
            f"<b>{header}</b>",
            f"<code>{change.task_title}</code>",
            "",
        ]

        # Add details
        if "project_id" in change.details:
            project_change = change.details["project_id"]
            lines.append(f"<b>Project:</b> Changed")

        if "status" in change.details:
            status_change = change.details["status"]
            lines.append(
                f"<b>Status:</b> {status_change['before']} → {status_change['after']}"
            )

        if "title" in change.details:
            title_change = change.details["title"]
            lines.append(f"<b>Title Updated</b>")

        if "kind" in change.details:
            kind_change = change.details["kind"]
            if kind_change["before"] or kind_change["after"]:
                lines.append(f"<b>Kind:</b> {kind_change['after'] or 'Not set'}")

        lines.append(f"")
        lines.append(f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

        return "\n".join(lines)

    def get_alert_template_for_project(
        self,
        project_id: uuid.UUID | None,
        changes: list[TaskChange],
    ) -> str:
        """Get formatted alert template for changes in a specific project."""
        if not changes:
            return ""

        response_lines = [
            f"📌 <b>Changes in Project</b>",
            "",
        ]

        for i, change in enumerate(changes, 1):
            emoji_map = {
                "task_created": "➕",
                "task_updated": "✏️",
                "task_moved_to_project": "📤",
                "task_status_changed": "🔄",
                "task_marked_completed": "✅",
            }
            emoji = emoji_map.get(change.change_type.value, "•")
            response_lines.append(f"{emoji} {i}. {change.description}")

        return "\n".join(response_lines)
