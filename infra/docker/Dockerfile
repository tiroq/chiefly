FROM python:3.12-slim

WORKDIR /app

# Copy all source first so pip install has access to the package tree
COPY pyproject.toml .
COPY apps/ apps/
COPY core/ core/
COPY db/ db/

# Non-editable install; produces a self-contained wheel
RUN pip install --no-cache-dir .

# Copy remaining files (prompts, scripts, etc.)
COPY . .

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
