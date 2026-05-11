# SLA / SLO Definitions

Service Level Objectives for the NOAA Climatology Pipeline.

---

## SLO-001: Data Freshness

**Definition**: 95% of rows in `noaa_marts.*` must be no older than 1 hour compared to `now()`.

**Measured by**: Dagster `freshness_sensor` checking `max(updated_at)` in `noaa_marts.mart_ingestion_metrics`.

**Alert threshold**: Data staleness > 2 hours → Grafana alert `DataStaleness`.

**SQL check**:
```sql
SELECT
    now() - max(updated_at) AS staleness_seconds,
    staleness_seconds > 3600 AS is_violating_slo
FROM noaa_marts.mart_ingestion_metrics
```

---

## SLO-002: Pipeline Availability

**Definition**: Ingestion pipeline uptime ≥ 99% measured by Dagster run success rate over a rolling 7-day window.

**Measured by**: Dagster run history — `success_count / total_runs >= 0.99`.

**Alert threshold**: Ingestion rate = 0 rows/s for > 5 consecutive minutes → Grafana alert `IngestionStalled`.

---

## SLO-003: Message Completeness

**Definition**: ≥ 99% of messages produced to Kafka topic `noaa.observations` must appear in `noaa_raw.observations_streaming` within 5 minutes.

**Measured by**: Compare `max(_kafka_offset)` in ClickHouse vs latest offset in Kafka topic.

**SQL check**:
```sql
SELECT
    _kafka_partition,
    max(_kafka_offset) AS clickhouse_latest_offset
FROM noaa_raw.observations_streaming
GROUP BY _kafka_partition
ORDER BY _kafka_partition
```

**Alert threshold**: Consumer lag > 1M messages → Grafana alert `KafkaLagHigh`.

---

## SLO-004: Query Performance

**Definition**: 95th percentile query time for mart tables ≤ 5 seconds for standard analytics queries.

**Measured by**: `system.query_log` in ClickHouse.

**SQL check**:
```sql
SELECT
    quantile(0.95)(query_duration_ms) / 1000 AS p95_sec
FROM system.query_log
WHERE
    databases = ['noaa_marts']
    AND type = 'QueryFinish'
    AND event_time > now() - INTERVAL 1 DAY
```

---

## Backup SLOs

| Objective               | Target  | Notes                          |
| ----------------------- | ------- | ------------------------------ |
| RPO (Recovery Point)    | 24 hours | Daily full backup at 3 AM     |
| RTO (Recovery Time)     | 1 hour   | Restore mart tables from local |
| Backup retention local  | 7 days   | clickhouse-backup setting      |
| Backup retention remote | 30 days  | S3-compatible (optional)       |
| Restore drill frequency | Monthly  | Document results in RUNBOOK.md |

---

## SLO Tracking

| SLO | Status | Last measured | Notes |
|-----|--------|---------------|-------|
| SLO-001 Data Freshness    | ⬜ Not yet measured | - | Phase 6/7 |
| SLO-002 Pipeline Availability | ⬜ Not yet measured | - | Phase 6 |
| SLO-003 Message Completeness | ⬜ Not yet measured | - | Phase 4/6 |
| SLO-004 Query Performance | ⬜ Not yet measured | - | Phase 5 |

*Will be updated with actual measurements after each phase completes.*
