#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

START_YEAR=${1:-1763}
END_YEAR=${2:-2010}

echo "Seeding ClickHouse with historical data (${START_YEAR}-${END_YEAR})..."
cd ingestion
uv run python -m backfill.load_historical \
  --start-year "${START_YEAR}" \
  --end-year "${END_YEAR}"
