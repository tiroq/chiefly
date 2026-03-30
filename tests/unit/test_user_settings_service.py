from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.user_settings_service import (
    cycle_batch_size,
    get_user_settings,
    toggle_bool_setting,
)


class TestGetUserSettings:
    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.AppSettingRepository")
    async def test_returns_defaults_when_no_stored_settings(self, mock_repo_cls):
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value="")
        mock_repo_cls.return_value = repo

        settings = await get_user_settings(session)

        assert settings["auto_next"] is True
        assert settings["batch_size"] == 1
        assert settings["paused"] is False
        repo.get.assert_awaited_once_with("user_settings", "")

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.AppSettingRepository")
    async def test_merges_stored_with_defaults(self, mock_repo_cls):
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value='{"auto_next": false, "batch_size": 10}')
        mock_repo_cls.return_value = repo

        settings = await get_user_settings(session)

        assert settings["auto_next"] is False
        assert settings["batch_size"] == 10
        assert settings["paused"] is False

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.AppSettingRepository")
    async def test_handles_corrupt_json(self, mock_repo_cls):
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value="{broken json")
        mock_repo_cls.return_value = repo

        settings = await get_user_settings(session)

        assert settings["auto_next"] is True
        assert settings["batch_size"] == 1


class TestToggleBoolSetting:
    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_toggles_true_to_false(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"auto_next": True, "batch_size": 1, "paused": False}

        settings = await toggle_bool_setting(session, "auto_next")

        assert settings["auto_next"] is False
        mock_save_user_settings.assert_awaited_once_with(session, settings)

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_toggles_false_to_true(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"auto_next": True, "batch_size": 1, "paused": False}

        settings = await toggle_bool_setting(session, "paused")

        assert settings["paused"] is True
        mock_save_user_settings.assert_awaited_once_with(session, settings)

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_ignores_non_bool_setting(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        original = {"auto_next": True, "batch_size": 5, "paused": False}
        mock_get_user_settings.return_value = dict(original)

        settings = await toggle_bool_setting(session, "batch_size")

        assert settings["batch_size"] == 5
        mock_save_user_settings.assert_awaited_once_with(session, settings)


class TestCycleBatchSize:
    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_cycles_1_to_5(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"batch_size": 1}

        settings = await cycle_batch_size(session)

        assert settings["batch_size"] == 5
        mock_save_user_settings.assert_awaited_once_with(session, settings)

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_cycles_5_to_10(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"batch_size": 5}

        settings = await cycle_batch_size(session)

        assert settings["batch_size"] == 10
        mock_save_user_settings.assert_awaited_once_with(session, settings)

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_cycles_10_to_1(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"batch_size": 10}

        settings = await cycle_batch_size(session)

        assert settings["batch_size"] == 1
        mock_save_user_settings.assert_awaited_once_with(session, settings)

    @pytest.mark.asyncio
    @patch("apps.api.services.user_settings_service.save_user_settings", new_callable=AsyncMock)
    @patch("apps.api.services.user_settings_service.get_user_settings", new_callable=AsyncMock)
    async def test_unknown_value_resets_to_1(self, mock_get_user_settings, mock_save_user_settings):
        session = AsyncMock()
        mock_get_user_settings.return_value = {"batch_size": 7}

        settings = await cycle_batch_size(session)

        assert settings["batch_size"] == 1
        mock_save_user_settings.assert_awaited_once_with(session, settings)
