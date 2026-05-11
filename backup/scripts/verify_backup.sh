#!/usr/bin/env bash
set -euo pipefail
# Verify backup exists and report row counts

BACKUP_NAME="${1:-}"

echo "=== Backup Verification ==="

# List available backups
echo "Available backups:"
docker exec clickhouse-backup clickhouse-backup list 2>/dev/null || \
  echo "  (clickhouse-backup not running — use ClickHouse native backup)"

# Current row counts
echo ""
echo "Current ClickHouse row counts:"
docker exec clickhouse clickhouse-client --query "
SELECT database, table, sum(rows) AS rows
FROM system.parts
WHERE database LIKE 'noaa_%' AND active = 1
GROUP BY database, table
ORDER BY database, table
"
