{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(date, station_id)'
    )
}}

-- Extreme weather events: record temps, heavy precipitation
SELECT
    station_id,
    date,
    year,
    country_code,
    station_name,
    latitude,
    longitude,
    temp_max_c,
    temp_min_c,
    precipitation_mm,
    snowfall_mm,
    weatherType,
    CASE
        WHEN temp_max_c >= 45  THEN 'extreme_heat'
        WHEN temp_min_c <= -30 THEN 'extreme_cold'
        WHEN precipitation_mm >= 100 THEN 'heavy_rain'
        WHEN snowfall_mm >= 300 THEN 'heavy_snow'
        WHEN weatherType IN (10) THEN 'tornado'
        ELSE 'other'
    END AS event_type
FROM {{ ref('int_observations_enriched') }}
WHERE
    temp_max_c >= 45
    OR temp_min_c <= -30
    OR precipitation_mm >= 100
    OR snowfall_mm >= 300
    OR weatherType = 10
