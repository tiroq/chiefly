from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@patch("apps.api.workers.sync_worker.get_session_factory")
@patch("apps.api.workers.sync_worker.AlertService")
@patch("apps.api.workers.sync_worker.TaskChangeMonitor")
@patch("apps.api.workers.sync_worker.SyncService")
@patch("apps.api.workers.sync_worker.TelegramService")
@patch("apps.api.workers.sync_worker.GoogleTasksService")
@patch("apps.api.workers.sync_worker.get_settings")
@pytest.mark.asyncio
async def test_run_sync_sends_summary_message_when_sync_has_updates(
    mock_get_settings,
    mock_google_tasks_cls,
    mock_telegram_cls,
    mock_sync_service_cls,
    mock_change_monitor_cls,
    mock_alert_service_cls,
    mock_get_session_factory,
):
    from apps.api.workers.sync_worker import run_sync

    settings = MagicMock(
        google_credentials_file="credentials.json",
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        google_tasks_inbox_list_id="inbox-list-id",
    )
    mock_get_settings.return_value = settings

    telegram = MagicMock()
    telegram.send_text = AsyncMock()
    telegram.aclose = AsyncMock()
    mock_telegram_cls.return_value = telegram

    mock_google_tasks_cls.return_value = MagicMock()

    sync_service = MagicMock()
    sync_service.sync_inbox = AsyncMock(return_value=2)
    mock_sync_service_cls.return_value = sync_service

    change_monitor = MagicMock()
    change_monitor.capture_baseline = AsyncMock()
    change_monitor.detect_changes = AsyncMock(return_value=[])
    change_monitor.log_all_changes = AsyncMock()
    mock_change_monitor_cls.return_value = change_monitor

    alert_service = MagicMock()
    alert_service.alert_task_changes = AsyncMock()
    mock_alert_service_cls.return_value = alert_service

    session = MagicMock()
    session.rollback = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_session_factory.return_value = MagicMock(return_value=ctx)

    await run_sync()

    telegram.send_text.assert_awaited_once_with(
        "🔄 Sync complete: 2 task(s) synced, 0 change(s) detected."
    )
