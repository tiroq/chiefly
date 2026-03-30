from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from apps.api.telegram.callbacks import handle_discard, handle_discard_cancel


@pytest.mark.asyncio
async def test_discard_requires_confirmation_before_discarding():
    task_id = "12345678123456781234567812345678"
    message = MagicMock(spec=Message)
    message.text = (
        "🤖 <b>Chiefly detected a new inbox item</b>\n📌 <b>Proposed:</b>\n  Title: Buy milk"
    )
    message.edit_text = AsyncMock()
    callback = SimpleNamespace(
        data=f"discard:{task_id}",
        message=message,
        answer=AsyncMock(),
    )

    await handle_discard(callback)

    callback.answer.assert_awaited_once_with("Are you sure?")
    message.edit_text.assert_awaited_once()
    await_args = message.edit_text.await_args
    assert await_args is not None
    args = await_args.args
    kwargs = await_args.kwargs
    text = args[0] if args else kwargs.get("text", "")
    assert "⚠️ Discard this task?" in text
    assert "Buy milk" in text

    reply_markup = kwargs.get("reply_markup")
    assert reply_markup is not None
    assert reply_markup.inline_keyboard[0][0].callback_data == f"discard_confirm:{task_id}"
    assert reply_markup.inline_keyboard[0][1].callback_data == f"discard_cancel:{task_id}"


@pytest.mark.asyncio
async def test_discard_cancel_shows_alert_when_session_not_found():
    from core.domain.exceptions import TaskNotFoundError

    callback = SimpleNamespace(
        data="discard_cancel:123",
        message=MagicMock(spec=Message),
        answer=AsyncMock(),
    )

    mock_session = AsyncMock()
    mock_factory = MagicMock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=mock_factory),
        patch(
            "apps.api.telegram.callbacks._get_review_session",
            side_effect=TaskNotFoundError("not found"),
        ),
    ):
        await handle_discard_cancel(callback)

    callback.answer.assert_awaited_once_with("Task not found!", show_alert=True)
