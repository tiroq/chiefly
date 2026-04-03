"""
Unit tests for Telegram bot command handlers.

Covers: help text, settings display, draft removal regression.
"""
from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from apps.api.services.model_settings_service import EffectiveLLMConfig
from apps.api.telegram.commands import cmd_help, cmd_settings


def _mock_async_session_cm():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _base_user_settings() -> dict:
    return {
        "auto_next": True,
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


def _llm_config() -> EffectiveLLMConfig:
    return EffectiveLLMConfig(
        provider="github_models",
        model="openai/gpt-4o",
        api_key="ghp_test",
        base_url="",
        fast_model="",
        quality_model="",
        fallback_model="",
        auto_mode=False,
    )


def _settings_patches(user_settings: dict, llm_config: EffectiveLLMConfig) -> ExitStack:
    stack = ExitStack()
    cm_session = _mock_async_session_cm()
    factory = MagicMock(return_value=cm_session)

    stack.enter_context(
        patch("apps.api.telegram.commands.get_session_factory", return_value=factory)
    )
    stack.enter_context(
        patch(
            "apps.api.services.user_settings_service.get_user_settings",
            new_callable=AsyncMock,
            return_value=user_settings,
        )
    )
    stack.enter_context(
        patch(
            "apps.api.services.model_settings_service.get_effective_llm_config",
            new_callable=AsyncMock,
            return_value=llm_config,
        )
    )
    stack.enter_context(
        patch("apps.api.telegram.commands.get_settings", return_value=SimpleNamespace())
    )
    stack.enter_context(patch("apps.api.telegram.commands.settings_keyboard", return_value=None))
    return stack


# ── /help command ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_help_does_not_mention_draft():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    await cmd_help(msg)

    text = msg.answer.call_args[0][0]
    assert "/draft" not in text
    assert "draft" not in text.lower()


@pytest.mark.asyncio
async def test_help_contains_core_commands():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    await cmd_help(msg)

    text = msg.answer.call_args[0][0]
    for cmd in ("/next", "/backlog", "/settings", "/pause", "/help"):
        assert cmd in text


# ── /settings command ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_does_not_show_draft_suggestions():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    with _settings_patches(_base_user_settings(), _llm_config()):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Draft suggestions" not in text
    assert "draft_suggestions" not in text


@pytest.mark.asyncio
async def test_settings_still_shows_ux_section():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    with _settings_patches(_base_user_settings(), _llm_config()):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "<b>UX:</b>" in text
    assert "Show confidence" in text
    assert "Ambiguity prompts" in text


# ── Draft command removed (negative regression) ───────────────────────────────


def test_cmd_draft_not_exported():
    """cmd_draft must not exist in the commands module after removal."""
    import apps.api.telegram.commands as commands_module

    assert not hasattr(commands_module, "cmd_draft"), (
        "cmd_draft should not exist in the bot commands module"
    )


def test_menu_draft_not_exported():
    """menu_draft (reply keyboard handler) must not exist after removal."""
    import apps.api.telegram.commands as commands_module

    assert not hasattr(commands_module, "menu_draft"), (
        "menu_draft should not exist in the bot commands module"
    )
