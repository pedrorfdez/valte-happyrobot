SHELL := /bin/bash
.DEFAULT_GOAL := help

PORT ?= 4173
RUN_ID ?=
export PORT
export RUN_ID

.PHONY: up up-legacy check check-legacy test-dashboard help

up: ## Levanta el dashboard v2 (default, app-v2) en primer plano
	@./scripts/dashboard-v2.sh up

up-legacy: ## Levanta el dashboard legacy (diagnóstico, app/)
	@./scripts/dashboard-local.sh up

check: ## Comprueba configuración y conectividad sin levantar el dashboard (v2)
	@./scripts/dashboard-v2.sh check

check-legacy: ## Comprueba configuración y conectividad (legacy)
	@./scripts/dashboard-local.sh check

test-dashboard: ## Ejecuta las pruebas aisladas del launcher
	@./scripts/test-dashboard-local.sh

help: ## Muestra los comandos disponibles
	@printf '%s\n' \
	  'Valte Crisis Orchestrator — dashboard v2 (app-v2) es el default; app/ legacy queda como fallback diagnóstico' \
	  '' \
	  '  make up                           Levanta el dashboard v2 (app-v2/dist) DANA' \
	  '  make up-legacy                    Levanta el dashboard legacy (app/)' \
	  '  make up RUN_ID=run-wildfire-demo Levanta otro run (v2)' \
	  '  make up PORT=4174                 Usa otro puerto' \
	  '  make check                        Comprueba .env y Gateway (v2)' \
	  '  make check-legacy                 Comprueba .env y Gateway (legacy)' \
	  '  make test-dashboard               Ejecuta las pruebas del launcher' \
	  '' \
	  'Ctrl-C detiene el dashboard.'
