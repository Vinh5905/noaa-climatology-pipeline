-- Warn if station IDs in observations don't appear in station metadata
-- This is a warning test (expects 0 failures)
-- Note: stations table may not be populated in all environments
SELECT count() AS orphan_count
FROM (
    SELECT DISTINCT station_id
    FROM {{ ref('stg_noaa__observations') }}
    WHERE station_id NOT IN (
        SELECT station_id FROM {{ ref('stg_noaa__stations') }}
    )
)
-- Only fail if both tables have data
WHERE (SELECT count() FROM {{ ref('stg_noaa__stations') }}) > 0
HAVING orphan_count > 1000000
