-- Data freshness: how stale is the mart data?
SELECT
    source_type,
    total_rows,
    updated_at,
    dateDiff('second', updated_at, now()) AS staleness_sec,
    dateDiff('second', updated_at, now()) > 3600 AS violates_slo
FROM noaa_marts.mart_ingestion_metrics
ORDER BY staleness_sec DESC
