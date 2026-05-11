{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='year'
    )
}}

-- Global average temperature by year
SELECT
    year,
    count(DISTINCT station_id)      AS station_count,
    round(avg(avg_temp_c), 2)       AS global_avg_temp_c,
    round(avg(max_temp_c), 2)       AS global_avg_max_temp_c,
    round(avg(min_temp_c), 2)       AS global_avg_min_temp_c,
    round(avg(total_precipitation_mm), 1) AS avg_precipitation_mm,
    sum(observation_days)           AS total_observations,
    now()                           AS updated_at
FROM {{ ref('int_station_yearly_agg') }}
WHERE year >= 1900
GROUP BY year
ORDER BY year
