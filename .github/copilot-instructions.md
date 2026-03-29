# Chiefly — Copilot Implementation Instructions

You are working on Chiefly, an AI Chief of Staff / execution assistant.

Before making changes, ALWAYS follow docs contracts.

Read:
- docs/PRODUCT_CONTRACT.md
- docs/ARCHITECTURE_CONTRACT.md
- docs/DATA_CONTRACT.md
- docs/LLM_CONTRACT.md
- docs/TELEGRAM_UX_CONTRACT.md
- docs/ADMIN_PANEL_CONTRACT.md
- docs/TESTING_CONTRACT.md
- docs/OPERATIONAL_RULES.md
- docs/IMPLEMENTATION_SEQUENCE.md
- docs/REVIEW_CHECKLIST.md

Core rules:
- Google Tasks = source of truth
- DB = history + control plane
- Sync and Processing MUST be decoupled
- Telegram must be sequential (no spam)
- Always add tests

Never:
- mix sync + processing
- store canonical tasks in DB
- bypass contracts

When implementing:
1. Explain impacted contracts
2. Implement
3. Add tests
4. Update docs if needed
