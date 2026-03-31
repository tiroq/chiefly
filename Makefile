.PHONY: install dev admin test lint migrate seed docker-up docker-down docker-logs docker-dev docker-dev-logs docker-dev-stop miniapp-build miniapp-dev

install:
	pip install -e ".[dev]"

dev:
	uvicorn apps.api.main:app --reload --reload-dir apps --reload-dir core --reload-dir db --host 0.0.0.0 --port 8000 --log-level debug

admin:
	uvicorn apps.admin.main:app --host 127.0.0.1 --port 8001 --log-level info

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

docker-dev:
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d

docker-dev-logs:
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml logs -f

docker-dev-stop:
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml down

miniapp-build:
	cd apps/miniapp && npm run build

miniapp-dev:
	cd apps/miniapp && npm run dev
