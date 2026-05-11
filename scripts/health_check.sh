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

check "ClickHouse HTTP"   "curl -sf http://localhost:8123/ping"
check "ClickHouse Native" "docker exec clickhouse clickhouse-client --query 'SELECT 1'"
check "Kafka"             "docker exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list"
check "Grafana"           "curl -sf http://localhost:3000/api/health"
check "Metabase"          "curl -sf http://localhost:3001/api/health"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
