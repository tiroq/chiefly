"""
Integration tests for admin action API routes (retry, re-classify, re-send).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from core.domain.enums import ConfidenceBand, TaskKind, TaskStatus
from core.schemas.llm import TaskClassificationResult
from db.models.task_item import TaskItem


TASK_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
MISSING_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _make_task(
    task_id: uuid.UUID = TASK_ID,
    status: TaskStatus = TaskStatus.ERROR,
    raw_text: str = "Fix the deployment pipeline",
    kind: TaskKind | None = TaskKind.TASK,
    normalized_title: str | None = "Fix deployment pipeline",
    project_id: uuid.UUID | None = None,
    confidence_band: str | None = ConfidenceBand.HIGH,
) -> MagicMock:
    """Create a mock TaskItem."""
    task = MagicMock(spec=TaskItem)
    task.id = task_id
    task.status = status.value
    task.raw_text = raw_text
    task.kind = kind
    task.normalized_title = normalized_title
    task.project_id = project_id
    task.confidence_band = confidence_band
    task.source_google_task_id = "gtask-001"
    task.source_google_tasklist_id = "inbox-list"
    return task


def _create_app_and_client(
    mock_session: AsyncMock,
) -> tuple[FastAPI, TestClient]:
    """Create a minimal FastAPI app with admin_api router and overridden deps."""
    from apps.api.dependencies import get_session
    from apps.api.routes.admin_api import router

    app = FastAPI()
    app.include_router(router)

    # Override session dependency
    async def _override_session():
        yield mock_session

    app.dependency_overrides[get_session] = _override_session

    # Override the require_admin auth dependency (captured closure in router.dependencies)
    auth_dep = router.dependencies[0].dependency

    async def _no_auth() -> None:
        pass

    app.dependency_overrides[auth_dep] = _no_auth

    return app, TestClient(app)


# ---------------------------------------------------------------------------
# RETRY
# ---------------------------------------------------------------------------


class TestRetryTask:
    """Tests for POST /tasks/{task_id}/retry."""

    def test_retry_task_success(self):
        """Task in ERROR state -> POST retry -> status becomes NEW, system event created."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        task = _make_task(status=TaskStatus.ERROR)

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = task
            mock_repo.save.return_value = task
            MockTaskRepo.return_value = mock_repo

            mock_event_svc = AsyncMock()
            MockEventSvc.return_value = mock_event_svc

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/retry")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "retry" in data["message"].lower()

            # Verify task status was changed to NEW
            assert task.status == TaskStatus.NEW.value

            # Verify system event was logged
            mock_event_svc.log_admin_action.assert_called_once()
            call_args = mock_event_svc.log_admin_action.call_args
            assert "task_retried" in str(call_args)

    def test_retry_task_invalid_state(self):
        """Task in CONFIRMED state -> POST retry -> returns 400 error (not 500)."""
        mock_session = AsyncMock()

        task = _make_task(status=TaskStatus.CONFIRMED)

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = task
            MockTaskRepo.return_value = mock_repo

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/retry")

            assert response.status_code == 400
            data = response.json()
            assert "error" in data or "detail" in data

    def test_retry_task_not_found(self):
        """Non-existent UUID -> POST retry -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            MockTaskRepo.return_value = mock_repo

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/retry")

            assert response.status_code == 404


# ---------------------------------------------------------------------------
# RECLASSIFY
# ---------------------------------------------------------------------------


class TestReclassifyTask:
    """Tests for POST /tasks/{task_id}/reclassify."""

    def test_reclassify_task_success(self):
        """Task exists -> POST reclassify -> new revision created, system event created."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        task = _make_task(status=TaskStatus.PROPOSED)
        mock_project = MagicMock()
        mock_project.id = uuid.uuid4()
        mock_project.name = "Personal"

        classification = TaskClassificationResult(
            kind=TaskKind.TASK,
            normalized_title="Fix deployment pipeline",
            confidence=ConfidenceBand.HIGH,
            project_guess="Personal",
            project_confidence=ConfidenceBand.HIGH,
            next_action="Review CI config",
        )

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.ProjectRepository") as MockProjRepo,
            patch("apps.api.routes.admin_api.ClassificationService") as MockClassSvc,
            patch("apps.api.routes.admin_api.RevisionService") as MockRevSvc,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
            patch("apps.api.routes.admin_api.LLMService"),
            patch("apps.api.routes.admin_api.ProjectRoutingService"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = task
            mock_repo.save.return_value = task
            MockTaskRepo.return_value = mock_repo

            mock_proj_repo = AsyncMock()
            mock_proj_repo.list_active.return_value = [mock_project]
            MockProjRepo.return_value = mock_proj_repo

            mock_class_svc = AsyncMock()
            mock_class_svc.classify.return_value = (classification, mock_project)
            MockClassSvc.return_value = mock_class_svc

            mock_rev_svc = AsyncMock()
            MockRevSvc.return_value = mock_rev_svc

            mock_event_svc = AsyncMock()
            MockEventSvc.return_value = mock_event_svc

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/reclassify")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            # Verify classification was called
            mock_class_svc.classify.assert_called_once()

            # Verify revision was created
            mock_rev_svc.create_classification_revision.assert_called_once()

            # Verify system event was logged
            mock_event_svc.log_admin_action.assert_called_once()
            call_args = mock_event_svc.log_admin_action.call_args
            assert "task_reclassified" in str(call_args)

    def test_reclassify_task_not_found(self):
        """Non-existent UUID -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            MockTaskRepo.return_value = mock_repo

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/reclassify")

            assert response.status_code == 404


# ---------------------------------------------------------------------------
# RESEND
# ---------------------------------------------------------------------------


class TestResendProposal:
    """Tests for POST /tasks/{task_id}/resend."""

    def test_resend_proposal_success(self):
        """Classified task -> POST resend -> telegram send called, system event created."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        task = _make_task(status=TaskStatus.PROPOSED)
        mock_project = MagicMock()
        mock_project.id = task.project_id
        mock_project.name = "Personal"

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.ProjectRepository") as MockProjRepo,
            patch("apps.api.routes.admin_api.TelegramService") as MockTgSvc,
            patch("apps.api.routes.admin_api.TaskRevisionRepository") as MockRevRepo,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = task
            MockTaskRepo.return_value = mock_repo

            mock_proj_repo = AsyncMock()
            mock_proj_repo.get_by_id.return_value = mock_project
            MockProjRepo.return_value = mock_proj_repo

            mock_rev_repo = AsyncMock()
            mock_revision = MagicMock()
            mock_revision.proposal_json = {
                "kind": "task",
                "normalized_title": "Fix deployment pipeline",
                "confidence": "high",
            }
            mock_rev_repo.list_by_task.return_value = [mock_revision]
            MockRevRepo.return_value = mock_rev_repo

            mock_tg_svc = AsyncMock()
            mock_tg_svc.send_proposal.return_value = 42
            MockTgSvc.return_value = mock_tg_svc

            mock_event_svc = AsyncMock()
            MockEventSvc.return_value = mock_event_svc

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/resend")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            # Verify telegram send was called
            mock_tg_svc.send_proposal.assert_called_once()

            # Verify system event was logged
            mock_event_svc.log_admin_action.assert_called_once()
            call_args = mock_event_svc.log_admin_action.call_args
            assert "proposal_resent" in str(call_args)

    def test_resend_proposal_not_found(self):
        """Non-existent UUID -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            MockTaskRepo.return_value = mock_repo

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/resend")

            assert response.status_code == 404

    def test_resend_proposal_not_classified(self):
        """Task in NEW state (not classified) -> POST resend -> returns 400."""
        mock_session = AsyncMock()

        task = _make_task(status=TaskStatus.NEW)

        with (
            patch("apps.api.routes.admin_api.TaskItemRepository") as MockTaskRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = task
            MockTaskRepo.return_value = mock_repo

            app, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/resend")

            assert response.status_code == 400
            data = response.json()
            assert "error" in data or "detail" in data
