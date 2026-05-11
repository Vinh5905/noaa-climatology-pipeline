#!/usr/bin/env bash
set -euo pipefail

echo "=== Bootstrapping NOAA Pipeline ==="

# Source env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "Creating ClickHouse databases..."
docker exec clickhouse clickhouse-client --multiquery <<'EOF'
CREATE DATABASE IF NOT EXISTS noaa_raw;
CREATE DATABASE IF NOT EXISTS noaa_staging;
CREATE DATABASE IF NOT EXISTS noaa_marts;
CREATE DATABASE IF NOT EXISTS noaa_ops;
EOF

echo "Running ClickHouse init scripts..."
for f in docker/clickhouse/init-scripts/*.sql; do
  echo "  Running $f..."
  docker exec -i clickhouse clickhouse-client --multiquery < "$f"
done

echo "Creating Kafka topics..."
docker exec kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic noaa.observations \
  --partitions 12 \
  --replication-factor 1

docker exec kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic noaa.stations \
  --partitions 1 \
  --replication-factor 1

echo "Bootstrap complete."
