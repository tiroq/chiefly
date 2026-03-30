# Chiefly

**AI Chief of Staff for task intake and execution.**

Chiefly turns a messy Google Tasks inbox into organized, prioritized execution by using an LLM to classify tasks, routing them to the right project, and letting you review everything in Telegram.

---

## What is Chiefly?

You dump anything into a Google Tasks list called **Inbox** — rough notes, voice-to-text entries, multilingual fragments, half-formed ideas. Chiefly picks them up, makes sense of them with an LLM, and asks you to confirm the interpretation in Telegram. Once confirmed, the task is moved to the right project list. A daily review keeps you on top of what's in flight.

---

## MVP Scope

- ✅ Poll Google Tasks Inbox list
- ✅ Detect new unprocessed tasks (idempotent)
- ✅ LLM classification (kind, title, project, next action, substeps)
- ✅ Telegram proposal card with inline action buttons
- ✅ User actions: Confirm / Edit / Change Project / Change Type / Show Steps / Discard
- ✅ On confirm: move task to correct Google Tasks list, patch title
- ✅ Full revision history per task
- ✅ Daily review summary sent via Telegram
- ✅ FastAPI health + admin endpoints
- ✅ Background scheduler (APScheduler)
- ✅ Postgres with Alembic migrations
- ✅ pytest tests for state machine, routing, LLM schema, intake flow, callbacks, daily review

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                      FastAPI App                        │
│  /health  /telegram/webhook  /admin                     │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   Background Jobs   │  (APScheduler)
              │  sync_worker        │  Poll Google Tasks
              │  processing_worker  │  LLM classify + queue
              │  daily_review_worker│  Daily summary
              └──────────┬──────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
  GoogleTasks        LLMService      TelegramService
  Service (Google    (OpenAI-       (aiogram 3.x)
  Tasks API)         compatible)
        │                │                │
        └────────────────┼────────────────┘
                         ▼
              ┌──────────────────────┐
              │  ClassificationSvc  │  LLM + routing
              │  ReviewQueueService │  Telegram queue
              │  ProjectRoutingSvc  │  Project matching
              │  RevisionService    │  History
              │  DailyReviewService │  Daily summary
              └──────────┬───────────┘
                         │
              ┌──────────▼───────────┐
              │      Postgres DB     │
              │   SQLAlchemy 2.x     │
              │   Alembic Migrations │
              └──────────────────────┘
```

### Core Domain

| Enum | Values |
|------|--------|
| `TaskKind` | TASK, WAITING, COMMITMENT, IDEA, REFERENCE |
| `TaskStatus` | NEW → PROPOSED → CONFIRMED → ROUTED → COMPLETED / DISCARDED / ERROR |
| `ReviewAction` | CONFIRM, EDIT, CHANGE_PROJECT, CHANGE_TYPE, DISCARD, SHOW_STEPS |
| `ProjectType` | CLIENT, PERSONAL, FAMILY, OPS, WRITING, INTERNAL |
| `ConfidenceBand` | LOW, MEDIUM, HIGH |

---

## Setup Instructions

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- A Telegram bot (create via [@BotFather](https://t.me/BotFather))
- Google Cloud project with Tasks API enabled
- An LLM API key (OpenAI or compatible)

### 1. Clone and Install

```bash
git clone https://github.com/tiroq/chiefly.git
cd chiefly
pip install -e ".[dev]"
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `APP_ENV` | `development` or `production` |
| `DATABASE_URL` | PostgreSQL async URL |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your personal Telegram chat ID |
| `GOOGLE_CREDENTIALS_FILE` | Path to Google service account JSON |
| `GOOGLE_TASKS_INBOX_LIST_ID` | Google Tasks list ID for inbox |
| `LLM_PROVIDER` | `openai` (or compatible) |
| `LLM_MODEL` | e.g. `gpt-4o` |
| `LLM_API_KEY` | Your LLM API key |
| `INBOX_POLL_INTERVAL_SECONDS` | Polling interval (default: 60) |
| `DAILY_REVIEW_CRON` | Cron expression (default: `0 9 * * *`) |
| `TIMEZONE` | Your timezone (e.g. `Europe/Moscow`) |

### 3. Google Tasks Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Google Tasks API**
3. Create a **Service Account** and download the JSON credentials
4. Share your Google Tasks with the service account email (or use OAuth2)
5. Get your Inbox list ID:
   ```bash
   python -c "
   from apps.api.services.google_tasks_service import GoogleTasksService
   svc = GoogleTasksService('path/to/credentials.json')
   for tl in svc.list_tasklists():
       print(tl['id'], tl['title'])
   "
   ```

### 4. Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather), create a bot, get the token
2. Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot)
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

For webhook mode (production), set your webhook URL:
```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourapp.com/telegram/webhook
```

---

## Run Locally

### With Docker Compose

```bash
# Production mode
make docker-up
make migrate
make seed

# Development mode with hot reload
make docker-dev
# View logs: make docker-dev-logs
# Stop: make docker-dev-stop
```

### Without Docker (Local Python Dev Server)

```bash
# Start Postgres
# Then:
make migrate
make seed
make dev
```

The `make dev` command starts the API server with **hot reload** enabled — any changes to Python files in `apps/`, `core/`, or `db/` will automatically restart the server.

### Hot Reload Reference

For detailed hot reload setup, troubleshooting, and best practices, see [docs/HOT_RELOAD.md](docs/HOT_RELOAD.md).

---

## Migrations

```bash
# Apply all migrations
make migrate

# Create a new migration
make migrate-create name="add_new_field"
```

---

## Run Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests only
make test-integration
```

---

## Admin Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness check |
| GET | `/health/ready` | Readiness check (DB ping) |
| GET | `/admin/tasks/{task_id}` | Get task by ID |
| GET | `/admin/reviews/latest` | Get latest daily review |
| POST | `/admin/poll-inbox-now` | Trigger inbox poll manually |
| POST | `/admin/send-review-now` | Trigger daily review manually |

---

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Help text |
| `/inbox` | Show pending proposals |
| `/today` | Show active tasks |
| `/projects` | List configured projects |
| `/review` | Generate and send daily review now |
| `/stats` | Task counts by status |
| `/pause` | Toggle review queue pause on/off |
| `/next` | Send next queued proposal |
| `/backlog` | Show queue status and pending items |

---

## Future Roadmap

- [ ] OAuth2 Google auth (instead of service account)
- [ ] Google Calendar integration for scheduling tasks
- [ ] Multi-user support
- [ ] Web dashboard (read-only)
- [ ] Voice message intake via Telegram
- [ ] Notion / Linear integration as alternative backends
- [ ] LLM streaming response
- [ ] Recurring task detection
- [ ] Smart due date inference from context

