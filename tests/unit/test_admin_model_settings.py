from __future__ import annotations

from typing import Any, Callable, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from apps.api.services.model_settings_service import (
    EffectiveLLMConfig,
    get_auth_status,
)


def _mock_env_settings():
    env = MagicMock()
    env.llm_provider = "openai"
    env.llm_model = "gpt-4o"
    env.llm_api_key = "sk-env-key"
    env.llm_base_url = ""
    env.llm_fast_model = ""
    env.llm_quality_model = ""
    env.llm_fallback_model = ""
    env.llm_auto_mode = False
    return env


def _default_db_settings():
    return {
        "provider": "",
        "model": "",
        "api_key": "",
        "base_url": "",
        "fast_model": "",
        "quality_model": "",
        "fallback_model": "",
        "auto_mode": False,
    }


def _effective_config(**overrides: str | bool) -> EffectiveLLMConfig:
    return EffectiveLLMConfig(
        provider=str(overrides.get("provider", "openai")),
        model=str(overrides.get("model", "gpt-4o")),
        api_key=str(overrides.get("api_key", "sk-env-key")),
        base_url=str(overrides.get("base_url", "")),
        fast_model=str(overrides.get("fast_model", "")),
        quality_model=str(overrides.get("quality_model", "")),
        fallback_model=str(overrides.get("fallback_model", "")),
        auto_mode=bool(overrides.get("auto_mode", False)),
    )


def _create_app_and_client(mock_session: AsyncMock) -> tuple[FastAPI, TestClient]:
    from apps.api.dependencies import get_session
    from apps.api.routes.admin_api import router

    app = FastAPI()
    app.include_router(router)

    async def _override_session():
        yield mock_session

    app.dependency_overrides[get_session] = _override_session

    auth_dep_raw = router.dependencies[0].dependency
    assert auth_dep_raw is not None
    auth_dep = cast(Callable[..., Any], auth_dep_raw)

    async def _no_auth() -> None:
        pass

    app.dependency_overrides[auth_dep] = _no_auth

    return app, TestClient(app)


class TestSaveEndpointProviderValidation:
    @patch("apps.api.routes.admin_api.get_effective_llm_config", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.save_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_settings", return_value=_mock_env_settings())
    def test_save_rejects_invalid_provider(self, _gs, mock_get, _save, _eff):
        mock_get.return_value = _default_db_settings()
        session = AsyncMock()
        session.commit = AsyncMock()
        _, client = _create_app_and_client(session)

        resp = client.post(
            "/model-settings/save",
            data={"provider": "invalid_provider", "model": "x", "auto_mode": "false"},
        )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        assert "Unsupported provider" in resp.json()["message"]
        _save.assert_not_awaited()

    @patch(
        "apps.api.routes.admin_api.get_auth_status",
        return_value={"source": "none", "configured": "false", "masked_key": ""},
    )
    @patch(
        "apps.api.routes.admin_api.get_effective_llm_config",
        new_callable=AsyncMock,
        return_value=_effective_config(),
    )
    @patch("apps.api.routes.admin_api.save_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_settings", return_value=_mock_env_settings())
    def test_save_accepts_valid_provider(self, _gs, mock_get, mock_save, _eff, _auth):
        mock_get.return_value = _default_db_settings()
        session = AsyncMock()
        session.commit = AsyncMock()
        _, client = _create_app_and_client(session)

        resp = client.post(
            "/model-settings/save",
            data={"provider": "github_models", "model": "openai/gpt-4o", "auto_mode": "false"},
        )

        assert resp.status_code == 200
        mock_save.assert_awaited_once()

    @patch(
        "apps.api.routes.admin_api.get_auth_status",
        return_value={"source": "none", "configured": "false", "masked_key": ""},
    )
    @patch(
        "apps.api.routes.admin_api.get_effective_llm_config",
        new_callable=AsyncMock,
        return_value=_effective_config(),
    )
    @patch("apps.api.routes.admin_api.save_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_settings", return_value=_mock_env_settings())
    def test_save_accepts_empty_provider(self, _gs, mock_get, mock_save, _eff, _auth):
        mock_get.return_value = _default_db_settings()
        session = AsyncMock()
        session.commit = AsyncMock()
        _, client = _create_app_and_client(session)

        resp = client.post(
            "/model-settings/save",
            data={"provider": "", "model": "", "auto_mode": "false"},
        )

        assert resp.status_code == 200
        mock_save.assert_awaited_once()


class TestTestEndpointProviderValidation:
    @patch("apps.api.routes.admin_api.get_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_settings", return_value=_mock_env_settings())
    def test_test_rejects_invalid_provider(self, _gs, mock_get):
        mock_get.return_value = _default_db_settings()
        session = AsyncMock()
        _, client = _create_app_and_client(session)

        resp = client.post(
            "/model-settings/test",
            data={"provider": "bad_provider", "model": "x"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "Unsupported provider" in resp.json()["message"]


class TestResetAuthEndpoint:
    @patch(
        "apps.api.routes.admin_api.get_auth_status",
        return_value={"source": "none", "configured": "false", "masked_key": ""},
    )
    @patch(
        "apps.api.routes.admin_api.get_effective_llm_config",
        new_callable=AsyncMock,
        return_value=_effective_config(),
    )
    @patch("apps.api.routes.admin_api.get_model_settings", new_callable=AsyncMock)
    @patch("apps.api.routes.admin_api.get_settings", return_value=_mock_env_settings())
    @patch("db.repositories.app_setting_repo.AppSettingRepository")
    def test_reset_auth_clears_api_key_only(self, mock_repo_cls, _gs, mock_get, _eff, _auth):
        import json

        stored_blob = json.dumps(
            {
                "provider": "github_models",
                "model": "openai/gpt-4o",
                "api_key": "ghp_secret",
                "auto_mode": True,
            }
        )
        repo = MagicMock()
        repo.get = AsyncMock(return_value=stored_blob)
        repo.set = AsyncMock()
        mock_repo_cls.return_value = repo

        mock_get.return_value = _default_db_settings()
        session = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        _, client = _create_app_and_client(session)

        resp = client.post("/model-settings/reset-auth")

        assert resp.status_code == 200
        repo.set.assert_awaited_once()
        written = json.loads(repo.set.call_args[0][1])
        assert "api_key" not in written
        assert written["provider"] == "github_models"
        assert written["auto_mode"] is True


class TestGetAuthStatus:
    def test_db_key_takes_priority(self):
        db: dict[str, str | bool] = {"api_key": "ghp_secretkey1234"}
        env = MagicMock()
        env.llm_api_key = "sk-env-key"

        result = get_auth_status(db, env)

        assert result["source"] == "database"
        assert result["configured"] == "true"
        assert result["masked_key"] == "••••1234"

    def test_env_key_used_when_no_db(self):
        db: dict[str, str | bool] = {"api_key": ""}
        env = MagicMock()
        env.llm_api_key = "sk-env-key-abcd"

        result = get_auth_status(db, env)

        assert result["source"] == "environment"
        assert result["configured"] == "true"
        assert result["masked_key"] == "••••abcd"

    def test_not_configured_when_no_keys(self):
        db: dict[str, str | bool] = {"api_key": ""}
        env = MagicMock()
        env.llm_api_key = ""

        result = get_auth_status(db, env)

        assert result["source"] == "none"
        assert result["configured"] == "false"
        assert result["masked_key"] == ""
