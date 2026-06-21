# LibraForge — convenience targets.
# `make up` is the one-command install: it creates the first-boot data dirs and
# starts the container as your host user so bind-mounted files stay writable.

# Current host user/group so the container can write to bind-mounted dirs.
export UID := $(shell id -u)
export GID := $(shell id -g)

COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help up down restart rebuild logs ps test dirs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dirs: ## Create the first-boot data directories
	@mkdir -p data/audiobooks data/auth

up: dirs ## Build (if needed) and start LibraForge at http://127.0.0.1:5056
	$(COMPOSE) up -d --build
	@echo "LibraForge is starting at http://127.0.0.1:5056"

down: ## Stop and remove the container
	$(COMPOSE) down

restart: ## Restart the backend (use after app/main.py changes)
	$(COMPOSE) restart libraforge

rebuild: dirs ## Rebuild the image and restart (use after Dockerfile/deps changes)
	$(COMPOSE) up -d --build

logs: ## Follow container logs
	$(COMPOSE) logs -f libraforge

ps: ## Show container status
	$(COMPOSE) ps

test: ## Run the unit test suite inside the container
	$(COMPOSE) exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"
