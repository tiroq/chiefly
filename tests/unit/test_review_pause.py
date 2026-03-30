from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.main import _build_telegram_dispatcher
from apps.api.services.review_pause import (
    is_review_paused,
    set_review_paused,
    toggle_review_pause,
)


def _get_message_handler(dp, name: str):
    for handler in dp.message.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler not found: {name}")


def test_toggle_review_pause_behavior():
    set_review_paused(False)
    assert is_review_paused() is False

    assert toggle_review_pause() is True
    assert is_review_paused() is True

    assert toggle_review_pause() is False
    assert is_review_paused() is False


@pytest.mark.asyncio
async def test_pause_command_toggles_state_and_replies():
    set_review_paused(False)
    settings = MagicMock(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        google_credentials_file="creds.json",
    )

    with patch("apps.api.main.get_settings", return_value=settings):
        dp = _build_telegram_dispatcher()

    cmd_pause = _get_message_handler(dp, "cmd_pause")
    message = SimpleNamespace(answer=AsyncMock())

    await cmd_pause(message)
    await cmd_pause(message)

    message.answer.assert_any_await("⏸ Review queue paused. Send /pause again to resume.")
    message.answer.assert_any_await("▶️ Review queue resumed.")
    assert message.answer.await_count == 2
    assert is_review_paused() is False
