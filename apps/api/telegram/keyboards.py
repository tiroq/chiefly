from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from core.domain.enums import ReviewAction, TaskKind
from core.schemas.telegram import CallbackPayload


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Review Queue"), KeyboardButton(text="▶️ Next Item")],
            [KeyboardButton(text="📬 Backlog"), KeyboardButton(text="📅 Today")],
            [KeyboardButton(text="📁 Projects"), KeyboardButton(text="✏️ Draft")],
            [KeyboardButton(text="⚙️ Settings"), KeyboardButton(text="❓ Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def queue_summary_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Start Review", callback_data="queue:start"),
                InlineKeyboardButton(text="📦 Review 5", callback_data="queue:batch:5"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Ambiguous Only", callback_data="queue:ambiguous"),
                InlineKeyboardButton(text="⏸ Pause", callback_data="queue:pause"),
            ],
        ]
    )


def proposal_keyboard(short_id: str) -> InlineKeyboardMarkup:
    def _btn(text: str, action: ReviewAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text,
            callback_data=CallbackPayload(action=action, task_id=short_id).encode(),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("✅ Confirm", ReviewAction.CONFIRM),
                _btn("✏️ Edit Title", ReviewAction.EDIT),
            ],
            [
                _btn("📁 Change Project", ReviewAction.CHANGE_PROJECT),
                _btn("🔄 Change Type", ReviewAction.CHANGE_TYPE),
            ],
            [
                _btn("❓ Clarify", ReviewAction.CLARIFY),
                _btn("📋 Show Steps", ReviewAction.SHOW_STEPS),
            ],
            [
                _btn("💬 Draft Message", ReviewAction.DRAFT_MESSAGE),
                _btn("⏭ Skip", ReviewAction.SKIP),
            ],
            [
                _btn("🗑 Discard", ReviewAction.DISCARD),
                InlineKeyboardButton(text="⏸ Pause", callback_data="queue:pause"),
            ],
        ]
    )


def discard_confirm_keyboard(short_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Yes, discard",
                    callback_data=f"discard_confirm:{short_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"discard_cancel:{short_id}",
                ),
            ]
        ]
    )


def kind_picker_keyboard(short_id: str) -> InlineKeyboardMarkup:
    kind_descriptions = {
        TaskKind.TASK: ("📋 Task", "something you should do"),
        TaskKind.WAITING: ("⏳ Waiting", "something you are waiting for"),
        TaskKind.COMMITMENT: ("🤝 Commitment", "something you promised"),
        TaskKind.IDEA: ("💡 Idea", "not actionable yet"),
        TaskKind.REFERENCE: ("📎 Reference", "informational only"),
    }
    buttons = []
    for kind, (label, desc) in kind_descriptions.items():
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{label} — {desc}",
                    callback_data=f"kind:{short_id}:{kind.value}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="↩️ Back", callback_data=f"back_to_card:{short_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def project_picker_keyboard(
    short_id: str,
    projects: list[tuple[str, str, str | None]],
    current_project: str | None = None,
    suggested_project: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    for name, slug, description in projects:
        label = name
        if name == current_project:
            label = f"✓ {name} (current)"
        elif name == suggested_project:
            label = f"★ {name}"
        if description:
            label = f"{label} — {description[:40]}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"proj:{short_id}:{slug}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="↩️ Back", callback_data=f"back_to_card:{short_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def disambiguation_keyboard(
    short_id: str, options: list[tuple[str, str, int]]
) -> InlineKeyboardMarkup:
    buttons = []
    for kind_value, title, idx in options:
        label = f"{kind_value.capitalize()}: {title[:50]}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"disambig:{short_id}:{idx}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="✏️ Manual edit", callback_data=f"edit:{short_id}"),
            InlineKeyboardButton(text="🗑 Discard", callback_data=f"discard:{short_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def draft_keyboard(short_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Use", callback_data=f"draft_use:{short_id}"),
                InlineKeyboardButton(text="📏 Shorter", callback_data=f"draft_shorter:{short_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="👔 More Formal", callback_data=f"draft_formal:{short_id}"
                ),
                InlineKeyboardButton(text="↩️ Back", callback_data=f"back_to_card:{short_id}"),
            ],
        ]
    )


def settings_keyboard(settings: dict[str, bool | int]) -> InlineKeyboardMarkup:
    def _toggle(key: str, label: str, current: bool) -> InlineKeyboardButton:
        status = "ON" if current else "OFF"
        return InlineKeyboardButton(
            text=f"{label}: {status}",
            callback_data=f"setting:{key}",
        )

    batch_size = settings.get("batch_size", 1)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_toggle("auto_next", "Auto-next", settings.get("auto_next", True))],
            [
                InlineKeyboardButton(
                    text=f"Batch size: {batch_size}",
                    callback_data="setting:batch_size",
                )
            ],
            [_toggle("paused", "Paused", settings.get("paused", False))],
            [_toggle("sync_summary", "Sync summary", settings.get("sync_summary", True))],
            [_toggle("daily_brief", "Daily brief", settings.get("daily_brief", True))],
            [_toggle("show_confidence", "Show confidence", settings.get("show_confidence", True))],
            [_toggle("show_raw_input", "Show raw input", settings.get("show_raw_input", True))],
            [
                _toggle(
                    "draft_suggestions",
                    "Draft suggestions",
                    settings.get("draft_suggestions", True),
                )
            ],
            [
                _toggle(
                    "ambiguity_prompts",
                    "Ambiguity prompts",
                    settings.get("ambiguity_prompts", True),
                )
            ],
            [_toggle("show_steps_auto", "Show steps auto", settings.get("show_steps_auto", False))],
            [InlineKeyboardButton(text="↩️ Back", callback_data="settings:close")],
        ]
    )


def backlog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Start Review", callback_data="queue:start"),
                InlineKeyboardButton(text="📦 Review 5", callback_data="queue:batch:5"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Ambiguous Only", callback_data="queue:ambiguous"),
                InlineKeyboardButton(text="⏸ Pause", callback_data="queue:pause"),
            ],
        ]
    )


def today_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Review Queue", callback_data="queue:start"),
                InlineKeyboardButton(text="📬 Backlog", callback_data="nav:backlog"),
            ],
        ]
    )
