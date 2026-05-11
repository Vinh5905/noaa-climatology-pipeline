# Architecture Decisions

This document records architectural decisions (ADRs) and trade-offs for the NOAA Climatology Pipeline.

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                              │
│  NOAA S3 bucket (CSV gz, by year)    NOAA stations metadata       │
└──────────────┬───────────────────────────┬───────────────────────┘
               │ (1) Bulk backfill         │ (2) One-time metadata
               │ INSERT FROM s3()           │ INSERT FROM url()
               ▼                           ▼
       ┌──────────────────┐         ┌──────────────────┐
       │ ClickHouse RAW   │◀────────│   Apache Kafka   │
       │  (MergeTree)     │  Kafka  │  (KRaft mode)    │
       │  1B pre-loaded   │ Engine  │  topic: noaa.obs │
       └────────┬─────────┘  + MV   └────────▲─────────┘
                │                            │
                ▼                  Custom Python Producer
       ┌──────────────────┐
       │       dbt        │  staging → intermediate → marts
       └────────┬─────────┘
                ▼
       ┌──────────────────┐
       │   ClickHouse     │   stg_*, int_*, mart_*
       │   MARTS layer    │
       └────────┬─────────┘
```

---

## ADR-001: ClickHouse as Data Warehouse

**Decision**: Use ClickHouse 24.x as the primary analytical store.

**Context**: Need sub-second queries on 2.6B rows of time-series climate data with complex aggregations.

**Trade-offs**:
- ✅ Best-in-class OLAP performance (columnar, vectorized execution)
- ✅ Native Kafka Engine for streaming ingestion
- ✅ Excellent compression (Delta + ZSTD reduces temp data ~70%)
- ❌ No ACID transactions (acceptable for analytics)
- ❌ Limited JOIN performance vs row-store (mitigated by pre-aggregation in dbt)

---

## ADR-002: Dagster over Airflow

**Decision**: Use Dagster 1.9+ for orchestration.

**Context**: Need to orchestrate batch + streaming + dbt + backup jobs with clear lineage.

**Trade-offs**:
- ✅ Asset-based model: each dbt model = one asset, lineage is automatic
- ✅ Native `dagster-dbt` integration
- ✅ `dagster dev` starts in one command vs Airflow's multi-process setup
- ✅ Pythonic types + Pydantic validation
- ❌ Smaller community than Airflow
- ❌ Less enterprise adoption (acceptable for portfolio project)

---

## ADR-003: Kafka KRaft Mode (No Zookeeper)

**Decision**: Use Kafka 3.7 in KRaft mode without Zookeeper.

**Context**: Local development setup; need simple, single-node Kafka.

**Trade-offs**:
- ✅ No Zookeeper container dependency (simpler docker-compose)
- ✅ Faster startup
- ✅ KRaft is production-ready since Kafka 3.3
- ❌ Fewer operational tools mature for KRaft (acceptable for local)

---

## ADR-004: 12 Kafka Partitions for `noaa.observations`

**Decision**: Use 12 partitions for the observations topic.

**Context**: Need to achieve ~1M rows/s throughput from producer; ClickHouse Kafka Engine needs enough partitions to parallelize.

**Trade-offs**:
- ✅ 12 partitions allows 4+ consumer threads in ClickHouse Kafka Engine
- ✅ Producer can fan-out by station_id hash
- ❌ Higher overhead per-partition for small datasets (acceptable at 1B+ rows)

---

## ADR-005: Ingestion Strategy — Hybrid Bulk + Streaming

**Decision**: Bulk INSERT FROM s3() for historical (1763-2010), Kafka streaming for recent (2011-2024).

**Context**: 2.6B rows total, need to demonstrate both batch and streaming patterns.

**Trade-offs**:
- ✅ `INSERT FROM s3()` is the fastest way to bulk-load into ClickHouse (no intermediary)
- ✅ Streaming via Kafka demonstrates real-time DE pattern
- ✅ Clear separation of historical vs streaming raw tables
- ❌ Two separate raw tables require a UNION view (`observations_all`) for downstream dbt

---

## ADR-006: dbt-clickhouse for Transforms

**Decision**: Use dbt-core 1.8+ with dbt-clickhouse adapter.

**Context**: Need a standards-based transform layer with testing, lineage, and documentation.

**Trade-offs**:
- ✅ Industry standard for SQL-based transforms
- ✅ Auto-documentation and lineage graph
- ✅ Built-in test framework (schema tests + singular tests)
- ❌ dbt-clickhouse adapter slightly behind dbt-core features (acceptable at 1.8+)

---

## ADR-007: FastAPI + HTMX for SQL Playground

**Decision**: Use FastAPI (Python) + HTMX (no-build frontend) + Monaco Editor (CDN).

**Context**: Need an internal SQL playground similar to ClickHouse Cloud's UI, without a React build pipeline.

**Trade-offs**:
- ✅ No Node.js/npm required — pure Python stack
- ✅ Monaco editor (VSCode engine) via CDN for full SQL intellisense
- ✅ HTMX enables AJAX-style partial updates without JavaScript framework
- ❌ Server-side rendering less interactive than SPA (acceptable for internal tool)

---

## ADR-008: Python 3.11 + uv

**Decision**: Pin Python 3.11, use uv as package manager.

**Context**: Dagster recommends 3.11; uv is significantly faster than pip for CI.

**Trade-offs**:
- ✅ uv install time ~10x faster than pip (important for CI)
- ✅ `uv.lock` for reproducible environments
- ❌ uv is relatively new (2024); less ecosystem maturity than pip (acceptable)

---

## ADR-009: clickhouse-backup for DR

**Decision**: Use Altinity clickhouse-backup 2.5+ for backup/restore.

**Context**: Need RPO=24h, RTO=1h backup strategy for ClickHouse.

**Trade-offs**:
- ✅ De-facto standard for ClickHouse backup
- ✅ Supports local disk and S3-compatible storage
- ✅ Incremental backup capability
- ❌ Backup of 1B rows takes significant time/disk (mitigated by incremental)

---

## Data Model

### Databases

| Database       | Purpose                                |
| -------------- | -------------------------------------- |
| `noaa_raw`     | Raw ingested data (backfill + streaming) |
| `noaa_staging` | dbt staging views                      |
| `noaa_marts`   | dbt final mart tables (business-ready) |
| `noaa_ops`     | Operational metadata, metrics          |

### Key Tables

| Table                              | Engine      | Rows      | Notes                        |
| ---------------------------------- | ----------- | --------- | ---------------------------- |
| `noaa_raw.observations_historical` | MergeTree   | ~1B       | Bulk loaded, immutable       |
| `noaa_raw.observations_streaming`  | MergeTree   | ~1.6B     | From Kafka, TTL 90 days      |
| `noaa_raw.observations_kafka`      | Kafka       | -         | Buffer table (Kafka Engine)  |
| `noaa_raw.stations`               | MergeTree   | ~120K     | Station metadata             |
| `noaa_raw.observations_dlq`       | MergeTree   | small     | Dead Letter Queue, TTL 30d   |

---

## Storage Tiering (Production Consideration)

For production, ClickHouse supports multi-disk storage policy:
- Hot tier: data < 30 days on SSD
- Cold tier: data > 30 days on HDD

Config in `docker/clickhouse/config.d/storage.xml`. This is documented but not enabled in local dev to keep complexity low.

---

## Deviation Log

| Plan Spec | Actual | Reason |
|-----------|--------|--------|
| `PARTITION BY toYYYY(date)` | `PARTITION BY toYear(date)` | `toYYYY()` does not exist in ClickHouse 24.10; `toYear()` is the correct function |
| `metabase/metabase:v0.51.0` | `metabase/metabase:v0.52.17` | v0.51.0 tag not published on Docker Hub |
| `bitnami/kafka:3.7` | `apache/kafka:3.7.0` | bitnami/kafka:3.7 tag not found on Docker Hub; apache/kafka is the official image |
| Per-year S3 parquet files `{year}.parquet` | Single file `noaa_enriched.parquet` | ClickHouse public dataset is a single 1B+ row file, not per-year files |

---

## Limitations & Known Trade-offs

1. **1M rows/s producer target**: Achievable on server hardware. On laptop, expect 200K-800K rows/s. The pipeline is designed to degrade gracefully — metrics will report actual throughput.

2. **No Schema Registry**: Producer uses JSON (not Avro/Protobuf). Comment in `noaa_producer.py` notes that Avro + Schema Registry is the production choice for schema evolution.

3. **Single-node ClickHouse**: No replication. For production, a 3-node cluster with `ReplicatedMergeTree` is recommended.

4. **Local Kafka**: Single broker. For production, use 3+ brokers with replication factor 3.
