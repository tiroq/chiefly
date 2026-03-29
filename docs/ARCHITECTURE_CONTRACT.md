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

Forbidden:
- sync calling LLM
- DB as task truth
- Telegram spam
