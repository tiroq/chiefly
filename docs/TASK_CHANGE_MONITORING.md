# Task Change Monitoring System

## Overview

A comprehensive task change monitoring system that detects and alerts on **all task modifications** across all projects during background pull operations (inbox polling and project syncing).

## Architecture

### Components

#### 1. **TaskChangeMonitor** ([apps/api/services/task_change_monitor.py](apps/api/services/task_change_monitor.py))

Core monitoring service that:
- Captures baseline snapshots of all tasks **before** pull operations
- Compares state **after** operations to detect changes
- Categorizes changes by type (created, updated, moved, status changed, etc.)
- Logs all changes to SystemEvent database

**Key Methods:**
- `capture_baseline()` - Capture task state before operations
- `detect_changes()` - Compare and detect all modifications
- `log_all_changes()` - Record changes to SystemEvent
- `get_changes_summary()` - Get count breakdown of change types
- `get_changes_by_project()` - Group changes by project

**Change Types Detected:**
- `TASK_CREATED` - New task was added
- `TASK_UPDATED` - General task update
- `TASK_MOVED_TO_PROJECT` - Task moved to different project
- `TASK_STATUS_CHANGED` - Task status changed
- `TASK_MARKED_COMPLETED` - Task marked as completed
- `TASK_PROPERTIES_CHANGED` - Title, kind, or confidence changed

#### 2. **AlertService** ([apps/api/services/alert_service.py](apps/api/services/alert_service.py))

Handles notifications and alerts for task changes:
- Sends Telegram notifications with formatted summaries
- Groups changes by operation type
- Provides emoji-enhanced formatting for readability
- Handles both batch alerts (multiple changes) and single task alerts

**Key Methods:**
- `alert_task_changes()` - Send alert for multiple changes
- `alert_task_created()` - Alert for task creation
- `alert_task_updated()` - Alert for task update
- `get_alert_template_for_project()` - Format alerts by project

#### 3. **Enhanced Workers**

**InboxPollWorker** ([apps/api/workers/inbox_poll_worker.py](apps/api/workers/inbox_poll_worker.py))
- Captures baseline before polling inbox
- Detects all changes after intake processing
- Logs changes to SystemEvent
- Sends Telegram alerts about detected changes

**ProjectSyncWorker** ([apps/api/workers/project_sync_worker.py](apps/api/workers/project_sync_worker.py))
- Captures baseline before syncing projects
- Detects changes after sync operations
- Logs changes to SystemEvent
- Sends Telegram alerts about detected changes

#### 4. **Enhanced Repository**

**TaskItemRepository** ([db/repositories/task_item_repo.py](db/repositories/task_item_repo.py))
- Added `list_all()` method to retrieve all tasks for baseline comparison

## Usage Flow

### For Inbox Poll Operations

```
1. run_inbox_poll() triggered by scheduler
   ↓
2. TaskChangeMonitor.capture_baseline()
   → Snapshot all current tasks
   ↓
3. IntakeService.poll_and_process()
   → Process new inbox items
   → Create/update TaskItems
   ↓
4. TaskChangeMonitor.detect_changes()
   → Compare before/after snapshots
   → Identify: created tasks, updated tasks, moved tasks
   ↓
5. TaskChangeMonitor.log_all_changes()
   → Create SystemEvent entries for each change
   ↓
6. AlertService.alert_task_changes()
   → Send Telegram notification with summary
   ↓
7. User receives alert about all changes
```

### For Project Sync Operations

```
1. run_project_sync() triggered by scheduler
   ↓
2. TaskChangeMonitor.capture_baseline()
   → Snapshot all current tasks
   ↓
3. ProjectSyncService.sync_from_google()
   → Sync Google Tasklists to Projects
   → Update project assignments
   ↓
4. TaskChangeMonitor.detect_changes()
   → Identify: new projects, moved tasks, updated tasks
   ↓
5. TaskChangeMonitor.log_all_changes()
   → Create SystemEvent entries
   ↓
6. AlertService.alert_task_changes()
   → Send Telegram alert
   ↓
7. Dashboard and UI updated with recent events
```

## Example Alert Message

When changes are detected, users receive a Telegram message like:

```
🔔 Task Changes Detected
From inbox_poll operation

📝 Task Created: 2
✏️ Task Updated: 1
✅ Task Marked Completed: 1

📊 Total Changes: 4
⏰ 2026-03-21 14:30:45 UTC

Recent items:
📝 1. Review quarterly report
📝 2. Schedule team meeting  
✏️ 3. Update project documentation
… and 1 more
```

## Database Schema

### SystemEvent Table

All changes are logged with:
- `event_type` - Type of change (e.g., "task_created", "task_moved_to_project")
- `severity` - "info", "warning", or "error"
- `subsystem` - "task_monitor"
- `stable_id` - Link to affected task
- `project_id` - Link to affected project
- `message` - Human-readable description
- `payload_json` - Detailed change information including before/after snapshots
- `created_at` - Timestamp  

**Query Examples:**

```python
# Get all task creation events
events = await system_event_repo.list_events(event_type="task_created")

# Get all changes for a specific task
events = await system_event_repo.list_events(stable_id=task_id)

# Get all changes for a specific project
events = await system_event_repo.list_events(project_id=project_id)

# Get summary of events by type in past 24 hours
events = await system_event_repo.list_events_since(hours=24)
```

## Configuration

Monitoring operates automatically with no configuration needed. To customize:

### Telegram Notifications
- Configure Telegram bot token: `TELEGRAM_BOT_TOKEN`
- Configure chat ID: `TELEGRAM_CHAT_ID`

### Polling Intervals
- Sync interval: `SYNC_INTERVAL_SECONDS` (default: 60 seconds; legacy `INBOX_POLL_INTERVAL_SECONDS` also accepted)
- Project sync interval: `PROJECT_SYNC_CRON` (default: hourly)

## Monitoring Capabilities

### What Gets Monitored ✅

- ✅ Tasks created during inbox polling
- ✅ Tasks created/updated during project sync
- ✅ Task property changes (title, kind, confidence)
- ✅ Task status transitions (NEW → PROPOSED → CONFIRMED → ROUTED etc.)
- ✅ Task project assignments (moved between projects)
- ✅ Bulk operations (multiple changes tracked individually)

### Tracking Features ✅

- ✅ Complete before/after snapshots stored in SystemEvent
- ✅ Changes grouped by project for easier analysis
- ✅ Change summaries with counts by type
- ✅ Timestamps on all changes
- ✅ Queryable via SystemEventRepo

### Alerting Features ✅

- ✅ Real-time Telegram notifications
- ✅ Emoji-enhanced formatted messages
- ✅ Multi-change summaries with examples
- ✅ Single-change detailed alerts
- ✅ Project-grouped alert templates

## Example Code Usage

### Manual Change Monitoring (if needed outside workers)

```python
from apps.api.services.task_change_monitor import TaskChangeMonitor
from apps.api.services.alert_service import AlertService
from db.session import get_session_factory

# Create monitor
factory = get_session_factory()
async with factory() as session:
    monitor = TaskChangeMonitor(session)
    alert_service = AlertService(telegram, session)
    
    # Capture before state
    await monitor.capture_baseline()
    
    # ... perform operations that modify tasks ...
    
    # Detect changes
    changes = await monitor.detect_changes()
    
    # Log changes
    await monitor.log_all_changes()
    
    # Send alerts
    await alert_service.alert_task_changes(changes, operation="custom")
    
    # Get summary
    summary = monitor.get_changes_summary()
    # Output: {'task_created': 2, 'task_updated': 1, ...}
```

### Query Changes from Database

```python
from db.repositories.system_event_repo import SystemEventRepo

repo = SystemEventRepo(session)

# Get all changes in last hour
recent_changes = await repo.list_events(
    event_type="task_created",  # Optional: filter by type
)

# Count changes by type
all_events = await repo.list_events()
change_counts = {}
for event in all_events:
    change_counts[event.event_type] = change_counts.get(event.event_type, 0) + 1
```

## Benefits

1. **Complete Visibility** - No task changes go unnoticed
2. **Audit Trail** - Full history of system changes in SystemEvent
3. **Proactive Alerts** - Users notified immediately of important changes
4. **Project-Level Tracking** - Group changes by project for analysis
5. **Change Categories** - Understand what type of change occurred
6. **Automated Logging** - All changes logged automatically without manual intervention
7. **Queryable History** - Full SystemEvent database queryable by type, project, task, time

## Testing

To test the monitoring system:

1. **Unit Tests** - Test TaskChangeMonitor snapshot and comparison logic
2. **Integration Tests** - Test with actual workers during polling/sync
3. **Manual Testing** - Trigger inbox poll or project sync and observe:
   - SystemEvent entries created
   - Telegram notification received
   - Dashboard updated with recent events

## Future Enhancements

- [ ] Batch processing optimizations for large change sets
- [ ] SMS/Email notification options beyond Telegram
- [ ] Webhooks for external system integration
- [ ] Change diff visualization in admin UI
- [ ] Configurable alert thresholds (alert only when X changes detected)
- [ ] Change rollback capability
- [ ] Change impact analysis (dependencies, affected workflows)
