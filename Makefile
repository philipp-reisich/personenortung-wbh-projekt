# path: personenortung-wbh-projekt/Makefile

SHELL := /bin/bash
COMPOSE = docker-compose --env-file .env -f docker-compose.yaml

.PHONY: up down logs seed test build

up:
	@echo "Starting RTLS system..."
	$(COMPOSE) up -d --build

down:
	@echo "Stopping RTLS system..."
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

build:
	@echo "Building containers..."
	$(COMPOSE) build

seed:
	@echo "Seeding database with demo data..."
	$(COMPOSE) run --rm api python -m api.scripts.seed

test:
	@echo "Running test suite..."
	$(COMPOSE) run --rm api pytest -q

stop:
	$(COMPOSE) stop

start:
	$(COMPOSE) start

restart:
	$(COMPOSE) restart api ingestor locator mqtt