.PHONY: up down logs clean bootstrap seed producer dbt-run dbt-test dbt-docs dagster-dev playground backup health help

COMPOSE := docker compose -f docker/docker-compose.yml
CLICKHOUSE_CLIENT := docker exec -it clickhouse clickhouse-client

help:
	@echo "NOAA Climatology Pipeline — Available targets:"
	@echo ""
	@echo "  Infrastructure:"
	@echo "    up            Start all Docker services"
	@echo "    down          Stop all Docker services"
	@echo "    logs          Follow logs from all services"
	@echo "    clean         Remove containers, volumes, and data"
	@echo "    health        Run health check on all services"
	@echo ""
	@echo "  Data Pipeline:"
	@echo "    bootstrap     Create ClickHouse databases/tables and Kafka topics"
	@echo "    seed          Run bulk backfill (historical 1763-2010)"
	@echo "    producer      Start Kafka producer (streaming simulation)"
	@echo ""
	@echo "  Transform:"
	@echo "    dbt-run       Run all dbt models"
	@echo "    dbt-test      Run all dbt tests"
	@echo "    dbt-docs      Generate and serve dbt documentation"
	@echo ""
	@echo "  Orchestration:"
	@echo "    dagster-dev   Start Dagster UI (localhost:3002)"
	@echo ""
	@echo "  Applications:"
	@echo "    playground    Start SQL Playground (localhost:8080)"
	@echo ""
	@echo "  Backup:"
	@echo "    backup        Run a full ClickHouse backup"

up:
	$(COMPOSE) up -d
	@echo "Services started. Run 'make health' to verify."

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

clean:
	$(COMPOSE) down -v
	@echo "WARNING: All container data removed."

health:
	@bash scripts/health_check.sh

bootstrap:
	@echo "Creating ClickHouse databases and tables..."
	@bash scripts/bootstrap.sh
	@echo "Bootstrap complete."

seed:
	@echo "Starting historical backfill (this will take a long time)..."
	cd ingestion && uv run python -m backfill.load_historical

producer:
	@echo "Starting Kafka producer..."
	@bash scripts/start_producer.sh

dbt-run:
	cd transform && dbt run

dbt-test:
	cd transform && dbt test

dbt-docs:
	cd transform && dbt docs generate && dbt docs serve

dagster-dev:
	cd orchestration && DAGSTER_HOME=$$(pwd)/../.dagster uv run dagster dev --host 0.0.0.0 --port 3002

playground:
	cd playground && uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

backup:
	@bash backup/scripts/backup_full.sh
