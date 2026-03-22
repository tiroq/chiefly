FROM python:3.12-slim

WORKDIR /app

# Install system CA certificates so SSL verification works inside the container
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy all source first so pip install has access to the package tree
COPY pyproject.toml .
COPY apps/ apps/
COPY core/ core/
COPY db/ db/

# Use ARG to determine install type (dev or prod)
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ] ; then \
      pip install --no-cache-dir -e '.[dev]' ; \
    else \
      pip install --no-cache-dir . ; \
    fi

# Copy remaining files (prompts, scripts, etc.)
COPY . .

# Use ARG to determine if hot reload should be enabled
ARG ENABLE_RELOAD=false
CMD if [ "$ENABLE_RELOAD" = "true" ] ; then \
      uvicorn apps.api.main:app --reload --reload-dir apps --reload-dir core --reload-dir db --host 0.0.0.0 --port 8000 --log-level debug ; \
    else \
      uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 ; \
    fi
