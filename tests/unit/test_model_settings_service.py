from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.model_settings_service import (
    EffectiveLLMConfig,
    _get_raw_stored_keys,
    get_effective_llm_config,
    get_model_settings,
    reset_model_settings,
    save_model_settings,
)


def _mock_repo(stored_value: str = ""):
    repo = MagicMock()
    repo.get = AsyncMock(return_value=stored_value)
    repo.set = AsyncMock()
    return repo


class TestGetModelSettings:
    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_returns_defaults_when_empty(self, mock_repo_cls):
        session = AsyncMock()
        mock_repo_cls.return_value = _mock_repo("")
        settings = await get_model_settings(session)
        assert settings["provider"] == ""
        assert settings["model"] == ""
        assert settings["auto_mode"] is False

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_merges_stored_with_defaults(self, mock_repo_cls):
        session = AsyncMock()
        mock_repo_cls.return_value = _mock_repo(
            '{"provider": "github_models", "model": "openai/gpt-4o"}'
        )
        settings = await get_model_settings(session)
        assert settings["provider"] == "github_models"
        assert settings["model"] == "openai/gpt-4o"
        assert settings["api_key"] == ""
        assert settings["auto_mode"] is False

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_handles_corrupt_json(self, mock_repo_cls):
        session = AsyncMock()
        mock_repo_cls.return_value = _mock_repo("{broken json")
        settings = await get_model_settings(session)
        assert settings["provider"] == ""
        assert settings["auto_mode"] is False

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_ignores_unknown_keys(self, mock_repo_cls):
        session = AsyncMock()
        mock_repo_cls.return_value = _mock_repo('{"provider": "openai", "unknown_key": "value"}')
        settings = await get_model_settings(session)
        assert "unknown_key" not in settings


class TestSaveModelSettings:
    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_save_persists_settings(self, mock_repo_cls):
        session = AsyncMock()
        repo = _mock_repo()
        mock_repo_cls.return_value = repo

        await save_model_settings(session, {"provider": "github_models"})

        repo.set.assert_awaited_once()
        call_args = repo.set.call_args
        assert call_args[0][0] == "model_settings"
        assert "github_models" in call_args[0][1]


class TestResetModelSettings:
    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_reset_clears_to_empty(self, mock_repo_cls):
        session = AsyncMock()
        repo = _mock_repo()
        mock_repo_cls.return_value = repo

        await reset_model_settings(session)

        repo.set.assert_awaited_once()
        call_args = repo.set.call_args
        assert call_args[0][0] == "model_settings"
        assert call_args[0][1] == ""


class TestGetEffectiveLLMConfig:
    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service._get_raw_stored_keys", new_callable=AsyncMock)
    @patch("apps.api.services.model_settings_service.get_model_settings", new_callable=AsyncMock)
    async def test_db_overrides_env(self, mock_get, mock_keys):
        mock_get.return_value = {
            "provider": "github_models",
            "model": "openai/gpt-4o",
            "api_key": "ghp_db_key",
            "base_url": "",
            "fast_model": "",
            "quality_model": "",
            "fallback_model": "",
            "auto_mode": False,
        }
        mock_keys.return_value = {"provider", "model", "api_key", "auto_mode"}
        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = "sk-env-key"
        env.llm_base_url = ""
        env.llm_fast_model = ""
        env.llm_quality_model = ""
        env.llm_fallback_model = ""
        env.llm_auto_mode = False

        config = await get_effective_llm_config(AsyncMock(), env)

        assert isinstance(config, EffectiveLLMConfig)
        assert config.provider == "github_models"
        assert config.model == "openai/gpt-4o"
        assert config.api_key == "ghp_db_key"

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service._get_raw_stored_keys", new_callable=AsyncMock)
    @patch("apps.api.services.model_settings_service.get_model_settings", new_callable=AsyncMock)
    async def test_falls_back_to_env_when_db_empty(self, mock_get, mock_keys):
        mock_get.return_value = {
            "provider": "",
            "model": "",
            "api_key": "",
            "base_url": "",
            "fast_model": "",
            "quality_model": "",
            "fallback_model": "",
            "auto_mode": False,
        }
        mock_keys.return_value = set()
        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = "sk-env-key"
        env.llm_base_url = ""
        env.llm_fast_model = "gpt-4o-mini"
        env.llm_quality_model = "gpt-4o"
        env.llm_fallback_model = ""
        env.llm_auto_mode = True

        config = await get_effective_llm_config(AsyncMock(), env)

        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.api_key == "sk-env-key"
        assert config.fast_model == "gpt-4o-mini"
        assert config.quality_model == "gpt-4o"
        assert config.auto_mode is True

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service._get_raw_stored_keys", new_callable=AsyncMock)
    @patch("apps.api.services.model_settings_service.get_model_settings", new_callable=AsyncMock)
    async def test_auto_mode_db_true_overrides_env_false(self, mock_get, mock_keys):
        mock_get.return_value = {
            "provider": "",
            "model": "",
            "api_key": "",
            "base_url": "",
            "fast_model": "",
            "quality_model": "",
            "fallback_model": "",
            "auto_mode": True,
        }
        mock_keys.return_value = {"auto_mode"}
        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = ""
        env.llm_base_url = ""
        env.llm_fast_model = ""
        env.llm_quality_model = ""
        env.llm_fallback_model = ""
        env.llm_auto_mode = False

        config = await get_effective_llm_config(AsyncMock(), env)

        assert config.auto_mode is True

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service._get_raw_stored_keys", new_callable=AsyncMock)
    @patch("apps.api.services.model_settings_service.get_model_settings", new_callable=AsyncMock)
    async def test_auto_mode_db_false_overrides_env_true(self, mock_get, mock_keys):
        mock_get.return_value = {
            "provider": "",
            "model": "",
            "api_key": "",
            "base_url": "",
            "fast_model": "",
            "quality_model": "",
            "fallback_model": "",
            "auto_mode": False,
        }
        mock_keys.return_value = {"auto_mode"}
        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = ""
        env.llm_base_url = ""
        env.llm_fast_model = ""
        env.llm_quality_model = ""
        env.llm_fallback_model = ""
        env.llm_auto_mode = True

        config = await get_effective_llm_config(AsyncMock(), env)

        assert config.auto_mode is False

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service.AppSettingRepository")
    async def test_reset_then_env_auto_mode_used(self, mock_repo_cls):
        session = AsyncMock()
        repo = _mock_repo("")
        mock_repo_cls.return_value = repo

        await reset_model_settings(session)

        repo.set.assert_awaited_once_with("model_settings", "")

        repo.get = AsyncMock(return_value="")
        stored_keys = await _get_raw_stored_keys(session)
        assert stored_keys == set()

        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = ""
        env.llm_base_url = ""
        env.llm_fast_model = ""
        env.llm_quality_model = ""
        env.llm_fallback_model = ""
        env.llm_auto_mode = True

        config = await get_effective_llm_config(session, env)
        assert config.auto_mode is True

    @pytest.mark.asyncio
    @patch("apps.api.services.model_settings_service._get_raw_stored_keys", new_callable=AsyncMock)
    @patch("apps.api.services.model_settings_service.get_model_settings", new_callable=AsyncMock)
    async def test_auto_mode_falls_back_to_env_when_not_stored(self, mock_get, mock_keys):
        mock_get.return_value = {
            "provider": "",
            "model": "",
            "api_key": "",
            "base_url": "",
            "fast_model": "",
            "quality_model": "",
            "fallback_model": "",
            "auto_mode": False,
        }
        mock_keys.return_value = set()
        env = MagicMock()
        env.llm_provider = "openai"
        env.llm_model = "gpt-4o"
        env.llm_api_key = ""
        env.llm_base_url = ""
        env.llm_fast_model = ""
        env.llm_quality_model = ""
        env.llm_fallback_model = ""
        env.llm_auto_mode = True

        config = await get_effective_llm_config(AsyncMock(), env)

        assert config.auto_mode is True
