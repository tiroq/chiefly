# Product Contract

Chiefly is an AI Chief of Staff.

NOT:
- task manager
- chatbot
- CRUD system

Purpose:
- interpret inbox tasks
- classify and route
- confirm via Telegram
- maintain history
- provide reviews

Source of truth:
Google Tasks ONLY.

DB stores:
- history
- queue
- sessions
- events
- project metadata

Core loop:
Inbox → Sync → Queue → Process → Telegram → Confirm → Apply → History

UX goals:
- no spam
- clarity
- fast decisions
