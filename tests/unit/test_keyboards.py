from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from apps.api.telegram.keyboards import (
    discard_confirm_keyboard,
    main_menu_keyboard,
    proposal_keyboard,
    settings_keyboard,
)


def _proposal_kb(short_id: str):
    with patch(
        "apps.api.telegram.keyboards.get_settings",
        return_value=SimpleNamespace(mini_app_url=None),
    ):
        return proposal_keyboard(short_id)


class TestMainMenuKeyboard:
    def test_has_7_buttons_in_4_rows(self):
        kb = main_menu_keyboard()
        assert len(kb.keyboard) == 4
        row_lengths = [len(row) for row in kb.keyboard]
        assert row_lengths == [2, 2, 1, 2]

    def test_is_persistent_and_resized(self):
        kb = main_menu_keyboard()
        assert kb.is_persistent is True
        assert kb.resize_keyboard is True

    def test_button_labels(self):
        kb = main_menu_keyboard()
        labels = [button.text for row in kb.keyboard for button in row]
        assert labels == [
            "📋 Review Queue",
            "▶️ Next Item",
            "📬 Backlog",
            "📅 Today",
            "📁 Projects",
            "⚙️ Settings",
            "❓ Help",
        ]

    def test_no_draft_button_in_main_menu(self):
        kb = main_menu_keyboard()
        labels = [button.text for row in kb.keyboard for button in row]
        assert "✏️ Draft" not in labels


class TestProposalKeyboard:
    def test_has_2_rows(self):
        kb = _proposal_kb("abc123")
        assert len(kb.inline_keyboard) == 2

    def test_confirm_callback_data(self):
        kb = _proposal_kb("abc123")
        assert kb.inline_keyboard[0][0].callback_data == "confirm:abc123"

    def test_contains_all_actions(self):
        short_id = "abc123"
        kb = _proposal_kb(short_id)
        callbacks = {button.callback_data for row in kb.inline_keyboard for button in row}
        assert {
            f"confirm:{short_id}",
            f"skip:{short_id}",
            f"discard:{short_id}",
        }.issubset(callbacks)
        assert "queue:pause" in callbacks

    def test_pause_button_present(self):
        kb = _proposal_kb("abc123")
        callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
        assert "queue:pause" in callbacks

    def test_no_editing_buttons_present(self):
        kb = _proposal_kb("abc123")
        callbacks = {button.callback_data for row in kb.inline_keyboard for button in row}
        editing_prefixes = [
            "edit:",
            "change_project:",
            "change_type:",
            "clarify:",
            "draft_message:",
            "show_steps:",
        ]
        for prefix in editing_prefixes:
            assert not any(cb and cb.startswith(prefix) for cb in callbacks), (
                f"Found editing button: {prefix}"
            )


class TestDiscardConfirmKeyboard:
    def test_two_buttons(self):
        kb = discard_confirm_keyboard("abc123")
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2
        assert kb.inline_keyboard[0][0].text == "✅ Yes, discard"
        assert kb.inline_keyboard[0][1].text == "❌ Cancel"

    def test_callback_data(self):
        kb = discard_confirm_keyboard("abc123")
        assert kb.inline_keyboard[0][0].callback_data == "discard_confirm:abc123"
        assert kb.inline_keyboard[0][1].callback_data == "discard_cancel:abc123"


class TestSettingsKeyboard:
    def test_shows_toggle_states(self):
        settings = {
            "auto_next": False,
            "batch_size": 5,
            "paused": True,
            "sync_summary": False,
            "daily_brief": True,
            "show_confidence": False,
            "show_raw_input": True,
            "draft_suggestions": False,
            "ambiguity_prompts": True,
            "show_steps_auto": False,
        }
        kb = settings_keyboard(settings)
        labels = [row[0].text for row in kb.inline_keyboard[:-1]]
        assert "Auto-next: OFF" in labels
        assert "Paused: ON" in labels
        assert "Sync summary: OFF" in labels

    def test_batch_size_shows_value(self):
        kb = settings_keyboard({"batch_size": 10})
        assert kb.inline_keyboard[1][0].text == "Batch size: 10"

    def test_has_back_button(self):
        kb = settings_keyboard({})
        back = kb.inline_keyboard[-1][0]
        assert back.text == "↩️ Back"
        assert back.callback_data == "settings:close"

    def test_no_draft_suggestions_toggle(self):
        kb = settings_keyboard({"draft_suggestions": True})
        all_labels = [row[0].text for row in kb.inline_keyboard]
        assert not any("Draft suggestions" in label for label in all_labels)
