.PHONY: install dev test lint migrate seed docker-up docker-down

install:
	pip install -e ".[dev]"

dev:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

lint:
	ruff check .

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(name)"

seed:
	python scripts/seed_projects.py

docker-up:
	docker compose -f infra/docker/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker/docker-compose.yml down

docker-logs:
	docker compose -f infra/docker/docker-compose.yml logs -f
