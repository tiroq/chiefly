from __future__ import annotations

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportAny=false

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.miniapp_review_service import MiniAppReviewService


def _execute_result_with_sessions(sessions):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = sessions
    result.scalars.return_value = scalars
    return result


class TestMiniAppReviewServiceQueue:
    @patch("apps.api.services.miniapp_review_service.TaskSnapshotRepository")
    @pytest.mark.asyncio
    async def test_get_queue_items_returns_shape_and_counts(self, mock_snapshot_repo_cls):
        stable_id = uuid.uuid4()
        sessions = [
            SimpleNamespace(
                stable_id=stable_id,
                status="queued",
                proposed_changes={"normalized_title": "Buy milk", "kind": "task"},
                created_at=datetime.now(timezone.utc),
            ),
            SimpleNamespace(
                stable_id=uuid.uuid4(),
                status="pending",
                proposed_changes={"normalized_title": "Plan", "kind": "idea"},
                created_at=datetime.now(timezone.utc),
            ),
        ]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_execute_result_with_sessions(sessions))
        snapshot_repo = mock_snapshot_repo_cls.return_value
        snapshot_repo.get_latest_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(payload={"title": "Raw input"})
        )
        service = MiniAppReviewService(session)

        items, counts = await service.get_queue_items()

        assert counts == {"total": 2, "queued": 1, "pending": 1}
        assert items[0]["stable_id"] == stable_id
        assert items[0]["raw_text"] == "Raw input"
        assert items[0]["normalized_title"] == "Buy milk"

    @patch("apps.api.services.miniapp_review_service.TaskSnapshotRepository")
    @pytest.mark.asyncio
    async def test_get_queue_items_filters_status(self, mock_snapshot_repo_cls):
        sessions = [
            SimpleNamespace(
                stable_id=uuid.uuid4(),
                status="queued",
                proposed_changes={"normalized_title": "A", "kind": "task"},
                created_at=datetime.now(timezone.utc),
            ),
            SimpleNamespace(
                stable_id=uuid.uuid4(),
                status="pending",
                proposed_changes={"normalized_title": "B", "kind": "task"},
                created_at=datetime.now(timezone.utc),
            ),
        ]
        session = MagicMock()
        session.execute = AsyncMock(return_value=_execute_result_with_sessions(sessions))
        mock_snapshot_repo_cls.return_value.get_latest_by_stable_id = AsyncMock(return_value=None)
        service = MiniAppReviewService(session)

        items, _ = await service.get_queue_items(status_filter="queued")

        assert len(items) == 1
        assert items[0]["normalized_title"] == "A"


class TestMiniAppReviewServiceActions:
    @patch.object(MiniAppReviewService, "update_telegram_message", new_callable=AsyncMock)
    @patch("apps.api.services.miniapp_review_service.utcnow")
    @patch("apps.api.services.miniapp_review_service.get_settings")
    @patch("apps.api.services.miniapp_review_service.GoogleTasksService")
    @patch("apps.api.services.miniapp_review_service.ProjectRepository")
    @patch("apps.api.services.miniapp_review_service.TaskRevisionRepository")
    @patch("apps.api.services.miniapp_review_service.TaskRecordRepository")
    @patch("apps.api.services.miniapp_review_service.ReviewSessionRepository")
    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_confirm_task_creates_miniapp_revision(
        self,
        mock_get_review_session,
        mock_session_repo_cls,
        mock_record_repo_cls,
        mock_revision_repo_cls,
        mock_project_repo_cls,
        mock_gtasks_cls,
        mock_get_settings,
        mock_utcnow,
        _mock_update_message,
    ):
        stable_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        mock_utcnow.return_value = now
        review_session = SimpleNamespace(
            stable_id=stable_id,
            proposed_changes={"normalized_title": "New title", "kind": "task"},
            status="queued",
            resolved_at=None,
            telegram_message_id=None,
        )
        mock_get_review_session.return_value = review_session

        record_repo = mock_record_repo_cls.return_value
        record_repo.get_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                current_tasklist_id="list-1",
                current_task_id="task-1",
            )
        )
        record_repo.update_pointer = AsyncMock()
        record_repo.update_processing_status = AsyncMock()

        revision_repo = mock_revision_repo_cls.return_value
        revision_repo.get_next_revision_no_by_stable_id = AsyncMock(return_value=7)
        revision_repo.create = AsyncMock()

        mock_project_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
        mock_get_settings.return_value = SimpleNamespace(google_credentials_file="/tmp/creds.json")

        google_task = SimpleNamespace(
            id="task-1",
            tasklist_id="list-1",
            title="Old title",
            notes="",
            status="needsAction",
            due=None,
            updated="2026-01-01T00:00:00Z",
            raw_payload=None,
        )
        gtasks = mock_gtasks_cls.return_value
        gtasks.get_task.side_effect = [google_task, google_task]
        gtasks.patch_task = MagicMock()

        session_repo = mock_session_repo_cls.return_value
        session_repo.save = AsyncMock()
        session = MagicMock()
        session.commit = AsyncMock()

        service = MiniAppReviewService(session)
        result = await service.confirm_task(stable_id)

        assert result["success"] is True
        assert result["message"] == "Task confirmed"
        assert revision_repo.create.await_args is not None
        revision = revision_repo.create.await_args.args[0]
        assert revision.actor_id == "miniapp"
        assert revision.action == "confirm"

    @patch.object(MiniAppReviewService, "update_telegram_message", new_callable=AsyncMock)
    @patch("apps.api.services.miniapp_review_service.utcnow")
    @patch("apps.api.services.miniapp_review_service.TaskRevisionRepository")
    @patch("apps.api.services.miniapp_review_service.TaskRecordRepository")
    @patch("apps.api.services.miniapp_review_service.ReviewSessionRepository")
    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_discard_task_creates_miniapp_revision(
        self,
        mock_get_review_session,
        mock_session_repo_cls,
        mock_record_repo_cls,
        mock_revision_repo_cls,
        mock_utcnow,
        _mock_update_message,
    ):
        stable_id = uuid.uuid4()
        mock_utcnow.return_value = datetime.now(timezone.utc)
        mock_get_review_session.return_value = SimpleNamespace(
            stable_id=stable_id,
            proposed_changes={"normalized_title": "Discard me", "kind": "task"},
            status="pending",
            resolved_at=None,
            telegram_message_id=None,
        )

        revision_repo = mock_revision_repo_cls.return_value
        revision_repo.get_next_revision_no_by_stable_id = AsyncMock(return_value=2)
        revision_repo.create = AsyncMock()
        mock_record_repo_cls.return_value.update_processing_status = AsyncMock()
        mock_session_repo_cls.return_value.save = AsyncMock()

        session = MagicMock()
        session.commit = AsyncMock()
        service = MiniAppReviewService(session)

        result = await service.discard_task(stable_id)

        assert result == {"success": True, "message": "Task discarded"}
        assert revision_repo.create.await_args is not None
        revision = revision_repo.create.await_args.args[0]
        assert revision.actor_id == "miniapp"
        assert revision.action == "discard"


class TestMiniAppReviewServiceEdits:
    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_edit_title_updates_proposed_changes(self, mock_get_review_session):
        stable_id = uuid.uuid4()
        review_session = SimpleNamespace(
            proposed_changes={"normalized_title": "Old title", "kind": "task"}
        )
        mock_get_review_session.return_value = review_session
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        service = MiniAppReviewService(session)

        result = await service.edit_title(stable_id, "  New title  ")

        assert result["success"] is True
        proposed = result.get("proposed_changes")
        assert isinstance(proposed, dict)
        assert proposed["normalized_title"] == "New title"

    @patch("apps.api.services.miniapp_review_service.ProjectRepository")
    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_change_project_updates_proposed_changes(
        self,
        mock_get_review_session,
        mock_project_repo_cls,
    ):
        project_id = uuid.uuid4()
        review_session = SimpleNamespace(proposed_changes={"normalized_title": "Task"})
        mock_get_review_session.return_value = review_session
        mock_project_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=SimpleNamespace(id=project_id, name="Work")
        )
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        service = MiniAppReviewService(session)

        result = await service.change_project(uuid.uuid4(), str(project_id))

        assert result["success"] is True
        proposed = result.get("proposed_changes")
        assert isinstance(proposed, dict)
        assert proposed["project_id"] == str(project_id)
        assert proposed["project_name"] == "Work"

    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_change_type_rejects_invalid_kind(self, mock_get_review_session):
        mock_get_review_session.return_value = SimpleNamespace(proposed_changes={"kind": "task"})
        session = MagicMock()
        service = MiniAppReviewService(session)

        result = await service.change_type(uuid.uuid4(), "not-a-kind")

        assert result == {"success": False, "message": "Invalid task kind"}

    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_resolve_ambiguity_selects_option(self, mock_get_review_session):
        review_session = SimpleNamespace(
            proposed_changes={
                "normalized_title": "Original",
                "kind": "task",
                "disambiguation_options": [
                    {"kind": "idea", "title": "Build startup"},
                    {"kind": "task", "title": "Buy milk"},
                ],
            }
        )
        mock_get_review_session.return_value = review_session
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        service = MiniAppReviewService(session)

        result = await service.resolve_ambiguity(uuid.uuid4(), 0)

        assert result["success"] is True
        proposed = result.get("proposed_changes")
        assert isinstance(proposed, dict)
        assert proposed["kind"] == "idea"
        assert proposed["normalized_title"] == "Build startup"
        assert proposed["ambiguities"] == []
        assert proposed["disambiguation_options"] == []

    @patch.object(MiniAppReviewService, "_get_review_session_for_action", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_resolve_ambiguity_clears_ambiguity_metadata(self, mock_get_review_session):
        review_session = SimpleNamespace(
            proposed_changes={
                "normalized_title": "Original",
                "kind": "task",
                "ambiguities": ["Could be a project or a task"],
                "disambiguation_options": [
                    {"kind": "idea", "title": "Build startup"},
                    {"kind": "task", "title": "Buy milk"},
                ],
            }
        )
        mock_get_review_session.return_value = review_session
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        service = MiniAppReviewService(session)

        result = await service.resolve_ambiguity(uuid.uuid4(), 1)

        assert result["success"] is True
        proposed = result.get("proposed_changes")
        assert isinstance(proposed, dict)
        assert proposed["kind"] == "task"
        assert proposed["normalized_title"] == "Buy milk"
        assert proposed["ambiguities"] == [], "Ambiguities should be cleared after resolution"
        assert proposed["disambiguation_options"] == [], (
            "Options should be cleared after resolution"
        )
