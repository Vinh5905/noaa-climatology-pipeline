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
