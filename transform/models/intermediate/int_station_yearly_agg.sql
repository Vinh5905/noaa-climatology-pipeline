{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(station_id, year)',
        partition_by='intDiv(year, 10)'
    )
}}

-- Per-station annual aggregates
SELECT
    station_id,
    year,
    country_code,
    station_name,
    latitude,
    longitude,
    elevation,
    -- Temperature stats
    avg(temp_avg_c)             AS avg_temp_c,
    max(temp_max_c)             AS max_temp_c,
    min(temp_min_c)             AS min_temp_c,
    -- Precipitation
    sum(precipitation_mm)       AS total_precipitation_mm,
    -- Wind
    avg(avg_wind_ms)            AS avg_wind_ms,
    -- Days with notable weather
    countIf(precipitation_mm > 1)   AS rainy_days,
    countIf(snowfall_mm > 0)        AS snowy_days,
    countIf(temp_max_c >= 35)       AS extreme_heat_days,
    countIf(temp_min_c <= -10)      AS extreme_cold_days,
    count()                         AS observation_days
FROM {{ ref('int_observations_enriched') }}
GROUP BY station_id, year, country_code, station_name, latitude, longitude, elevation
