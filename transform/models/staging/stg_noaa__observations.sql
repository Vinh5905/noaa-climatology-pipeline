{{
    config(
        materialized='view'
    )
}}

-- Unified staging: historical + streaming observations
-- Normalizes types, filters invalid dates, renames to standard schema
WITH historical AS (
    SELECT
        station_id,
        date,
        tempAvg,
        tempMax,
        tempMin,
        toInt32(precipitation)      AS precipitation,
        toInt32(snowfall)           AS snowfall,
        toInt32(snowDepth)          AS snowDepth,
        toInt8(percentDailySun)     AS percentDailySun,
        toInt32(averageWindSpeed)   AS averageWindSpeed,
        toInt32(maxWindSpeed)       AS maxWindSpeed,
        toInt8(weatherType)         AS weatherType,
        location.1                  AS longitude,
        location.2                  AS latitude,
        elevation,
        name,
        'historical'                AS source_type
    FROM {{ source('noaa_raw', 'observations_historical') }}
    WHERE date <= today()
      AND date >= toDate32('1900-01-01')
),

streaming AS (
    SELECT
        station_id,
        date,
        tempAvg,
        tempMax,
        tempMin,
        precipitation,
        snowfall,
        snowDepth,
        percentDailySun,
        averageWindSpeed,
        maxWindSpeed,
        weatherType,
        lon                         AS longitude,
        lat                         AS latitude,
        elevation,
        name,
        'streaming'                 AS source_type
    FROM {{ source('noaa_raw', 'observations_streaming') }}
    WHERE date <= today()
      AND date >= toDate32('1900-01-01')
)

SELECT * FROM historical
UNION ALL
SELECT * FROM streaming
