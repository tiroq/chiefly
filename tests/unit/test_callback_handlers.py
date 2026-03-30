from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from apps.api.telegram.callbacks import (
    handle_clarify,
    handle_edit,
    handle_queue_start,
    handle_setting_toggle,
    handle_skip,
)
from apps.api.telegram.states import ReviewStates


def _mock_async_session_cm():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_skip_marks_session_skipped_and_sends_next():
    review_session = SimpleNamespace(status="queued")
    message = MagicMock(spec=Message)
    message.text = "card"
    message.edit_text = AsyncMock()
    callback = SimpleNamespace(data="skip:abc123", message=message, answer=AsyncMock())

    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)
    session_repo = MagicMock()
    session_repo.save = AsyncMock()

    tg = MagicMock()
    tg.aclose = AsyncMock()
    queue_svc = MagicMock()
    queue_svc.send_next = AsyncMock(return_value=True)

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=factory),
        patch(
            "apps.api.telegram.callbacks.get_settings",
            return_value=SimpleNamespace(telegram_bot_token="token", telegram_chat_id="123"),
        ),
        patch("apps.api.telegram.callbacks.TelegramService", return_value=tg),
        patch("apps.api.telegram.callbacks.ReviewSessionRepository", return_value=session_repo),
        patch("apps.api.telegram.callbacks._get_review_session", return_value=review_session),
        patch("apps.api.telegram.callbacks._queue_service", return_value=queue_svc),
    ):
        await handle_skip(callback)

    assert review_session.status == "skipped"
    callback.answer.assert_awaited_once_with("⏭ Skipped.")
    queue_svc.send_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_clarify_shows_disambiguation_keyboard():
    message = MagicMock(spec=Message)
    message.edit_text = AsyncMock()
    callback = SimpleNamespace(data="clarify:abc123", message=message, answer=AsyncMock())

    review_session = SimpleNamespace(
        proposed_changes={
            "disambiguation_options": [
                {"kind": "task", "title": "Buy milk"},
                {"kind": "idea", "title": "Plan startup"},
            ]
        }
    )

    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=factory),
        patch("apps.api.telegram.callbacks._get_review_session", return_value=review_session),
    ):
        await handle_clarify(callback)

    message.edit_text.assert_awaited_once()
    kwargs = message.edit_text.await_args.kwargs
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "disambig:abc123:0"
    assert kwargs["reply_markup"].inline_keyboard[1][0].callback_data == "disambig:abc123:1"


@pytest.mark.asyncio
async def test_edit_sets_fsm_state():
    message = MagicMock(spec=Message)
    callback = SimpleNamespace(data="edit:abc123", message=message, answer=AsyncMock())
    state = MagicMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()

    review_session = SimpleNamespace(status="queued")
    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)
    session_repo = MagicMock()
    session_repo.save = AsyncMock()

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=factory),
        patch("apps.api.telegram.callbacks.ReviewSessionRepository", return_value=session_repo),
        patch("apps.api.telegram.callbacks._get_review_session", return_value=review_session),
    ):
        await handle_edit(callback, state)

    state.set_state.assert_awaited_once_with(ReviewStates.awaiting_title_edit)
    state.update_data.assert_awaited_once_with(task_id="abc123")


@pytest.mark.asyncio
async def test_toggle_bool_setting():
    message = MagicMock(spec=Message)
    message.text = "⚙️ <b>Settings</b>"
    message.edit_text = AsyncMock()
    callback = SimpleNamespace(data="setting:auto_next", message=message, answer=AsyncMock())

    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)
    updated = {
        "auto_next": False,
        "batch_size": 1,
        "paused": False,
        "sync_summary": True,
        "daily_brief": True,
        "show_confidence": True,
        "show_raw_input": True,
        "draft_suggestions": True,
        "ambiguity_prompts": True,
        "show_steps_auto": False,
    }

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=factory),
        patch(
            "apps.api.telegram.callbacks.toggle_bool_setting", new=AsyncMock(return_value=updated)
        ) as mock_toggle,
        patch("apps.api.telegram.callbacks.get_user_settings", new=AsyncMock(return_value=updated)),
    ):
        await handle_setting_toggle(callback)

    mock_toggle.assert_awaited_once_with(cm_session, "auto_next")
    message.edit_text.assert_awaited_once()
    reply_markup = message.edit_text.await_args.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Auto-next: OFF"


@pytest.mark.asyncio
async def test_queue_start_sends_next():
    callback = SimpleNamespace(data="queue:start", message=None, answer=AsyncMock())

    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)
    tg = MagicMock()
    tg.aclose = AsyncMock()
    queue_svc = MagicMock()
    queue_svc.send_next = AsyncMock(return_value=True)

    with (
        patch("apps.api.telegram.callbacks.get_session_factory", return_value=factory),
        patch(
            "apps.api.telegram.callbacks.get_settings",
            return_value=SimpleNamespace(telegram_bot_token="token", telegram_chat_id="123"),
        ),
        patch("apps.api.telegram.callbacks.TelegramService", return_value=tg),
        patch("apps.api.telegram.callbacks._queue_service", return_value=queue_svc),
    ):
        await handle_queue_start(callback)

    queue_svc.send_next.assert_awaited_once()
