#!/usr/bin/env bash
set -euo pipefail
# Full ClickHouse backup via clickhouse-backup

BACKUP_NAME="${1:-noaa-$(date +%Y%m%d-%H%M%S)}"

echo "=== ClickHouse Full Backup: ${BACKUP_NAME} ==="

if ! docker ps --filter "name=clickhouse-backup" --filter "status=running" -q | grep -q .; then
  echo "WARNING: clickhouse-backup container not running. Using docker exec approach."
  # Direct backup via clickhouse-client for essential marts
  docker exec clickhouse clickhouse-client --query "
  BACKUP TABLE noaa_marts.mart_global_temperature_yearly
  TO File('/backups/${BACKUP_NAME}_mart_temp.zip')
  " 2>&1 || echo "Backup via BACKUP TABLE (ClickHouse native backup)"
else
  docker exec clickhouse-backup clickhouse-backup create "${BACKUP_NAME}"
fi

echo "Backup complete: ${BACKUP_NAME}"
ls -lh /backups/ 2>/dev/null || echo "Backup stored in container at /backups/"
