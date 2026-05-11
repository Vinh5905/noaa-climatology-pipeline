{{
    config(
        materialized='view'
    )
}}

SELECT
    id                          AS station_id,
    trim(name)                  AS station_name,
    country,
    state,
    latitude,
    longitude,
    elevation,
    wmo_id,
    loaded_at
FROM {{ source('noaa_raw', 'stations') }}
WHERE id != ''
