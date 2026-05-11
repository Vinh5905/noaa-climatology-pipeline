{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(station_id, date)',
        partition_by='toYear(date)'
    )
}}

-- Enriched observations: temp in °C, precipitation in mm, wind in m/s
SELECT
    o.station_id,
    o.date,
    toYear(o.date)                          AS year,
    toMonth(o.date)                         AS month,
    -- Convert from tenths-of-degree to °C
    o.tempAvg / 10.0                        AS temp_avg_c,
    o.tempMax / 10.0                        AS temp_max_c,
    o.tempMin / 10.0                        AS temp_min_c,
    -- Convert from tenths-of-mm to mm
    o.precipitation / 10.0                  AS precipitation_mm,
    o.snowfall                              AS snowfall_mm,
    o.snowDepth                             AS snow_depth_mm,
    o.percentDailySun                       AS pct_sun,
    -- Convert from tenths-of-m/s to m/s
    o.averageWindSpeed / 10.0               AS avg_wind_ms,
    o.maxWindSpeed / 10.0                   AS max_wind_ms,
    o.weatherType,
    o.longitude,
    o.latitude,
    o.elevation,
    trim(o.name)                            AS station_name,
    -- Country code from first 2 chars of station_id (NOAA convention)
    substring(o.station_id, 1, 2)           AS country_code,
    o.source_type
FROM {{ ref('stg_noaa__observations') }} o
WHERE
    -- Valid temperature range: -90°C to +60°C (tenths)
    (o.tempMax = 0 OR (o.tempMax >= -900 AND o.tempMax <= 600))
    -- Valid date
    AND o.date IS NOT NULL
