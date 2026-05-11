#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

RATE=${PRODUCER_RATE_PER_SEC:-500000}
YEARS=${PRODUCER_YEARS:-"2011,2012,2013,2014,2015"}

echo "Starting NOAA Kafka producer..."
echo "  Rate: ${RATE} rows/s"
echo "  Years: ${YEARS}"

cd ingestion
uv run python -m producer.noaa_producer \
  --rate "${RATE}" \
  --years "${YEARS}"
