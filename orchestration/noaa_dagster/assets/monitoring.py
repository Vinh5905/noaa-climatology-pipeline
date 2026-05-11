"""Dagster asset: pipeline health check."""

from dagster import AssetExecutionContext, asset

from ..resources.clickhouse import ClickHouseResource
from ..resources.kafka import KafkaResource


@asset(
    group_name="ops",
    description="Pipeline health check: row counts, Kafka consumers, data freshness",
    compute_kind="python",
)
def pipeline_health_check(
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
) -> None:
    client = clickhouse.get_client()

    historical = client.query(
        "SELECT count() FROM noaa_raw.observations_historical"
    ).result_rows[0][0]

    streaming = client.query(
        "SELECT count(), max(_ingested_at) FROM noaa_raw.observations_streaming"
    ).result_rows[0]

    context.log.info(f"Historical rows: {historical:,}")
    context.log.info(f"Streaming rows: {streaming[0]:,}, last_ingested: {streaming[1]}")

    kafka_consumers = client.query(
        "SELECT count() FROM system.kafka_consumers WHERE database='noaa_raw'"
    ).result_rows[0][0]

    context.log.info(f"Active Kafka consumers: {kafka_consumers}")

    context.add_output_metadata({
        "historical_rows": historical,
        "streaming_rows": streaming[0],
        "kafka_consumers": kafka_consumers,
        "last_ingested": str(streaming[1]),
    })
