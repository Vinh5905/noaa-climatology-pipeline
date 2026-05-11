-- Ingestion rate: rows per second over last 60 seconds
SELECT
    count() / 60 AS rows_per_sec,
    count() AS rows_last_60s,
    max(_ingested_at) AS last_insert_at
FROM noaa_raw.observations_streaming
WHERE _ingested_at > now() - INTERVAL 60 SECOND
