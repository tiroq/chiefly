# Admin Panel Contract

Purpose:
- visibility
- prompt control
- debugging
- LLM provider and model configuration

Port: 8001 (internal only, not exposed via Cloudflare Tunnel)
Host: 127.0.0.1 (configurable via ADMIN_HOST)

Routes:
/admin
/admin/tasks
/admin/projects
/admin/events
/admin/model-settings

Must support:
- project metadata
- prompt versioning
- rollback
- logs

## Model Settings Page

Route: `/admin/model-settings`

Allows configuring:
- LLM provider (`openai`, `ollama`, `github_models`)
- API key
- Base URL
- Primary, fast, quality, and fallback models
- Auto mode toggle

Actions:
- Save — persists to DB via `model_settings_service`
- Test Connection — verifies LLM connectivity
- Reset — clears DB overrides, reverts to env defaults

Settings are persisted in the `app_settings` table as a JSON blob under key `model_settings`. DB settings take priority over `.env` values.
