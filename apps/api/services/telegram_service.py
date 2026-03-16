"""
Telegram service for sending messages and handling the bot.
"""

from __future__ import annotations

import asyncio
import html

from apps.api.logging import get_logger
from core.domain.exceptions import TelegramError
from core.schemas.llm import TaskClassificationResult
from core.schemas.telegram import (
    CallbackPayload,
    KindSelectPayload,
    ProjectSelectPayload,
)
from core.domain.enums import ReviewAction, TaskKind

logger = get_logger(__name__)

CONFIDENCE_EMOJI = {"low": "🔴", "medium": "🟡", "high": "🟢"}
KIND_LABELS = {
    TaskKind.TASK: "📋 Task",
    TaskKind.WAITING: "⏳ Waiting",
    TaskKind.COMMITMENT: "🤝 Commitment",
    TaskKind.IDEA: "💡 Idea",
    TaskKind.REFERENCE: "📎 Reference",
}


def _build_proposal_text(
    raw_text: str,
    classification: TaskClassificationResult,
    project_name: str | None,
) -> str:
    conf_emoji = CONFIDENCE_EMOJI.get(classification.confidence, "⚪")
    kind_label = KIND_LABELS.get(classification.kind, classification.kind)

    # Escape all user/LLM-provided content before embedding in HTML
    safe_raw = html.escape(raw_text)
    safe_title = html.escape(classification.normalized_title)
    safe_project = html.escape(project_name) if project_name else "?"
    safe_next_action = html.escape(classification.next_action) if classification.next_action else None
    safe_due_hint = html.escape(classification.due_hint) if classification.due_hint else None

    lines = [
        "🤖 <b>Chiefly detected a new inbox item</b>",
        "",
        f"<b>Raw:</b> <i>{safe_raw}</i>",
        "",
        "📌 <b>Proposed:</b>",
        f"  Type: {kind_label}",
        f"  Project: {safe_project}",
        f"  Title: {safe_title}",
    ]
    if safe_next_action:
        lines.append(f"  Next step: {safe_next_action}")
    if safe_due_hint:
        lines.append(f"  Due: {safe_due_hint}")
    lines.append(f"  Confidence: {conf_emoji} {classification.confidence.capitalize()}")

    if classification.ambiguities:
        lines.append("")
        lines.append("⚠️ <b>Ambiguities:</b>")
        for a in classification.ambiguities:
            lines.append(f"  • {html.escape(a)}")

    return "\n".join(lines)


class TelegramService:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._bot = None

    def _get_bot(self):
        if self._bot is None:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode

            self._bot = Bot(
                token=self._bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        return self._bot

    async def send_proposal(
        self,
        task_id: str,
        raw_text: str,
        classification: TaskClassificationResult,
        project_name: str | None,
    ) -> int:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        text = _build_proposal_text(raw_text, classification, project_name)
        short_id = task_id.replace("-", "")

        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Confirm",
                    callback_data=CallbackPayload(
                        action=ReviewAction.CONFIRM, task_id=short_id
                    ).encode(),
                ),
                InlineKeyboardButton(
                    text="✏️ Edit",
                    callback_data=CallbackPayload(
                        action=ReviewAction.EDIT, task_id=short_id
                    ).encode(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📁 Change Project",
                    callback_data=CallbackPayload(
                        action=ReviewAction.CHANGE_PROJECT, task_id=short_id
                    ).encode(),
                ),
                InlineKeyboardButton(
                    text="🔄 Change Type",
                    callback_data=CallbackPayload(
                        action=ReviewAction.CHANGE_TYPE, task_id=short_id
                    ).encode(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📋 Show Steps",
                    callback_data=CallbackPayload(
                        action=ReviewAction.SHOW_STEPS, task_id=short_id
                    ).encode(),
                ),
                InlineKeyboardButton(
                    text="🗑 Discard",
                    callback_data=CallbackPayload(
                        action=ReviewAction.DISCARD, task_id=short_id
                    ).encode(),
                ),
            ],
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            bot = self._get_bot()
            msg = await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                reply_markup=keyboard,
            )
            return msg.message_id
        except Exception as e:
            raise TelegramError(f"Failed to send proposal: {e}") from e

    async def send_project_picker(
        self, task_id: str, projects: list[tuple[str, str]]
    ) -> int:
        """Send a project selection keyboard. projects = [(name, slug)]"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        short_id = task_id.replace("-", "")
        buttons = []
        for name, slug in projects:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=name,
                        callback_data=ProjectSelectPayload(
                            task_id=short_id, project_slug=slug
                        ).encode(),
                    )
                ]
            )
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        try:
            bot = self._get_bot()
            msg = await bot.send_message(
                chat_id=self._chat_id,
                text="Select a project:",
                reply_markup=keyboard,
            )
            return msg.message_id
        except Exception as e:
            raise TelegramError(f"Failed to send project picker: {e}") from e

    async def send_kind_picker(self, task_id: str) -> int:
        """Send a task kind selection keyboard."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        short_id = task_id.replace("-", "")
        buttons = []
        for kind in TaskKind:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=KIND_LABELS.get(kind, kind.value),
                        callback_data=KindSelectPayload(
                            task_id=short_id, kind=kind.value
                        ).encode(),
                    )
                ]
            )
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        try:
            bot = self._get_bot()
            msg = await bot.send_message(
                chat_id=self._chat_id,
                text="Select task type:",
                reply_markup=keyboard,
            )
            return msg.message_id
        except Exception as e:
            raise TelegramError(f"Failed to send kind picker: {e}") from e

    async def send_text(self, text: str) -> int:
        try:
            bot = self._get_bot()
            msg = await bot.send_message(chat_id=self._chat_id, text=text)
            return msg.message_id
        except Exception as e:
            raise TelegramError(f"Failed to send text: {e}") from e

    async def edit_message_text(
        self, message_id: int, text: str, reply_markup=None
    ) -> None:
        try:
            bot = self._get_bot()
            await bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.warning("edit_message_text failed", error=str(e))

    async def delete_message(self, message_id: int) -> None:
        try:
            bot = self._get_bot()
            await bot.delete_message(chat_id=self._chat_id, message_id=message_id)
        except Exception as e:
            logger.warning("delete_message failed", error=str(e))
