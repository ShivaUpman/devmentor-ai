# Makefile — Developer task automation
#
# WHY a Makefile?
#   Standardizes developer commands. New engineers run `make setup` and
#   have a working environment. Commands are documented and consistent.
#   Works on any Unix system without installing additional tools.

.PHONY: help setup dev test lint clean build migrate

# Default target: show help
help:
	@echo ""
	@echo "DevMentor AI — Developer Commands"
	@echo "──────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

setup: ## First-time setup: copy .env, install deps, start services
	cp .env.example .env
	@echo "✓ .env created from .env.example — edit GROQ_API_KEY"
	docker compose build
	docker compose up -d postgres redis
	sleep 3
	docker compose run --rm backend alembic upgrade head
	@echo "✓ Database schema created"
	@echo ""
	@echo "Run 'make dev' to start all services"

dev: ## Start all services in development mode (hot reload)
	docker compose up

test-backend: ## Run backend tests
	cd backend && PYTHONPATH=. pytest tests/ -v --cov=app --cov-report=term-missing

test-ml: ## Run ML service tests
	cd ml && pytest tests/ -v --cov=. --cov-report=term-missing

test: test-backend test-ml ## Run all tests

lint: ## Run linting on all code
	cd backend && ruff check app/ && ruff format app/ --check
	cd frontend && npm run lint

migrate: ## Run database migrations
	docker compose exec backend alembic upgrade head

migrate-new: ## Create a new migration (usage: make migrate-new msg="add column")
	docker compose exec backend alembic revision --autogenerate -m "$(msg)"

clean: ## Stop and remove all containers, volumes, and images
	docker compose down -v --rmi local

build: ## Build all Docker images
	docker compose build

logs: ## Tail logs from all services
	docker compose logs -f

shell-backend: ## Open a shell in the backend container
	docker compose exec backend bash

shell-db: ## Open psql in the postgres container
	docker compose exec postgres psql -U devmentor -d devmentor

redis-cli: ## Open redis-cli
	docker compose exec redis redis-cli

health: ## Check all service health
	@curl -sf http://localhost/health && echo "✓ API healthy" || echo "✗ API unhealthy"
	@docker compose exec postgres pg_isready -U devmentor && echo "✓ DB healthy" || echo "✗ DB unhealthy"
	@docker compose exec redis redis-cli ping && echo "✓ Redis healthy" || echo "✗ Redis unhealthy"
