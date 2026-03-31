# Deployment

Chiefly runs as two separate processes sharing the same database.

## Port Layout

| Port | App | Exposure | Purpose |
|------|-----|----------|---------|
| 8000 | Public | Cloudflare Tunnel | Health, Telegram webhook, Mini App API + SPA, scheduler-dependent admin routes |
| 8001 | Admin | Internal only | HTMX admin panel, admin API |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_HOST` | `127.0.0.1` | Admin app bind address |
| `ADMIN_PORT` | `8001` | Admin app port |
| `MINI_APP_URL` | (empty) | Site origin for Mini App WebApp buttons (e.g., `https://chiefly.tiroq.dev`). Leave empty to disable Mini App buttons in Telegram. |

## Running

### Docker Compose (Production)

```bash
make docker-up    # Starts both api and admin services
make migrate
make seed
```

### Docker Compose (Development)

```bash
make docker-dev   # Starts both services with hot reload
```

### Local Development

```bash
make dev          # Public app on :8000
make admin        # Admin app on :8001 (separate terminal)
make miniapp-dev  # Mini App dev server with HMR (separate terminal)
```

### Mini App Build

```bash
make miniapp-build  # Builds React SPA to apps/miniapp/dist/
```

The public app serves the built SPA from `apps/miniapp/dist/` at `/app/`. If the dist directory doesn't exist, the SPA routes are skipped with a warning.

## Cloudflare Tunnel

Only port 8000 should be exposed via Cloudflare Tunnel. Port 8001 (admin) must remain internal.

Example `config.yml`:
```yaml
tunnel: your-tunnel-id
ingress:
  - hostname: chiefly.tiroq.dev
    service: http://localhost:8000
  - service: http_status:404
```

## Telegram Mini App Setup

1. Set `MINI_APP_URL` to your public domain (e.g., `https://chiefly.tiroq.dev`)
2. Build the Mini App: `make miniapp-build`
3. The "Open in App" button will appear on proposal cards in Telegram
4. The "Open Settings in App" button will appear on the settings keyboard

The Mini App URL must be HTTPS and match the domain configured in BotFather for WebApp.
