#!/usr/bin/env bash
set -euo pipefail

echo "=== Producer Load Test ==="

cd ingestion

for rate in 50000 100000 250000 500000 1000000; do
  echo ""
  echo "Testing rate: ${rate} rows/s (10 seconds)..."
  timeout 12 uv run python -m producer.noaa_producer \
    --rate "${rate}" \
    --max-rows $((rate * 10)) \
    --dry-run \
    2>&1 | tail -5 || true
done

echo ""
echo "Load test complete."
