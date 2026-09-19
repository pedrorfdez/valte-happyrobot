SHELL := /bin/bash
.DEFAULT_GOAL := help

PORT ?= 4173
RUN_ID ?=
export PORT
export RUN_ID

.PHONY: up check test-dashboard help

up: ## Comprueba el Gateway y levanta el dashboard en primer plano
	@./scripts/dashboard-local.sh up

check: ## Comprueba configuración y conectividad sin levantar el dashboard
	@./scripts/dashboard-local.sh check

test-dashboard: ## Ejecuta las pruebas aisladas del launcher
	@./scripts/test-dashboard-local.sh

help: ## Muestra los comandos disponibles
	@printf '%s\n' \
	  'Valte Crisis Orchestrator' \
	  '' \
	  '  make up                           Levanta el dashboard DANA' \
	  '  make up RUN_ID=run-wildfire-demo Levanta otro run' \
	  '  make up PORT=4174                 Usa otro puerto' \
	  '  make check                        Comprueba .env y Gateway' \
	  '  make test-dashboard               Ejecuta las pruebas del launcher' \
	  '' \
	  'Ctrl-C detiene el dashboard.'
