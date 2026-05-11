-- v1: created 2026-05-11
-- Initialize NOAA databases and tables on ClickHouse startup

CREATE DATABASE IF NOT EXISTS noaa_raw;
CREATE DATABASE IF NOT EXISTS noaa_staging;
CREATE DATABASE IF NOT EXISTS noaa_marts;
CREATE DATABASE IF NOT EXISTS noaa_ops;

-- Historical observations (bulk backfill from NOAA S3)
CREATE TABLE IF NOT EXISTS noaa_raw.observations_historical (
    station_id      LowCardinality(String),
    date            Date32,  -- Date32 needed for dates before 1970
    tempAvg         Int32 CODEC(Delta, ZSTD),
    tempMax         Int32 CODEC(Delta, ZSTD),
    tempMin         Int32 CODEC(Delta, ZSTD),
    precipitation   UInt32 CODEC(ZSTD),
    snowfall        UInt32 CODEC(ZSTD),
    snowDepth       UInt32 CODEC(ZSTD),
    percentDailySun UInt8,
    averageWindSpeed UInt32,
    maxWindSpeed    UInt32,
    weatherType     Enum8(
        'Normal'=0, 'Fog'=1, 'HeavyFog'=2, 'Thunder'=3, 'SmallHail'=4,
        'Hail'=5, 'Glaze'=6, 'Dust'=7, 'Smoke'=8, 'Blowing'=9,
        'Tornado'=10, 'HighWind'=11, 'Mist'=12, 'Drizzle'=13,
        'FreezingDrizzle'=14, 'Rain'=15, 'FreezingRain'=16, 'Snow'=17,
        'UnknownPrecip'=18, 'Ground'=19, 'Freezing'=20
    ),
    location        Point,
    elevation       Float32,
    name            LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYear(date)
ORDER BY (station_id, date)
SETTINGS index_granularity = 8192;

-- Station metadata (one-time load)
CREATE TABLE IF NOT EXISTS noaa_raw.stations (
    id          LowCardinality(String),
    name        String,
    country     LowCardinality(String),
    state       LowCardinality(String),
    latitude    Float32,
    longitude   Float32,
    elevation   Float32,
    wmo_id      Nullable(String),
    loaded_at   DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY id
SETTINGS index_granularity = 8192;

-- Streaming ingestion tables (Kafka Engine)
CREATE TABLE IF NOT EXISTS noaa_raw.observations_kafka
(
    station_id String, date String, tempAvg Int32, tempMax Int32, tempMin Int32,
    precipitation Int32, snowfall Int32, snowDepth Int32, percentDailySun Int8,
    averageWindSpeed Int32, maxWindSpeed Int32, weatherType Int8,
    lat Float64, lon Float64, elevation Float32, name String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:29092',
    kafka_topic_list = 'noaa.observations',
    kafka_group_name = 'clickhouse_noaa_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 4,
    kafka_max_block_size = 100000;

CREATE TABLE IF NOT EXISTS noaa_raw.observations_streaming
(
    station_id LowCardinality(String), date Date32,
    tempAvg Int32 CODEC(Delta, ZSTD), tempMax Int32 CODEC(Delta, ZSTD),
    tempMin Int32 CODEC(Delta, ZSTD), precipitation Int32 CODEC(ZSTD),
    snowfall Int32 CODEC(ZSTD), snowDepth Int32 CODEC(ZSTD),
    percentDailySun Int8, averageWindSpeed Int32, maxWindSpeed Int32,
    weatherType Int8, lat Float64, lon Float64, elevation Float32,
    name LowCardinality(String),
    _kafka_offset UInt64, _kafka_partition UInt32, _ingested_at DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYear(date)
ORDER BY (station_id, date)
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS noaa_raw.observations_mv
TO noaa_raw.observations_streaming AS
SELECT station_id, toDate32(date) AS date, tempAvg, tempMax, tempMin,
    precipitation, snowfall, snowDepth, percentDailySun, averageWindSpeed,
    maxWindSpeed, weatherType, lat, lon, elevation, name,
    _offset AS _kafka_offset, _partition AS _kafka_partition, now() AS _ingested_at
FROM noaa_raw.observations_kafka;

CREATE TABLE IF NOT EXISTS noaa_raw.observations_dlq
(
    raw_message String, error String,
    _kafka_offset UInt64, _kafka_partition UInt32, _ingested_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (_ingested_at, _kafka_partition)
SETTINGS index_granularity = 8192;

-- Phase 11: TTL policies (applied after tables are created)
-- These ALTER TABLE commands are idempotent
ALTER TABLE IF EXISTS noaa_raw.observations_streaming MODIFY TTL _ingested_at + INTERVAL 90 DAY;
ALTER TABLE IF EXISTS noaa_raw.observations_dlq MODIFY TTL _ingested_at + INTERVAL 30 DAY;
