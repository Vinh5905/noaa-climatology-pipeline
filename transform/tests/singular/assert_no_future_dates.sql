-- Fail if any observations have dates in the future
SELECT count() AS future_date_count
FROM {{ ref('stg_noaa__observations') }}
WHERE date > today()
HAVING future_date_count > 0
