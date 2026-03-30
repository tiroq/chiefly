from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.sync_service import SyncCycleSummary


def _make_summary(
    tasklists_scanned: int = 3,
    tasks_scanned: int = 10,
    new_count: int = 2,
    updated_count: int = 1,
    moved_count: int = 0,
    deleted_count: int = 0,
) -> SyncCycleSummary:
    summary = SyncCycleSummary(
        tasklists_scanned=tasklists_scanned,
        tasks_scanned=tasks_scanned,
        new_count=new_count,
        updated_count=updated_count,
        moved_count=moved_count,
        deleted_count=deleted_count,
        queued_count=new_count + updated_count + moved_count,
    )
    return summary


@patch("apps.api.workers.sync_worker.get_session_factory")
@patch("apps.api.workers.sync_worker.SystemEventRepo")
@patch("apps.api.workers.sync_worker.ProjectRepository")
@patch("apps.api.workers.sync_worker.ProjectSyncService")
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
    mock_project_sync_cls,
    mock_project_repo_cls,
    mock_event_repo_cls,
    mock_get_session_factory,
):
    from apps.api.workers.sync_worker import run_sync

    settings = MagicMock(
        google_credentials_file="credentials.json",
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        google_tasks_inbox_list_id="inbox-list",
        default_tasklist_id="inbox-list",
    )
    mock_get_settings.return_value = settings

    telegram = MagicMock()
    telegram.send_text = AsyncMock()
    telegram.aclose = AsyncMock()
    mock_telegram_cls.return_value = telegram

    mock_google_tasks_cls.return_value = MagicMock()

    project_sync = MagicMock()
    project_sync.sync_from_google = AsyncMock(
        return_value={"created": [], "updated": [], "deactivated": [], "skipped": []}
    )
    mock_project_sync_cls.return_value = project_sync

    summary = _make_summary(tasklists_scanned=3, tasks_scanned=10, new_count=2, updated_count=1)
    sync_service = MagicMock()
    sync_service.sync_all = AsyncMock(return_value=summary)
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

    sync_service.sync_all.assert_awaited_once()
    telegram.send_text.assert_awaited_once()
    msg = telegram.send_text.await_args[0][0]
    assert "3 list(s) scanned" in msg
    assert "10 task(s) seen" in msg
    assert "2 new" in msg
    assert "1 updated" in msg


@patch("apps.api.workers.sync_worker.get_session_factory")
@patch("apps.api.workers.sync_worker.SystemEventRepo")
@patch("apps.api.workers.sync_worker.ProjectRepository")
@patch("apps.api.workers.sync_worker.ProjectSyncService")
@patch("apps.api.workers.sync_worker.AlertService")
@patch("apps.api.workers.sync_worker.TaskChangeMonitor")
@patch("apps.api.workers.sync_worker.SyncService")
@patch("apps.api.workers.sync_worker.TelegramService")
@patch("apps.api.workers.sync_worker.GoogleTasksService")
@patch("apps.api.workers.sync_worker.get_settings")
@pytest.mark.asyncio
async def test_run_sync_no_message_when_nothing_changed(
    mock_get_settings,
    mock_google_tasks_cls,
    mock_telegram_cls,
    mock_sync_service_cls,
    mock_change_monitor_cls,
    mock_alert_service_cls,
    mock_project_sync_cls,
    mock_project_repo_cls,
    mock_event_repo_cls,
    mock_get_session_factory,
):
    from apps.api.workers.sync_worker import run_sync

    settings = MagicMock(
        google_credentials_file="credentials.json",
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        google_tasks_inbox_list_id="inbox-list",
        default_tasklist_id="inbox-list",
    )
    mock_get_settings.return_value = settings

    telegram = MagicMock()
    telegram.send_text = AsyncMock()
    telegram.aclose = AsyncMock()
    mock_telegram_cls.return_value = telegram

    mock_google_tasks_cls.return_value = MagicMock()

    project_sync = MagicMock()
    project_sync.sync_from_google = AsyncMock(
        return_value={"created": [], "updated": [], "deactivated": [], "skipped": []}
    )
    mock_project_sync_cls.return_value = project_sync

    summary = _make_summary(
        tasklists_scanned=5,
        tasks_scanned=30,
        new_count=0,
        updated_count=0,
        moved_count=0,
        deleted_count=0,
    )
    sync_service = MagicMock()
    sync_service.sync_all = AsyncMock(return_value=summary)
    mock_sync_service_cls.return_value = sync_service

    change_monitor = MagicMock()
    change_monitor.capture_baseline = AsyncMock()
    change_monitor.detect_changes = AsyncMock(return_value=[])
    change_monitor.log_all_changes = AsyncMock()
    mock_change_monitor_cls.return_value = change_monitor

    alert_service = MagicMock()
    mock_alert_service_cls.return_value = alert_service

    session = MagicMock()
    session.rollback = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_get_session_factory.return_value = MagicMock(return_value=ctx)

    await run_sync()

    telegram.send_text.assert_not_awaited()
