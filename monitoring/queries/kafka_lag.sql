-- Kafka consumer lag: offset behind per partition
SELECT
    _kafka_partition,
    max(_kafka_offset) AS clickhouse_latest_offset,
    count() AS rows_in_partition
FROM noaa_raw.observations_streaming
GROUP BY _kafka_partition
ORDER BY _kafka_partition
