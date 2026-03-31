from __future__ import annotations

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false

from types import SimpleNamespace
from unittest.mock import patch

from apps.api.telegram.keyboards import proposal_keyboard, settings_keyboard


def _button_texts(kb) -> list[str]:
    return [button.text for row in kb.inline_keyboard for button in row]


def _find_button(kb, text: str):
    for row in kb.inline_keyboard:
        for button in row:
            if button.text == text:
                return button
    return None


class TestMiniAppTelegramIntegration:
    @patch("apps.api.telegram.keyboards.get_settings")
    def test_proposal_keyboard_includes_webapp_button_when_configured(self, mock_get_settings):
        mock_get_settings.return_value = SimpleNamespace(mini_app_url="https://mini.example.com")

        kb = proposal_keyboard("12345678123456781234567812345678")

        assert "📱 Open in App" in _button_texts(kb)

    @patch("apps.api.telegram.keyboards.get_settings")
    def test_proposal_keyboard_excludes_webapp_button_when_unset(self, mock_get_settings):
        mock_get_settings.return_value = SimpleNamespace(mini_app_url="")

        kb = proposal_keyboard("12345678123456781234567812345678")

        assert "📱 Open in App" not in _button_texts(kb)

    @patch("apps.api.telegram.keyboards.get_settings")
    def test_proposal_keyboard_webapp_url_uses_full_uuid(self, mock_get_settings):
        mock_get_settings.return_value = SimpleNamespace(mini_app_url="https://mini.example.com")

        kb = proposal_keyboard("12345678123456781234567812345678")
        button = _find_button(kb, "📱 Open in App")

        assert button is not None
        assert button.web_app is not None
        assert (
            button.web_app.url
            == "https://mini.example.com/app/review/12345678-1234-5678-1234-567812345678"
        )

    @patch("apps.api.telegram.keyboards.get_settings")
    def test_settings_keyboard_includes_webapp_button_when_configured(self, mock_get_settings):
        mock_get_settings.return_value = SimpleNamespace(mini_app_url="https://mini.example.com")

        kb = settings_keyboard({})

        assert "📱 Open Settings in App" in _button_texts(kb)

    @patch("apps.api.telegram.keyboards.get_settings")
    def test_settings_keyboard_excludes_webapp_button_when_unset(self, mock_get_settings):
        mock_get_settings.return_value = SimpleNamespace(mini_app_url="")

        kb = settings_keyboard({})

        assert "📱 Open Settings in App" not in _button_texts(kb)
