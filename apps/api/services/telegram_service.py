"""
Telegram service for sending messages and handling the bot.
"""

from __future__ import annotations

import html

from apps.api.logging import get_logger
from core.domain.exceptions import TelegramError
from core.schemas.llm import TaskClassificationResult
from core.domain.enums import TaskKind

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
    queue_position: int | None = None,
) -> str:
    conf_emoji = CONFIDENCE_EMOJI.get(classification.confidence, "⚪")
    kind_label = KIND_LABELS.get(classification.kind, classification.kind)

    # Escape all user/LLM-provided content before embedding in HTML
    safe_raw = html.escape(raw_text)
    safe_title = html.escape(classification.normalized_title)
    safe_project = html.escape(project_name) if project_name else "?"
    safe_next_action = (
        html.escape(classification.next_action) if classification.next_action else None
    )
    safe_due_hint = html.escape(classification.due_hint) if classification.due_hint else None

    lines = [
        "🤖 <b>Chiefly detected a new task to review</b>",
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
    if queue_position is not None:
        lines.append(f"📋 Queue position: {queue_position}")

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

    async def aclose(self) -> None:
        """Close the underlying aiohttp session opened by the Bot."""
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

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
        queue_position: int | None = None,
    ) -> int:
        """Send a task proposal card to Telegram with action buttons.

        Args:
            task_id: The stable ID of the task.
            raw_text: The original task text.
            classification: The LLM classification result.
            project_name: The name of the matched project.
            queue_position: Optional position in the review queue.

        Returns:
            int: The ID of the sent Telegram message.
        """
        from apps.api.telegram.keyboards import proposal_keyboard

        text = _build_proposal_text(
            raw_text,
            classification,
            project_name,
            queue_position=queue_position,
        )
        short_id = task_id.replace("-", "")
        keyboard = proposal_keyboard(short_id)

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

    async def send_text(self, text: str) -> int:
        """Send a plain text message to the configured Telegram chat.

        Args:
            text: The message content (HTML supported).

        Returns:
            int: The ID of the sent Telegram message.
        """
        try:
            bot = self._get_bot()
            msg = await bot.send_message(chat_id=self._chat_id, text=text)
            return msg.message_id
        except Exception as e:
            raise TelegramError(f"Failed to send text: {e}") from e

    async def edit_message_text(self, message_id: int, text: str, reply_markup=None) -> None:
        """Edit the text and keyboard of an existing Telegram message.

        Args:
            message_id: The ID of the message to edit.
            text: The new message content.
            reply_markup: The new inline keyboard (optional).
        """
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
        """Delete a specific message from the Telegram chat.

        Args:
            message_id: The ID of the message to delete.
        """
        try:
            bot = self._get_bot()
            await bot.delete_message(chat_id=self._chat_id, message_id=message_id)
        except Exception as e:
            logger.warning("delete_message failed", error=str(e))
