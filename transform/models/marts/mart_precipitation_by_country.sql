{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(country_code, year)'
    )
}}

-- Annual precipitation by country
SELECT
    country_code,
    year,
    count(DISTINCT station_id)          AS station_count,
    round(avg(total_precipitation_mm), 1) AS avg_precipitation_mm,
    toUInt64(sum(total_precipitation_mm)) AS country_total_precipitation_mm,
    round(avg(rainy_days), 1)           AS avg_rainy_days
FROM {{ ref('int_station_yearly_agg') }}
WHERE country_code != ''
  AND observation_days >= 30
GROUP BY country_code, year
ORDER BY country_code, year
