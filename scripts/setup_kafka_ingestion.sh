#!/usr/bin/env bash
set -euo pipefail
# Setup Kafka → ClickHouse ingestion pipeline (Phase 4)

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "=== Setting up Kafka Ingestion Pipeline ==="

# Create Kafka topic
echo "Creating Kafka topics..."
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic noaa.observations \
  --partitions 12 \
  --replication-factor 1

docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic noaa.stations \
  --partitions 1 \
  --replication-factor 1

# Create ClickHouse Kafka Engine + MV + DLQ
echo "Creating ClickHouse Kafka Engine tables..."
docker exec -i clickhouse clickhouse-client --multiquery << 'SQL'
CREATE TABLE IF NOT EXISTS noaa_raw.observations_kafka
(
    station_id      String,
    date            String,
    tempAvg         Int32,
    tempMax         Int32,
    tempMin         Int32,
    precipitation   Int32,
    snowfall        Int32,
    snowDepth       Int32,
    percentDailySun Int8,
    averageWindSpeed Int32,
    maxWindSpeed    Int32,
    weatherType     Int8,
    lat             Float64,
    lon             Float64,
    elevation       Float32,
    name            String
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
    station_id      LowCardinality(String),
    date            Date32,
    tempAvg         Int32 CODEC(Delta, ZSTD),
    tempMax         Int32 CODEC(Delta, ZSTD),
    tempMin         Int32 CODEC(Delta, ZSTD),
    precipitation   Int32 CODEC(ZSTD),
    snowfall        Int32 CODEC(ZSTD),
    snowDepth       Int32 CODEC(ZSTD),
    percentDailySun Int8,
    averageWindSpeed Int32,
    maxWindSpeed    Int32,
    weatherType     Int8,
    lat             Float64,
    lon             Float64,
    elevation       Float32,
    name            LowCardinality(String),
    _kafka_offset   UInt64,
    _kafka_partition UInt32,
    _ingested_at    DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYear(date)
ORDER BY (station_id, date)
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS noaa_raw.observations_mv
TO noaa_raw.observations_streaming AS
SELECT
    station_id,
    toDate32(date) AS date,
    tempAvg, tempMax, tempMin,
    precipitation, snowfall, snowDepth,
    percentDailySun, averageWindSpeed, maxWindSpeed,
    weatherType, lat, lon, elevation, name,
    _offset AS _kafka_offset,
    _partition AS _kafka_partition,
    now() AS _ingested_at
FROM noaa_raw.observations_kafka;

CREATE TABLE IF NOT EXISTS noaa_raw.observations_dlq
(
    raw_message     String,
    error           String,
    _kafka_offset   UInt64,
    _kafka_partition UInt32,
    _ingested_at    DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (_ingested_at, _kafka_partition)
SETTINGS index_granularity = 8192;

CREATE OR REPLACE VIEW noaa_raw.observations_all AS
SELECT
    station_id, date, tempAvg, tempMax, tempMin,
    precipitation, snowfall, snowDepth, percentDailySun,
    averageWindSpeed, maxWindSpeed,
    toInt8(weatherType) AS weatherType,
    (lon, lat) AS location, elevation, name
FROM noaa_raw.observations_streaming
UNION ALL
SELECT
    station_id, date, tempAvg, tempMax, tempMin,
    toInt32(precipitation), toInt32(snowfall), toInt32(snowDepth),
    toInt8(percentDailySun), toInt32(averageWindSpeed), toInt32(maxWindSpeed),
    toInt8(weatherType) AS weatherType,
    location, elevation, name
FROM noaa_raw.observations_historical;
SQL

echo "Kafka ingestion setup complete."
