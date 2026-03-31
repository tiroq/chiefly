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

## Mini App Integration

Proposal cards include a "📱 Open in App" WebApp button when `MINI_APP_URL` is configured. The button opens the Mini App directly to the task review screen.

Settings command includes a "📱 Open Settings in App" WebApp button.

When a task is confirmed or discarded via Mini App:
- The original Telegram message keyboard is removed
- Status text is appended ("Confirmed via Mini App" / "Discarded via Mini App")

Rules:
- WebApp buttons only appear when MINI_APP_URL is set (non-empty)
- Mini App uses the same review session model as Telegram callbacks
- actor_id for Mini App actions is "miniapp" (vs "telegram" for inline buttons)
