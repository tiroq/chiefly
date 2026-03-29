FROM python:3.12-slim

WORKDIR /app

# Install system CA certificates so SSL verification works inside the container
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

# --- Dependency layer ---
# Copy only pyproject.toml first so this layer is cached until deps change.
COPY pyproject.toml .
ARG INSTALL_DEV=false
# Install all third-party deps declared in pyproject.toml (no local package source needed).
RUN python3 -c "
import tomllib, subprocess, sys
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
deps = list(data['project']['dependencies'])
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps, check=True)
" && \
    if [ "$INSTALL_DEV" = "true" ]; then \
        python3 -c "
import tomllib, subprocess, sys
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
dev_deps = data['project'].get('optional-dependencies', {}).get('dev', [])
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + dev_deps, check=True)
"; fi

# --- Source layer ---
# Invalidated on code changes, but no network I/O (deps already installed above).
COPY apps/ apps/
COPY core/ core/
COPY db/ db/
COPY . .
RUN pip install --no-cache-dir --no-deps .

# Use ARG to determine if hot reload should be enabled
ARG ENABLE_RELOAD=false
CMD if [ "$ENABLE_RELOAD" = "true" ] ; then \
      uvicorn apps.api.main:app --reload --reload-dir apps --reload-dir core --reload-dir db --host 0.0.0.0 --port 8000 --log-level debug ; \
    else \
      uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 ; \
    fi
