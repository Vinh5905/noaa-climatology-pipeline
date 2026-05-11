# Ingestion

Handles two ingestion patterns:
1. **Bulk backfill**: historical data (1763–2010) via `INSERT FROM s3()` directly into ClickHouse
2. **Streaming**: real-time simulation (2011–2024) via Kafka producer (see `producer/`)

## Setup

```bash
uv sync
```

## Bulk Backfill

### Load historical observations (1763–2010)

```bash
# Full load
uv run python -m backfill.load_historical

# Specific year range
uv run python -m backfill.load_historical --start-year 1900 --end-year 1950

# Force reload a year (even if already loaded)
uv run python -m backfill.load_historical --start-year 1900 --end-year 1900 --force
```

### Load station metadata (one-time)

```bash
uv run python -m backfill.load_stations

# Force reload
uv run python -m backfill.load_stations --force
```

### Verify backfill

```bash
uv run python -m backfill.verify_backfill
```

## Idempotency

`load_historical.py` checks `system.parts` before loading each year's partition.
If a partition already exists with rows > 0, it is skipped (unless `--force`).

This means you can safely:
- Kill and restart the script at any point
- Re-run for failed years only
- Backfill a specific year range without duplicating data

## Environment

Copy `.env.example` to `.env` and configure:
- `CLICKHOUSE_HOST`, `CLICKHOUSE_HTTP_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`

## Data Source

NOAA GHCN-D dataset from ClickHouse public S3 bucket:
`https://datasets-documentation.s3.eu-west-3.amazonaws.com/noaa/noaa_enriched/`

Files are in Parquet format, one per year.
