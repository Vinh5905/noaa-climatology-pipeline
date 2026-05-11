# noaa-climatology-pipeline

A production-grade Data Engineering pipeline for NOAA Global Historical Climatology Network (GHCN-Daily) data.
Processes ~2.6 billion rows of global weather observations using ClickHouse, Kafka, dbt, and Dagster.

[![CI](https://github.com/Vinh5905/noaa-climatology-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/Vinh5905/noaa-climatology-pipeline/actions/workflows/ci.yml)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                              │
│  NOAA S3 bucket (CSV gz, by year)    NOAA stations metadata       │
└──────────────┬───────────────────────────┬───────────────────────┘
               │ (1) Bulk backfill         │ (2) One-time metadata
               │ INSERT FROM s3()           │ INSERT FROM url()
               ▼                           ▼
       ┌──────────────────┐         ┌──────────────────┐
       │ ClickHouse RAW   │◀────────│   Apache Kafka   │
       │  (MergeTree)     │  Kafka  │  (KRaft mode)    │
       │  1B pre-loaded   │ Engine  │  topic: noaa.obs │
       └────────┬─────────┘  + MV   └────────▲─────────┘
                │                            │
                │                  (3) Streaming
                │                  Custom Python Producer
                │                  (~1M rows/s, librdkafka)
                ▼
       ┌──────────────────┐
       │       dbt        │  staging → intermediate → marts
       │ (dbt-clickhouse) │
       └────────┬─────────┘
                ▼
       ┌──────────────────┐
       │   ClickHouse     │   stg_*, int_*, mart_*
       │   MARTS layer    │
       └────────┬─────────┘
                │
        ┌───────┼───────┬─────────────────┐
        ▼       ▼       ▼                 ▼
  ┌─────────┐ ┌──────┐ ┌─────────┐  ┌──────────────┐
  │Metabase │ │Grafana│ │ SQL    │  │clickhouse-   │
  │(BI mart)│ │(realt)│ │Playground│ │backup        │
  └─────────┘ └──────┘ └─────────┘  └──────────────┘
         ▲
         │
   ┌─────┴──────┐
   │  Dagster   │  ◀── orchestrates ALL of the above
   └────────────┘
```

---

## Prerequisites

- Docker + Docker Compose v2
- Python 3.11
- [uv](https://github.com/astral-sh/uv) (package manager)
- ~50 GB free disk space
- 16 GB RAM recommended

---

## Quick Start

```bash
# 1. Clone
git clone git@github.com:Vinh5905/noaa-climatology-pipeline.git
cd noaa-climatology-pipeline

# 2. Setup environment
cp .env.example .env
# Edit .env with your passwords

# 3. Start all services
make up

# 4. Bootstrap (create tables, topics)
make bootstrap

# 5. Open dashboards
# Grafana:    http://localhost:3000
# Metabase:   http://localhost:3001
# Dagster:    http://localhost:3002
# Playground: http://localhost:8080
```

---

## Port Map

| Port        | Service            |
| ----------- | ------------------ |
| 8123 / 9000 | ClickHouse         |
| 9092        | Kafka              |
| 3000        | Grafana            |
| 3001        | Metabase           |
| 3002        | Dagster            |
| 8080        | SQL Playground     |
| 8000        | Kafka UI (optional)|

---

## Running the Pipeline

### Bulk Backfill (1B historical rows)

```bash
make seed
# or manually:
cd ingestion && uv run python -m backfill.load_historical --start-year 1763 --end-year 2010
```

### Kafka Producer (streaming simulation)

```bash
make producer
# or manually:
cd ingestion && uv run python -m producer.noaa_producer --years 2011,2012 --rate 500000
```

### dbt Transforms

```bash
make dbt-run
# or manually:
cd transform && dbt run
```

### Dagster Orchestration

```bash
make dagster-dev
# UI at http://localhost:3002
```

### SQL Playground

```bash
make playground
# UI at http://localhost:8080
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| ClickHouse not responding | `docker compose -f docker/docker-compose.yml logs clickhouse` |
| Kafka consumer lag high | See RUNBOOK.md §2 |
| dbt test failures | `cd transform && dbt test` then see RUNBOOK.md §4 |
| Disk full | See RUNBOOK.md §3 |
| Restore from backup | See RUNBOOK.md §5 |

See [RUNBOOK.md](RUNBOOK.md) for full incident procedures.

---

## Project Structure

```
noaa-climatology-pipeline/
├── docker/           # Docker Compose stack
├── ingestion/        # Backfill scripts + Kafka producer
├── transform/        # dbt project (staging → intermediate → marts)
├── orchestration/    # Dagster assets, schedules, sensors
├── playground/       # SQL Playground web app (FastAPI + HTMX)
├── monitoring/       # Grafana dashboard sources
├── reporting/        # Metabase exported dashboards
├── backup/           # clickhouse-backup configs + scripts
├── scripts/          # Bootstrap, health check, load test
└── tests/e2e/        # End-to-end smoke tests
```

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Architecture decisions and trade-offs
- [RUNBOOK.md](RUNBOOK.md) — Incident response procedures
- [SLA.md](SLA.md) — Service level objectives
- [backup/retention_policy.md](backup/retention_policy.md) — Backup strategy
- `make dbt-docs` — dbt lineage graph

---

## Tech Stack

| Layer            | Tool                         |
| ---------------- | ---------------------------- |
| Data Warehouse   | ClickHouse 24.x              |
| Streaming        | Apache Kafka 3.7+ (KRaft)    |
| Transform        | dbt-core + dbt-clickhouse    |
| Orchestration    | Dagster 1.9+                 |
| Producer         | Python + confluent-kafka     |
| BI Reporting     | Metabase 0.51+               |
| Real-time Mon.   | Grafana 11.x                 |
| SQL Playground   | FastAPI + HTMX + Monaco      |
| Backup           | clickhouse-backup 2.5+       |
| Container        | Docker Compose v2            |
| Package manager  | uv                           |
