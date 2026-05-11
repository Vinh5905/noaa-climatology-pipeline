-- Fail if any observations have temperature values outside physical bounds
-- Range: -90°C to +60°C (in tenths: -900 to 600)
-- Exclude rows where tempMax = 0 (missing data placeholder)
SELECT count() AS out_of_range_count
FROM {{ ref('int_observations_enriched') }}
WHERE
    (temp_max_c < -90 OR temp_max_c > 60)
    AND temp_max_c != 0
HAVING out_of_range_count > 0
