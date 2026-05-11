#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" > /dev/null 2>&1; then
    echo "  [OK]  $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Health Check ==="

check "ClickHouse native query" \
  "docker exec clickhouse clickhouse-client --query 'SELECT 1'"

check "ClickHouse HTTP ping" \
  "docker exec clickhouse wget -q -O- http://localhost:8123/ping"

check "ClickHouse databases" \
  "docker exec clickhouse clickhouse-client --query 'SHOW DATABASES' | grep -q noaa_raw"

check "Kafka broker" \
  "docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list"

check "Grafana health" \
  "curl -sf http://localhost:3000/api/health"

check "Metabase health" \
  "curl -sf http://localhost:3001/api/health"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
