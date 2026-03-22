# Hot Reload Development Guide

This document explains how to use hot reload in development mode for the Chiefly application.

## Quick Start

### Using Task (Recommended)
```bash
task dev
```

### Using Make
```bash
make dev
```

### Using Python script
```bash
python scripts/dev_server.py
```

### Direct uvicorn
```bash
uvicorn apps.api.main:app --reload --reload-dir apps --reload-dir core --reload-dir db --host 0.0.0.0 --port 8000
```

## Docker Hot Reload

You can also run the development server with hot reload inside Docker. This is useful for testing with the exact same environment as production while still having automatic code reloading.

### Using Task (Recommended)
```bash
# Start all services with hot reload enabled
task docker:dev

# View logs
task docker:dev:logs

# Stop services
task docker:dev:stop

# Rebuild and restart
task docker:dev:rebuild
```

### Using Docker Compose directly
```bash
# Start with hot reload
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up

# In background
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d

# View logs
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs -f

# Stop services
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml down
```

### Docker Hot Reload Features

The Docker development setup includes:
- ✅ **Volume mounts** for `apps/`, `core/`, `db/` directories
- ✅ **Auto-reload** on file changes using uvicorn's `--reload` flag
- ✅ **Development dependencies** installed (`[dev]`)
- ✅ **Debug logging** enabled by default
- ✅ **Access logs** for HTTP requests
- ✅ **Postgres database** automatically set up and running

### How Volume Mounts Work

The `docker-compose.dev.yml` mounts your local source code into the container:

```yaml
volumes:
  - ../../../apps:/app/apps
  - ../../../core:/app/core
  - ../../../db:/app/db
```

When you edit a file locally, Docker sees the change immediately and uvicorn reloads automatically. No need to rebuild the image!

When you run the development server with the `--reload` flag, uvicorn:

1. **Watches file changes** in the specified directories (`apps`, `core`, `db`)
2. **Detects Python file modifications** using the `watchfiles` library
3. **Automatically restarts** the application server when files change
4. **Preserves state** during rapid iterations

The `--reload-dir` option specifies which directories to monitor (specify multiple times for multiple directories):
- `apps/` - API routes, services, and handlers
- `core/` - Domain models, schemas, and utilities
- `db/` - Database models and repositories

## File Change Detection

Hot reload will trigger on changes to:
- ✅ Python files (`.py`)
- ✅ Configuration files (imported during startup)
- ✅ Template files (if you're using Jinja2)

Hot reload will **NOT** trigger on:
- ❌ Static files (CSS, JS) - browser cache/refresh needed
- ❌ Environment variables in `.env` - restart required
- ❌ Database migrations - manual migration + restart required
- ❌ Poetry/pip dependencies - reinstall + restart required

## Accessing the Dev Server

Once running, access your application at:

- **API**: http://localhost:8000
- **Interactive API Docs (Swagger)**: http://localhost:8000/docs
- **Alternative API Docs (ReDoc)**: http://localhost:8000/redoc
- **Admin UI**: http://localhost:8000/admin/

## Common Scenarios

### Scenario 1: Modifying a Route Handler
```python
# apps/api/routes/health.py
@router.get("/")
async def health_check():
    return {"status": "ok"}  # Change this
```
→ **Hot reload triggers automatically** ✓

### Scenario 2: Modifying a Service
```python
# apps/api/services/classification_service.py
async def classify_task(self, task_text: str):
    # Modify logic here
    return result
```
→ **Hot reload triggers automatically** ✓

### Scenario 3: Modifying Database Model
```python
# db/models/task_item.py
class TaskItem(Base):
    # Add new column here
    new_field: Mapped[str]
```
→ **⚠️ Requires migration + manual restart**
```bash
task migrate  # Or: make migrate
# Then restart the dev server
```

### Scenario 4: Changing Environment Variables
```bash
# Edit .env file
# Change: LOG_LEVEL=info → LOG_LEVEL=debug
```
→ **⚠️ Requires manual restart**
```bash
# Stop current server (Ctrl+C)
# Start it again: task dev
```

### Scenario 5: Installing New Dependencies
```bash
# Add to pyproject.toml, then install
uv pip install -e '.[dev]'
# Or: pip install -e '.[dev]'
```
→ **⚠️ Requires manual restart**

## Customizing Hot Reload

### Watch Additional Directories
Edit `Taskfile.yml`:
```yaml
dev:
  cmds:
    - .venv/bin/uvicorn apps.api.main:app --reload --reload-dir apps --reload-dir core --reload-dir db --reload-dir custom_dir --host 0.0.0.0 --port 8000
```

### Disable Hot Reload (Run Normally)
```bash
# Remove the --reload flag
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

### Adjust Reload Delay
```bash
# Add delay to reload detection (useful if you have slow file systems)
uvicorn apps.api.main:app --reload --reload-delay 2 --host 0.0.0.0 --port 8000
```

### Change Log Level
```bash
# More verbose logging
uvicorn apps.api.main:app --reload --log-level debug --host 0.0.0.0 --port 8000

# Less verbose logging
uvicorn apps.api.main:app --reload --log-level error --host 0.0.0.0 --port 8000
```

## Troubleshooting

### Issue: Reload not detecting changes
**Solution**: Ensure files are saved. Some editors have "autosave" delays.

### Issue: Changes break the app, but server keeps running
**Solution**: Check the terminal output for error messages. Fix the Python syntax error and save - the server will auto-restart once the error is fixed.

### Issue: Port 8000 already in use
**Solution**: Either kill the previous process or use a different port:
```bash
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8001
```

### Issue: Import errors after file changes
**Solution**: This can happen due to circular imports. Check the error message in the terminal and restart the server:
```bash
# Ctrl+C to stop
# Then run: task dev
```

## Performance Tips

1. **Use a fast disk**: SSD much faster than HDD for file watching
2. **Limit watched directories**: Only watch what you need (already optimized)
3. **Close unnecessary files**: In your editor, close files you're not working on
4. **Consider dedicated terminal**: Keep the dev server in a separate terminal tab

## Development Workflow

### Best Practice Workflow
1. Open the dev server in one terminal: `task dev`
2. Edit code in your editor (e.g., VS Code)
3. Watch the terminal for automatic reload messages
4. Test in the browser or with curl/Postman
5. Make more changes - they reload automatically

### With Multiple Services
If you need to run the dev server AND other services (database, migrations, etc.):

```bash
# Terminal 1: Start Docker services
task docker:up

# Terminal 2: Run migrations (if needed)
task migrate

# Terminal 3: Start dev server
task dev
```

## Related Tasks

```bash
task install        # Install dependencies
task migrate        # Run database migrations
task test          # Run test suite
task docker:up     # Start Docker services
task docker:down   # Stop Docker services
```

## Learn More

- [Uvicorn Documentation](https://www.uvicorn.org/)
- [FastAPI Development Guide](https://fastapi.tiangolo.com/deployment/concepts/#development)
- [Watchfiles Documentation](https://watchfiles.helpmanual.io/)
