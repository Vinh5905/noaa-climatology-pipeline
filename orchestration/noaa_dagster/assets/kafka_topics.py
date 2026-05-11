"""Dagster asset: provision Kafka topics."""

from dagster import AssetExecutionContext, asset

from ..resources.kafka import KafkaResource


@asset(
    group_name="ingestion",
    description="Kafka topics provisioned: noaa.observations (12 partitions), noaa.stations",
    compute_kind="kafka",
)
def kafka_topics_provisioned(
    context: AssetExecutionContext,
    kafka: KafkaResource,
) -> None:
    created = []

    if kafka.ensure_topic("noaa.observations", num_partitions=12):
        context.log.info("Created topic: noaa.observations (12 partitions)")
        created.append("noaa.observations")
    else:
        context.log.info("Topic noaa.observations already exists")

    if kafka.ensure_topic("noaa.stations", num_partitions=1):
        context.log.info("Created topic: noaa.stations (1 partition)")
        created.append("noaa.stations")
    else:
        context.log.info("Topic noaa.stations already exists")

    context.add_output_metadata({"created": created, "total_topics": 2})
