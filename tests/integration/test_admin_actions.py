import uuid
from collections.abc import Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from core.domain.enums import ConfidenceBand, TaskKind, WorkflowStatus
from core.schemas.llm import TaskClassificationResult
from db.models.task_record import TaskRecord


TASK_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
MISSING_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _make_record(
    stable_id: uuid.UUID = TASK_ID,
    processing_status: str = WorkflowStatus.FAILED.value,
) -> MagicMock:
    record = MagicMock(spec=TaskRecord)
    record.stable_id = stable_id
    record.processing_status = processing_status
    return record


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
    auth_dep_raw = router.dependencies[0].dependency
    assert auth_dep_raw is not None
    auth_dep = cast(Callable[..., Any], auth_dep_raw)

    async def _no_auth() -> None:
        pass

    app.dependency_overrides[auth_dep] = _no_auth

    return app, TestClient(app)


# ---------------------------------------------------------------------------
# RETRY
# ---------------------------------------------------------------------------


class TestRetryTask:
    def test_retry_task_success(self):
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        record = _make_record(processing_status=WorkflowStatus.FAILED.value)

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = record
            mock_repo.update_processing_status = AsyncMock()
            MockRecordRepo.return_value = mock_repo

            mock_event_svc = AsyncMock()
            MockEventSvc.return_value = mock_event_svc

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/retry")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Task queued for retry"

            mock_repo.update_processing_status.assert_called_once()
            mock_event_svc.log_admin_action.assert_called_once()

    def test_retry_task_invalid_state(self):
        mock_session = AsyncMock()

        record = _make_record(processing_status=WorkflowStatus.PENDING.value)

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = record
            MockRecordRepo.return_value = mock_repo

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/retry")

            assert response.status_code == 400
            data = response.json()
            assert "error" in data or "detail" in data

    def test_retry_task_not_found(self):
        """Non-existent UUID -> POST retry -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = None
            MockRecordRepo.return_value = mock_repo

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/retry")

            assert response.status_code == 404


# ---------------------------------------------------------------------------
# RECLASSIFY
# ---------------------------------------------------------------------------


class TestReclassifyTask:
    def test_reclassify_task_success(self):
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        record = _make_record(processing_status=WorkflowStatus.AWAITING_REVIEW.value)
        mock_snapshot = MagicMock()
        mock_snapshot.payload = {"title": "Fix deployment pipeline"}

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
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.TaskSnapshotRepository") as MockSnapshotRepo,
            patch("apps.api.routes.admin_api.ProjectRepository") as MockProjRepo,
            patch("apps.api.routes.admin_api.ClassificationService") as MockClassSvc,
            patch("apps.api.routes.admin_api.RevisionService") as MockRevSvc,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
            patch("apps.api.routes.admin_api.LLMService"),
            patch("apps.api.routes.admin_api.ProjectRoutingService"),
            patch("apps.api.routes.admin_api.ProjectAliasRepo"),
            patch(
                "apps.api.routes.admin_api.get_effective_llm_config",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    provider="openai",
                    model="gpt-4o-mini",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                    fast_model="",
                    quality_model="",
                    fallback_model="",
                    auto_mode=False,
                ),
            ),
            patch(
                "apps.api.routes.admin_api.settings",
                new=MagicMock(
                    llm_provider="openai",
                    llm_model="gpt-4o-mini",
                    llm_api_key="test-key",
                    llm_base_url="https://example.test/v1",
                ),
            ),
            patch("apps.api.routes.admin_api.get_settings"),
        ):
            mock_record_repo = AsyncMock()
            mock_record_repo.get_by_stable_id.return_value = record
            mock_record_repo.update_processing_status = AsyncMock()
            MockRecordRepo.return_value = mock_record_repo

            mock_snapshot_repo = AsyncMock()
            mock_snapshot_repo.get_latest_by_stable_id.return_value = mock_snapshot
            MockSnapshotRepo.return_value = mock_snapshot_repo

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

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/reclassify")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            mock_class_svc.classify.assert_called_once()
            mock_rev_svc.create_classification_revision.assert_called_once()
            rev_kwargs = mock_rev_svc.create_classification_revision.call_args.kwargs
            assert rev_kwargs["stable_id"] == TASK_ID

            mock_record_repo.update_processing_status.assert_called_once_with(
                TASK_ID,
                WorkflowStatus.PENDING,
            )
            mock_event_svc.log_admin_action.assert_called_once()

    def test_reclassify_task_not_found(self):
        """Non-existent UUID -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = None
            MockRecordRepo.return_value = mock_repo

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/reclassify")

            assert response.status_code == 404


# ---------------------------------------------------------------------------
# RESEND
# ---------------------------------------------------------------------------


class TestResendProposal:
    def test_resend_proposal_success(self):
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        record = _make_record(processing_status=WorkflowStatus.APPLIED.value)
        mock_snapshot = MagicMock()
        mock_snapshot.payload = {"title": "Fix deployment pipeline", "notes": ""}

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.TaskSnapshotRepository") as MockSnapshotRepo,
            patch("apps.api.routes.admin_api.TaskRevisionRepository") as MockRevRepo,
            patch("apps.api.routes.admin_api.TelegramService") as MockTgSvc,
            patch("apps.api.routes.admin_api.SystemEventService") as MockEventSvc,
            patch("apps.api.routes.admin_api.SystemEventRepo"),
            patch(
                "apps.api.routes.admin_api.settings",
                new=MagicMock(
                    telegram_bot_token="bot-token",
                    telegram_chat_id="12345",
                ),
            ),
            patch("apps.api.routes.admin_api.get_settings"),
        ):
            mock_record_repo = AsyncMock()
            mock_record_repo.get_by_stable_id.return_value = record
            MockRecordRepo.return_value = mock_record_repo

            mock_snapshot_repo = AsyncMock()
            mock_snapshot_repo.get_latest_by_stable_id.return_value = mock_snapshot
            MockSnapshotRepo.return_value = mock_snapshot_repo

            mock_rev_repo = AsyncMock()
            mock_revision = MagicMock()
            mock_revision.proposal_json = {
                "kind": "task",
                "normalized_title": "Fix deployment pipeline",
            }
            mock_rev_repo.list_by_stable_id.return_value = [mock_revision]
            MockRevRepo.return_value = mock_rev_repo

            mock_tg_svc = AsyncMock()
            mock_tg_svc.send_proposal.return_value = 42
            mock_tg_svc.aclose = AsyncMock()
            MockTgSvc.return_value = mock_tg_svc

            mock_event_svc = AsyncMock()
            MockEventSvc.return_value = mock_event_svc

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/resend")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            mock_tg_svc.send_proposal.assert_called_once()
            mock_tg_svc.aclose.assert_called_once()

            mock_event_svc.log_admin_action.assert_called_once()

    def test_resend_proposal_not_found(self):
        """Non-existent UUID -> 404."""
        mock_session = AsyncMock()

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = None
            MockRecordRepo.return_value = mock_repo

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{MISSING_ID}/resend")

            assert response.status_code == 404

    def test_resend_proposal_not_classified(self):
        mock_session = AsyncMock()

        record = _make_record(processing_status=WorkflowStatus.PENDING.value)

        with (
            patch("apps.api.routes.admin_api.TaskRecordRepository") as MockRecordRepo,
            patch("apps.api.routes.admin_api.SystemEventService"),
            patch("apps.api.routes.admin_api.SystemEventRepo"),
        ):
            mock_repo = AsyncMock()
            mock_repo.get_by_stable_id.return_value = record
            MockRecordRepo.return_value = mock_repo

            _, client = _create_app_and_client(mock_session)

            response = client.post(f"/tasks/{TASK_ID}/resend")

            assert response.status_code == 400
            data = response.json()
            assert "error" in data or "detail" in data
