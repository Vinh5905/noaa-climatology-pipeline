#!/usr/bin/env bash
set -euo pipefail
# Restore ClickHouse from backup

BACKUP_NAME="${1:?Usage: restore.sh <backup_name> [optional_table]}"
TABLE="${2:-}"

echo "=== ClickHouse Restore: ${BACKUP_NAME} ==="

if [ -n "$TABLE" ]; then
  echo "Restoring single table: $TABLE"
  docker exec clickhouse-backup clickhouse-backup restore \
    --tables "${TABLE}" "${BACKUP_NAME}"
else
  echo "Restoring all tables..."
  docker exec clickhouse-backup clickhouse-backup restore "${BACKUP_NAME}"
fi

echo "Restore complete."
echo "Verifying mart row counts..."
docker exec clickhouse clickhouse-client --query "
SELECT 'mart_global_temperature_yearly' AS table, count() AS rows
FROM noaa_marts.mart_global_temperature_yearly
UNION ALL
SELECT 'mart_top_hottest_stations', count()
FROM noaa_marts.mart_top_hottest_stations
"
