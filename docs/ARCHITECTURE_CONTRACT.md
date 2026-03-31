# Architecture Contract

Pipeline:
Google Tasks → Sync → DB → Processing → Telegram → Mutation → History

Layers:

Sync:
- read only
- detect changes
- mark queue

Processing:
- one task at a time
- LLM usage
- create proposal

Review:
- Telegram UI
- confirm/edit/discard

Mutation:
- apply changes to Google Tasks
- save before/after

Admin:
- visibility
- prompt versions
- rollback

Mini App:
- React SPA at /app/ (port 8000)
- API at /api/app/ (port 8000)
- auth via Telegram WebApp init data HMAC
- actions update review sessions same as Telegram callbacks

Port Split:
- 8000: public (health, webhook, mini app, scheduler-dependent admin routes)
- 8001: admin (HTMX UI, admin API, internal only)
- shared DB, shared config, shared services

Forbidden:
- sync calling LLM
- DB as task truth
- Telegram spam
- admin UI on public port
