from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.api.services.review_pause import _reset_cache, is_review_paused


def test_is_review_paused_defaults_false_when_cache_empty():
    _reset_cache()
    assert is_review_paused() is False


@pytest.mark.asyncio
async def test_toggle_calls_repo_and_updates_cache():
    from apps.api.services.review_pause import toggle_review_pause

    _reset_cache()
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value="false")
    mock_repo.set = AsyncMock()

    with patch(
        "apps.api.services.review_pause.AppSettingRepository",
        return_value=mock_repo,
    ):
        result = await toggle_review_pause(mock_session)

    assert result is True
    assert is_review_paused() is True
    mock_repo.set.assert_awaited_once_with("review_paused", "true")
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_paused_calls_repo_and_updates_cache():
    from apps.api.services.review_pause import set_review_paused

    _reset_cache()
    mock_session = AsyncMock()
    mock_repo = AsyncMock()

    with patch(
        "apps.api.services.review_pause.AppSettingRepository",
        return_value=mock_repo,
    ):
        await set_review_paused(mock_session, True)

    assert is_review_paused() is True
    mock_repo.set.assert_awaited_once_with("review_paused", "true")
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_pause_state_populates_cache():
    from apps.api.services.review_pause import load_pause_state

    _reset_cache()
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value="true")

    with patch(
        "apps.api.services.review_pause.AppSettingRepository",
        return_value=mock_repo,
    ):
        result = await load_pause_state(mock_session)

    assert result is True
    assert is_review_paused() is True
