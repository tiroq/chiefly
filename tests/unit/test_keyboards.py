from __future__ import annotations

from apps.api.telegram.keyboards import (
    disambiguation_keyboard,
    discard_confirm_keyboard,
    draft_keyboard,
    kind_picker_keyboard,
    main_menu_keyboard,
    project_picker_keyboard,
    proposal_keyboard,
    settings_keyboard,
)
from core.domain.enums import TaskKind


class TestMainMenuKeyboard:
    def test_has_8_buttons_in_4_rows(self):
        kb = main_menu_keyboard()
        assert len(kb.keyboard) == 4
        assert all(len(row) == 2 for row in kb.keyboard)

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
            "✏️ Draft",
            "⚙️ Settings",
            "❓ Help",
        ]


class TestProposalKeyboard:
    def test_has_5_rows(self):
        kb = proposal_keyboard("abc123")
        assert len(kb.inline_keyboard) == 5

    def test_confirm_callback_data(self):
        kb = proposal_keyboard("abc123")
        assert kb.inline_keyboard[0][0].callback_data == "confirm:abc123"

    def test_contains_all_actions(self):
        short_id = "abc123"
        kb = proposal_keyboard(short_id)
        callbacks = {button.callback_data for row in kb.inline_keyboard for button in row}
        assert {
            f"confirm:{short_id}",
            f"edit:{short_id}",
            f"change_project:{short_id}",
            f"change_type:{short_id}",
            f"clarify:{short_id}",
            f"show_steps:{short_id}",
            f"draft_message:{short_id}",
            f"skip:{short_id}",
            f"discard:{short_id}",
        }.issubset(callbacks)

    def test_pause_button_present(self):
        kb = proposal_keyboard("abc123")
        callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
        assert "queue:pause" in callbacks


class TestKindPickerKeyboard:
    def test_has_5_kinds_plus_back(self):
        kb = kind_picker_keyboard("abc123")
        assert len(kb.inline_keyboard) == 6

    def test_callback_data_format(self):
        short_id = "abc123"
        kb = kind_picker_keyboard(short_id)
        callbacks = [row[0].callback_data for row in kb.inline_keyboard[:-1]]
        assert callbacks == [f"kind:{short_id}:{kind.value}" for kind in TaskKind]

    def test_descriptions_in_labels(self):
        kb = kind_picker_keyboard("abc123")
        labels = [row[0].text for row in kb.inline_keyboard[:-1]]
        assert all(" — " in label for label in labels)
        assert "something you should do" in labels[0]

    def test_back_button(self):
        kb = kind_picker_keyboard("abc123")
        back = kb.inline_keyboard[-1][0]
        assert back.text == "↩️ Back"
        assert back.callback_data == "back_to_card:abc123"


class TestProjectPickerKeyboard:
    def test_marks_current_project(self):
        projects: list[tuple[str, str, str | None]] = [
            ("Personal", "personal", None),
            ("Work", "work", None),
        ]
        kb = project_picker_keyboard("abc123", projects, current_project="Personal")
        assert kb.inline_keyboard[0][0].text.startswith("✓ Personal")
        assert "(current)" in kb.inline_keyboard[0][0].text

    def test_marks_suggested_project(self):
        projects: list[tuple[str, str, str | None]] = [
            ("Personal", "personal", None),
            ("Work", "work", None),
        ]
        kb = project_picker_keyboard("abc123", projects, suggested_project="Work")
        assert kb.inline_keyboard[1][0].text.startswith("★ Work")

    def test_includes_description(self):
        long_description = "x" * 60
        projects: list[tuple[str, str, str | None]] = [("Personal", "personal", long_description)]
        kb = project_picker_keyboard("abc123", projects)
        expected_description = long_description[:40]
        assert kb.inline_keyboard[0][0].text == f"Personal — {expected_description}"

    def test_back_button(self):
        projects: list[tuple[str, str, str | None]] = [("Personal", "personal", None)]
        kb = project_picker_keyboard("abc123", projects)
        back = kb.inline_keyboard[-1][0]
        assert back.text == "↩️ Back"
        assert back.callback_data == "back_to_card:abc123"

    def test_callback_data_format(self):
        projects: list[tuple[str, str, str | None]] = [
            ("Personal", "personal", None),
            ("Work", "work", None),
        ]
        kb = project_picker_keyboard("abc123", projects)
        callbacks = [row[0].callback_data for row in kb.inline_keyboard[:-1]]
        assert callbacks == ["proj:abc123:personal", "proj:abc123:work"]


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


class TestDisambiguationKeyboard:
    def test_renders_options(self):
        options = [("task", "Buy milk", 0), ("idea", "Plan startup", 1)]
        kb = disambiguation_keyboard("abc123", options)
        assert len(kb.inline_keyboard) == len(options) + 1

    def test_callback_data_format(self):
        options = [("task", "Buy milk", 0), ("idea", "Plan startup", 1)]
        kb = disambiguation_keyboard("abc123", options)
        callbacks = [row[0].callback_data for row in kb.inline_keyboard[:-1]]
        assert callbacks == ["disambig:abc123:0", "disambig:abc123:1"]

    def test_footer_has_edit_and_discard(self):
        kb = disambiguation_keyboard("abc123", [("task", "Buy milk", 0)])
        footer = kb.inline_keyboard[-1]
        assert footer[0].text == "✏️ Manual edit"
        assert footer[1].text == "🗑 Discard"


class TestDraftKeyboard:
    def test_has_4_buttons_in_2_rows(self):
        kb = draft_keyboard("abc123")
        assert len(kb.inline_keyboard) == 2
        assert all(len(row) == 2 for row in kb.inline_keyboard)

    def test_callback_data(self):
        kb = draft_keyboard("abc123")
        callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]
        assert callbacks == [
            "draft_use:abc123",
            "draft_shorter:abc123",
            "draft_formal:abc123",
            "back_to_card:abc123",
        ]
