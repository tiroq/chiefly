from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import InlineKeyboardMarkup

from apps.api.services.telegram_service import TelegramService
from core.schemas.telegram import ProjectSelectPayload


class _Message:
    message_id: int

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class _BotMock:
    text: str

    def __init__(self) -> None:
        self.chat_id: str | None = None
        self.text = ""
        self.reply_markup: InlineKeyboardMarkup | None = None
        self.send_message: AsyncMock = AsyncMock(side_effect=self._send_message)

    async def _send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: InlineKeyboardMarkup,
    ) -> _Message:
        self.chat_id = chat_id
        self.text = text
        self.reply_markup = reply_markup
        return _Message(message_id=777)


class TestProjectSelectionUX:
    async def _send_project_picker(
        self,
        task_id: str,
        projects: list[tuple[str, str]],
        task_title: str | None = None,
        current_project: str | None = None,
        suggested_project: str | None = None,
    ) -> tuple[int, str, InlineKeyboardMarkup]:
        bot = _BotMock()
        service = TelegramService(bot_token="token", chat_id="chat-id")

        with patch.object(TelegramService, "_get_bot", return_value=bot):
            message_id = await service.send_project_picker(
                task_id=task_id,
                projects=projects,
                task_title=task_title,
                current_project=current_project,
                suggested_project=suggested_project,
            )

        assert bot.reply_markup is not None
        return message_id, bot.text, bot.reply_markup

    @pytest.mark.asyncio
    async def test_includes_task_current_and_suggested_context_lines(self):
        _, text, _ = await self._send_project_picker(
            task_id="abc-def",
            projects=[("Inbox", "inbox")],
            task_title="Prepare monthly report",
            current_project="Ops",
            suggested_project="Finance",
        )

        assert "Task: <i>Prepare monthly report</i>" in text
        assert "Current: <b>Ops</b>" in text
        assert "Suggested: Finance" in text

    @pytest.mark.asyncio
    async def test_uses_contextual_and_plain_button_labels(self):
        _, _, keyboard = await self._send_project_picker(
            task_id="abc-def",
            projects=[
                ("Ops", "ops"),
                ("Finance", "finance"),
                ("Inbox", "inbox"),
            ],
            current_project="Ops",
            suggested_project="Finance",
        )

        labels = [row[0].text for row in keyboard.inline_keyboard]
        assert "✓ Ops (current)" in labels
        assert "★ Finance (suggested)" in labels
        assert "Inbox" in labels

    @pytest.mark.asyncio
    async def test_without_optional_fields_shows_only_header(self):
        _, text, _ = await self._send_project_picker(
            task_id="abc-def",
            projects=[("Inbox", "inbox")],
        )

        assert text == "📁 <b>Select a project:</b>"

    @pytest.mark.asyncio
    async def test_escapes_html_entities_in_task_title(self):
        _, text, _ = await self._send_project_picker(
            task_id="abc-def",
            projects=[("Inbox", "inbox")],
            task_title="<script>alert('xss')</script> & <b>bold</b>",
        )

        assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in text
        assert "&lt;b&gt;bold&lt;/b&gt;" in text
        assert "<script>" not in text

    @pytest.mark.asyncio
    async def test_renders_all_projects_with_expected_callback_payloads(self):
        task_id = "123e4567-e89b-12d3-a456-426614174000"
        short_id = task_id.replace("-", "")
        projects = [("Ops", "ops"), ("Finance", "finance"), ("Inbox", "inbox")]

        message_id, _, keyboard = await self._send_project_picker(
            task_id=task_id,
            projects=projects,
        )

        assert message_id == 777
        assert len(keyboard.inline_keyboard) == len(projects)
        for row, (_, slug) in zip(keyboard.inline_keyboard, projects, strict=True):
            button = row[0]
            assert (
                button.callback_data
                == ProjectSelectPayload(
                    task_id=short_id,
                    project_slug=slug,
                ).encode()
            )
