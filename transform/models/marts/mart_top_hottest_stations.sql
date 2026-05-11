{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(station_id)'
    )
}}

-- Top stations by all-time maximum temperature
SELECT
    station_id,
    station_name,
    country_code,
    latitude,
    longitude,
    elevation,
    max(max_temp_c)         AS all_time_max_temp_c,
    min(min_temp_c)         AS all_time_min_temp_c,
    avg(avg_temp_c)         AS avg_annual_temp_c,
    count()                 AS years_of_data
FROM {{ ref('int_station_yearly_agg') }}
WHERE observation_days >= 100
GROUP BY station_id, station_name, country_code, latitude, longitude, elevation
ORDER BY all_time_max_temp_c DESC
LIMIT 500
