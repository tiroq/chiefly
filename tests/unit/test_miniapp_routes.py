from __future__ import annotations

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportAny=false

import uuid
from datetime import datetime, timezone
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from apps.api.miniapp.auth import verify_miniapp_auth
from apps.api.miniapp.routes import router as miniapp_router


@pytest.fixture
def test_app() -> FastAPI:
    from apps.api.dependencies import get_session

    app = FastAPI()
    app.include_router(miniapp_router)

    async def _override_auth() -> dict[str, str]:
        return {"user": '{"id":12345}'}

    async def _override_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        yield mock_session

    app.dependency_overrides[verify_miniapp_auth] = _override_auth
    app.dependency_overrides[get_session] = _override_session
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


def _queue_item(stable_id: uuid.UUID) -> dict[str, object]:
    return {
        "stable_id": stable_id,
        "raw_text": "raw",
        "normalized_title": "normalized",
        "project_name": "Personal",
        "kind": "task",
        "confidence": "high",
        "has_ambiguity": False,
        "created_at": datetime.now(timezone.utc),
    }


class TestMiniAppRoutes:
    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_get_review_queue(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service = mock_service_cls.return_value
        mock_service.get_queue_items = AsyncMock(
            return_value=(
                [
                    _queue_item(stable_id),
                ],
                {"total": 1, "active": 1, "queued": 0},
            )
        )

        resp = client.get("/api/app/review/queue")

        assert resp.status_code == 200
        body_obj = resp.json()
        assert isinstance(body_obj, dict)
        body = cast(dict[str, object], body_obj)
        assert body["total"] == 1
        items = cast(list[dict[str, object]], body["items"])
        assert items[0]["stable_id"] == str(stable_id)

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_get_review_detail(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service = mock_service_cls.return_value
        mock_service.get_review_detail = AsyncMock(
            return_value={
                "stable_id": stable_id,
                "raw_text": "raw",
                "normalized_title": "normalized",
                "kind": "task",
                "confidence": "high",
                "project_name": "Personal",
                "project_id": None,
                "next_action": None,
                "due_hint": None,
                "substeps": [],
                "ambiguities": [],
                "disambiguation_options": [],
                "telegram_message_id": None,
                "created_at": datetime.now(timezone.utc),
            }
        )

        resp = client.get(f"/api/app/review/{stable_id}")

        assert resp.status_code == 200
        assert resp.json()["stable_id"] == str(stable_id)

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_confirm_review_item(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.confirm_task = AsyncMock(
            return_value={"success": True, "message": "Task confirmed"}
        )

        resp = client.post(f"/api/app/review/{stable_id}/confirm")

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Task confirmed"}

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_discard_review_item(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.discard_task = AsyncMock(
            return_value={"success": True, "message": "Task discarded"}
        )

        resp = client.post(f"/api/app/review/{stable_id}/discard")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Task discarded"

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_edit_review_title(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.edit_title = AsyncMock(
            return_value={"success": True, "message": "Title updated"}
        )

        resp = client.post(
            f"/api/app/review/{stable_id}/edit-title",
            json={"title": "New title"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Title updated"

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_change_review_project(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.change_project = AsyncMock(
            return_value={"success": True, "message": "Project changed"}
        )

        resp = client.post(
            f"/api/app/review/{stable_id}/change-project",
            json={"project_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_change_review_type(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.change_type = AsyncMock(
            return_value={"success": True, "message": "Type changed"}
        )

        resp = client.post(
            f"/api/app/review/{stable_id}/change-type",
            json={"kind": "idea"},
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("apps.api.miniapp.routes.MiniAppReviewService")
    def test_clarify_review_item(self, mock_service_cls, client: TestClient):
        stable_id = uuid.uuid4()
        mock_service_cls.return_value.resolve_ambiguity = AsyncMock(
            return_value={"success": True, "message": "Updated"}
        )

        resp = client.post(
            f"/api/app/review/{stable_id}/clarify",
            json={"option_index": 1},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Updated"

    @patch("apps.api.miniapp.routes.get_user_settings", new_callable=AsyncMock)
    def test_get_settings_endpoint(self, mock_get_user_settings, client: TestClient):
        mock_get_user_settings.return_value = {
            "auto_next": True,
            "batch_size": 5,
            "paused": False,
            "sync_summary": True,
            "daily_brief": True,
            "show_confidence": True,
            "show_raw_input": True,
            "draft_suggestions": True,
            "ambiguity_prompts": True,
            "show_steps_auto": False,
            "changes_only": False,
        }

        resp = client.get("/api/app/settings")

        assert resp.status_code == 200
        assert resp.json()["batch_size"] == 5

    @patch("apps.api.miniapp.routes.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.miniapp.routes.get_user_settings", new_callable=AsyncMock)
    def test_update_settings_endpoint(
        self,
        mock_get_user_settings,
        mock_save_user_settings,
        client: TestClient,
    ):
        mock_get_user_settings.return_value = {
            "auto_next": True,
            "batch_size": 1,
            "paused": False,
            "sync_summary": True,
            "daily_brief": True,
            "show_confidence": True,
            "show_raw_input": True,
            "draft_suggestions": True,
            "ambiguity_prompts": True,
            "show_steps_auto": False,
            "changes_only": False,
        }

        resp = client.put("/api/app/settings", json={"batch_size": 10, "changes_only": True})

        assert resp.status_code == 200
        assert resp.json()["batch_size"] == 10
        assert resp.json()["changes_only"] is True
        mock_save_user_settings.assert_awaited_once()

    @patch("apps.api.miniapp.routes.ProjectRepository")
    def test_update_project_type_success(self, mock_repo_cls, client: TestClient):
        project_id = uuid.uuid4()
        mock_project = MagicMock()
        mock_project.project_type = "personal"
        mock_repo = mock_repo_cls.return_value
        mock_repo.get_by_id = AsyncMock(return_value=mock_project)
        mock_repo.save = AsyncMock(return_value=mock_project)

        resp = client.patch(
            f"/api/app/projects/{project_id}",
            json={"project_type": "family"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Project type updated"}
        mock_repo.save.assert_awaited_once()

    @patch("apps.api.miniapp.routes.ProjectRepository")
    def test_update_project_type_invalid_type(self, mock_repo_cls, client: TestClient):
        project_id = uuid.uuid4()

        resp = client.patch(
            f"/api/app/projects/{project_id}",
            json={"project_type": "nonexistent"},
        )

        assert resp.status_code == 400
        assert "Invalid project_type" in resp.json()["detail"]

    @patch("apps.api.miniapp.routes.ProjectRepository")
    def test_update_project_type_not_found(self, mock_repo_cls, client: TestClient):
        project_id = uuid.uuid4()
        mock_repo = mock_repo_cls.return_value
        mock_repo.get_by_id = AsyncMock(return_value=None)

        resp = client.patch(
            f"/api/app/projects/{project_id}",
            json={"project_type": "personal"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"
