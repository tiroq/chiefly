from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.main import _build_telegram_dispatcher


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edit_text = AsyncMock()


def _get_callback_handler(dp, name: str):
    for handler in dp.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler not found: {name}")


@pytest.mark.asyncio
async def test_discard_requires_confirmation_before_discarding():
    settings = MagicMock(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        google_credentials_file="creds.json",
    )
    with (
        patch("apps.api.main.get_settings", return_value=settings),
        patch("aiogram.types.Message", _FakeMessage),
    ):
        dp = _build_telegram_dispatcher()

    handle_discard = _get_callback_handler(dp, "handle_discard")
    task_id = "12345678123456781234567812345678"
    message = _FakeMessage(
        "🤖 <b>Chiefly detected a new inbox item</b>\n📌 <b>Proposed:</b>\n  Title: Buy milk"
    )
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
    text = args[0] if args else kwargs["text"]
    assert "⚠️ Discard this task?" in text
    assert "Buy milk" in text

    markup = kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == f"discard_confirm:{task_id}"
    assert markup.inline_keyboard[0][1].callback_data == f"discard_cancel:{task_id}"


@pytest.mark.asyncio
async def test_discard_cancel_answers_cancelled():
    settings = MagicMock(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        google_credentials_file="creds.json",
    )
    with patch("apps.api.main.get_settings", return_value=settings):
        dp = _build_telegram_dispatcher()

    handle_discard_cancel = _get_callback_handler(dp, "handle_discard_cancel")
    callback = SimpleNamespace(
        data="discard_cancel:123",
        answer=AsyncMock(),
    )

    await handle_discard_cancel(callback)

    callback.answer.assert_awaited_once_with("Cancelled")
