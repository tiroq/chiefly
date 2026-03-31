from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from apps.api.services.model_settings_service import EffectiveLLMConfig
from apps.api.telegram.commands import cmd_settings


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
    }


def _llm_config(**overrides) -> EffectiveLLMConfig:
    defaults = dict(
        provider="github_models",
        model="openai/gpt-4o",
        api_key="ghp_test",
        base_url="",
        fast_model="",
        quality_model="",
        fallback_model="",
        auto_mode=False,
    )
    defaults.update(overrides)
    return EffectiveLLMConfig(**defaults)


def _apply_patches(user_settings: dict, llm_config: EffectiveLLMConfig) -> ExitStack:
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


@pytest.mark.asyncio
async def test_settings_shows_llm_section():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(provider="github_models", model="openai/gpt-4o")
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = (
        msg.answer.call_args[0][0] if msg.answer.call_args[0] else msg.answer.call_args[1]["text"]
    )
    assert "<b>LLM:</b>" in text
    assert "github_models" in text
    assert "openai/gpt-4o" in text
    assert "Auto-mode: OFF" in text


@pytest.mark.asyncio
async def test_settings_auto_mode_on_shows_fast_quality():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(
        auto_mode=True,
        fast_model="openai/gpt-4o-mini",
        quality_model="openai/gpt-4o",
    )
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Auto-mode: ON" in text
    assert "Fast model: openai/gpt-4o-mini" in text
    assert "Quality model: openai/gpt-4o" in text


@pytest.mark.asyncio
async def test_settings_auto_mode_off_hides_fast_quality():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(
        auto_mode=False,
        fast_model="openai/gpt-4o-mini",
        quality_model="openai/gpt-4o",
    )
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Auto-mode: OFF" in text
    assert "Fast model" not in text
    assert "Quality model" not in text


@pytest.mark.asyncio
async def test_settings_fallback_model_shown_when_set():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(fallback_model="openai/gpt-4o-mini")
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Fallback model: openai/gpt-4o-mini" in text


@pytest.mark.asyncio
async def test_settings_fallback_model_hidden_when_empty():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(fallback_model="")
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Fallback model" not in text


@pytest.mark.asyncio
async def test_settings_provider_not_set():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config(provider="", model="")
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "Provider: (not set)" in text
    assert "Model: (not set)" in text


@pytest.mark.asyncio
async def test_settings_shows_admin_nav_hint():
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()

    cfg = _llm_config()
    with _apply_patches(_base_user_settings(), cfg):
        await cmd_settings(msg)

    text = msg.answer.call_args[0][0]
    assert "/admin/model-settings" in text
