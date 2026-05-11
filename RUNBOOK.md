# Runbook — NOAA Climatology Pipeline

Operational procedures for incident response and common maintenance tasks.

---

## Scenario Index

1. [Pipeline Ingestion Stopped](#1-pipeline-ingestion-stopped)
2. [Kafka Consumer Lag Too High](#2-kafka-consumer-lag-too-high)
3. [Disk Full on ClickHouse](#3-disk-full-on-clickhouse)
4. [dbt Test Failure Investigation](#4-dbt-test-failure-investigation)
5. [Restore from Backup](#5-restore-from-backup)
6. [Backfill a Specific Year](#6-backfill-a-specific-year)
7. [Add a New dbt Model](#7-add-a-new-dbt-model)

---

## 1. Pipeline Ingestion Stopped

**Symptoms**:
- Grafana alert `IngestionStalled` fires
- `ingestion rate rows/s` panel shows 0 for > 5 minutes

**Diagnosis**:
```bash
# Check producer process
docker compose -f docker/docker-compose.yml logs --tail=50 producer

# Check ClickHouse Kafka consumers
docker exec -it clickhouse clickhouse-client \
  --query "SELECT * FROM system.kafka_consumers"

# Check Kafka topic
docker exec -it kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --describe --topic noaa.observations
```

**Resolution**:
```bash
# Restart producer
make producer

# If Kafka is down, restart
docker compose -f docker/docker-compose.yml restart kafka

# Verify recovery
scripts/health_check.sh
```

---

## 2. Kafka Consumer Lag Too High

**Symptoms**:
- Grafana alert `KafkaLagHigh` fires (lag > 1M messages)
- Dagster sensor `kafka_consumer_lag_sensor` raises alert

**Diagnosis**:
```bash
# Check consumer group lag
docker exec -it kafka kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --describe --group clickhouse_noaa_consumer

# Check ClickHouse insert rate
docker exec -it clickhouse clickhouse-client \
  --query "SELECT count() FROM system.query_log 
           WHERE query_kind='Insert' 
           AND event_time > now() - INTERVAL 5 MINUTE"
```

**Resolution**:
1. If ClickHouse is slow inserting: reduce `kafka_max_block_size` and restart the Kafka Engine table
2. If producer is too fast: reduce `--rate` flag in producer command
3. If lag is persistent: restart ClickHouse Kafka consumer:
```sql
-- In ClickHouse client
DETACH TABLE noaa_raw.observations_kafka;
ATTACH TABLE noaa_raw.observations_kafka;
```

---

## 3. Disk Full on ClickHouse

**Symptoms**:
- Grafana alert `ClickHouseDiskFull` fires (usage > 80%)
- ClickHouse starts refusing inserts

**Diagnosis**:
```bash
# Check disk usage by table
docker exec -it clickhouse clickhouse-client \
  --query "SELECT table, formatReadableSize(sum(bytes_on_disk)) AS size
           FROM system.parts 
           WHERE database LIKE 'noaa_%' AND active 
           GROUP BY table 
           ORDER BY sum(bytes_on_disk) DESC"
```

**Resolution** (in order of preference):
1. Run OPTIMIZE to force merges (reduces parts overhead):
```sql
OPTIMIZE TABLE noaa_raw.observations_streaming FINAL;
```

2. Force TTL cleanup:
```sql
ALTER TABLE noaa_raw.observations_streaming MATERIALIZE TTL;
```

3. Drop oldest partitions manually:
```sql
-- List partitions
SELECT partition, sum(rows), formatReadableSize(sum(bytes_on_disk))
FROM system.parts 
WHERE table = 'observations_streaming' AND active
GROUP BY partition ORDER BY partition;

-- Drop oldest if necessary
ALTER TABLE noaa_raw.observations_streaming DROP PARTITION '2011';
```

4. As last resort: stop producer and clear DLQ table.

---

## 4. dbt Test Failure Investigation

**Symptoms**:
- CI fails on `dbt test` step
- Dagster sensor `dbt_test_failure_sensor` alerts

**Diagnosis**:
```bash
cd transform

# Run tests with verbose output
dbt test --store-failures -v

# Check stored failures (if store_failures: true)
docker exec -it clickhouse clickhouse-client \
  --query "SHOW TABLES FROM noaa_ops LIKE 'assert_%'"
```

**Common causes and fixes**:

| Test | Common cause | Fix |
|------|-------------|-----|
| `not_null` on `station_id` | DLQ messages missing field | Check producer Pydantic validation |
| `assert_no_future_dates` | System clock skew | Check Docker host clock |
| `assert_temp_in_valid_range` | Corrupt CSV row | Add filter in staging model |
| `unique` on mart key | Duplicate records from Kafka replay | Check `unique_key` in incremental model |

**Resolution**:
```bash
# Rerun only failed tests
dbt test --select state:fail

# Rerun specific model + tests
dbt build --select mart_global_temperature_yearly+
```

---

## 5. Restore from Backup

**Prerequisites**: `clickhouse-backup` service is running.

**Steps**:
```bash
# 1. List available backups
docker exec -it clickhouse-backup clickhouse-backup list

# 2. Note the backup name (e.g., 2026-01-15T03-00-00)
BACKUP_NAME="2026-01-15T03-00-00"

# 3. Run restore script
./backup/scripts/restore.sh ${BACKUP_NAME}

# 4. Verify row counts
docker exec -it clickhouse clickhouse-client \
  --query "SELECT count() FROM noaa_marts.mart_global_temperature_yearly"
```

**Restore single table**:
```bash
docker exec -it clickhouse-backup clickhouse-backup restore \
  --tables noaa_marts.mart_global_temperature_yearly \
  ${BACKUP_NAME}
```

**Restore drill results** (fill after running in Phase 10):
- Date performed: _TBD_
- Backup size: _TBD_
- Restore duration: _TBD_
- Row count verified: _TBD_

**Expected RTO**: < 1 hour for mart tables.

---

## 6. Backfill a Specific Year

**Use case**: A year's data was corrupted or a new year needs to be reloaded.

```bash
# Backfill single year (idempotent — skips if partition already clean)
cd ingestion
uv run python -m backfill.load_historical \
  --start-year 1985 \
  --end-year 1985 \
  --force  # force reload even if partition exists

# Verify
docker exec -it clickhouse clickhouse-client \
  --query "SELECT count(), min(date), max(date) 
           FROM noaa_raw.observations_historical 
           WHERE toYYYY(date) = 1985"
```

**Via Dagster**: In the Dagster UI, go to Assets → `historical_observations` → Materialize → select partition `1985`.

---

## 7. Add a New dbt Model

**Steps**:

1. Create SQL file in the appropriate layer:
   - `transform/models/staging/stg_noaa__<entity>.sql` — raw source normalization
   - `transform/models/intermediate/int_<description>.sql` — business logic joins
   - `transform/models/marts/mart_<name>.sql` — final business tables

2. Add schema definition in the layer's `_models.yml`:
```yaml
- name: mart_my_new_model
  description: "What this model represents"
  columns:
    - name: id
      tests:
        - not_null
        - unique
    - name: date
      tests:
        - not_null
```

3. Add singular test if business rule needed:
```sql
-- transform/tests/singular/assert_my_rule.sql
SELECT count()
FROM {{ ref('mart_my_new_model') }}
WHERE some_column IS NULL
HAVING count() > 0
```

4. Test locally:
```bash
cd transform
dbt run --select mart_my_new_model
dbt test --select mart_my_new_model
```

5. Commit:
```bash
git add transform/models/marts/mart_my_new_model.sql \
        transform/models/marts/_models.yml
git commit -m "feat(dbt): add mart_my_new_model"
git push origin main
```
