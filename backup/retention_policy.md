# Backup Retention Policy

## Recovery Objectives

| Objective | Target | Notes |
|-----------|--------|-------|
| **RPO** (Recovery Point Objective) | 24 hours | Daily full backup at 3 AM |
| **RTO** (Recovery Time Objective) | 1 hour | For mart tables from local backup |

## Backup Schedule

| Type | Frequency | Time | Retention |
|------|-----------|------|-----------|
| Full backup | Daily | 3:00 AM | 7 days local, 30 days remote (when S3 configured) |
| Incremental | Every 6h | 6,12,18,0 AM | Optional — not enabled by default |

## What is Backed Up

- All `noaa_raw.*` tables (historical + streaming + DLQ)
- All `noaa_staging.*` tables (intermediate models)
- All `noaa_marts.*` tables (final mart tables)
- Table schemas and DDL

**Not backed up**: `system.*` tables, Kafka topic data (ephemeral), `.dagster/` state

## Storage

- **Local**: `backup/storage/` (7 backups = ~7 × size of marts layer)
- **Remote S3**: Optional. Configure `BACKUP_S3_BUCKET` in `.env`

## Restore Priority

1. `noaa_marts.*` — restore first (BI/reporting impact)
2. `noaa_raw.*` — restore second (can be reloaded from S3 if needed)
3. `noaa_staging.*` — can be regenerated via `dbt run`

## Restore Drill Log

| Date | Backup Name | Duration | Result |
|------|-------------|----------|--------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ |

Drills must be conducted monthly. Record results here.
See [RUNBOOK.md §5](../RUNBOOK.md) for restore procedure.
