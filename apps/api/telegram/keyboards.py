from __future__ import annotations

import uuid as _uuid

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from apps.api.config import get_settings
from core.domain.enums import ReviewAction
from core.schemas.telegram import CallbackPayload


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Review Queue"), KeyboardButton(text="▶️ Next Item")],
            [KeyboardButton(text="📬 Backlog"), KeyboardButton(text="📅 Today")],
            [KeyboardButton(text="📁 Projects")],
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

    rows: list[list[InlineKeyboardButton]] = [
        [
            _btn("✅ Confirm", ReviewAction.CONFIRM),
            _btn("⏭ Skip", ReviewAction.SKIP),
        ],
        [
            _btn("🗑 Discard", ReviewAction.DISCARD),
            InlineKeyboardButton(text="⏸ Pause", callback_data="queue:pause"),
        ],
    ]

    mini_app_url = get_settings().mini_app_url
    if mini_app_url:
        full_uuid = str(_uuid.UUID(short_id))
        rows.append(
            [
                InlineKeyboardButton(
                    text="📱 Open in App",
                    web_app=WebAppInfo(url=f"{mini_app_url}/app/review/{full_uuid}"),
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def settings_keyboard(settings: dict[str, bool | int]) -> InlineKeyboardMarkup:
    def _toggle(key: str, label: str, current: bool | int) -> InlineKeyboardButton:
        status = "ON" if bool(current) else "OFF"
        return InlineKeyboardButton(
            text=f"{label}: {status}",
            callback_data=f"setting:{key}",
        )

    batch_size = settings.get("batch_size", 1)
    rows: list[list[InlineKeyboardButton]] = [
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
                "ambiguity_prompts",
                "Ambiguity prompts",
                settings.get("ambiguity_prompts", True),
            )
        ],
        [_toggle("show_steps_auto", "Show steps auto", settings.get("show_steps_auto", False))],
        [InlineKeyboardButton(text="🔌 Test LLM Connection", callback_data="settings:test_llm")],
    ]

    mini_app_url = get_settings().mini_app_url
    if mini_app_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📱 Open Settings in App",
                    web_app=WebAppInfo(url=f"{mini_app_url}/app/settings"),
                )
            ]
        )

    rows.append([InlineKeyboardButton(text="↩️ Back", callback_data="settings:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
