# Telegram UX Contract

Telegram = review interface.

Rules:
- one active task at a time
- no flooding

Commands:
/review
/next
/backlog
/pause
/settings

Card must show:
- raw input
- type
- project
- title
- next action
- confidence

Actions:
- confirm
- edit
- change project
- change type
- discard

## Settings Command

`/settings` displays current configuration including:
- LLM provider, model, auto mode status
- Fast/quality/fallback models (when auto mode is on)
- Link to admin panel for changes

No credential entry or provider switching through Telegram — admin panel only.
