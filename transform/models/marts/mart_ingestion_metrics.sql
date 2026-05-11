{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='metric_time'
    )
}}

-- Operational metrics for SLA monitoring and Grafana dashboards
SELECT
    now()                           AS metric_time,
    'historical'                    AS source_type,
    count()                         AS total_rows,
    min(date)                       AS earliest_date,
    max(date)                       AS latest_date,
    count(DISTINCT toYear(date))    AS year_count,
    now()                           AS updated_at
FROM {{ source('noaa_raw', 'observations_historical') }}

UNION ALL

SELECT
    now()                           AS metric_time,
    'streaming'                     AS source_type,
    count()                         AS total_rows,
    min(date)                       AS earliest_date,
    max(date)                       AS latest_date,
    count(DISTINCT toYear(date))    AS year_count,
    max(_ingested_at)               AS updated_at
FROM {{ source('noaa_raw', 'observations_streaming') }}
