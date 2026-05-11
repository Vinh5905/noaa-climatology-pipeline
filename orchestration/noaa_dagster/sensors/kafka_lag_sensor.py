"""Sensor: alert when Kafka consumer lag exceeds threshold."""

from dagster import RunRequest, SensorEvaluationContext, SensorResult, sensor

LAG_THRESHOLD = 1_000_000


@sensor(
    description="Alert if Kafka consumer lag > 1M messages",
    minimum_interval_seconds=60,
)
def kafka_consumer_lag_sensor(context: SensorEvaluationContext) -> SensorResult:
    try:
        from confluent_kafka.admin import AdminClient

        admin = AdminClient({"bootstrap.servers": "localhost:9092"})
        metadata = admin.list_topics(timeout=5)
        topic_name = "noaa.observations"

        if topic_name not in metadata.topics:
            return SensorResult(skip_reason="Topic noaa.observations not found")

        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer({
            "bootstrap.servers": "localhost:9092",
            "group.id": "clickhouse_noaa_consumer",
        })
        partitions = [
            TopicPartition(topic_name, p)
            for p in metadata.topics[topic_name].partitions
        ]
        committed = consumer.committed(partitions, timeout=5)
        total_lag = 0
        for tp in committed:
            lo, hi = consumer.get_watermark_offsets(tp, timeout=5)
            if tp.offset >= 0:
                total_lag += max(0, hi - tp.offset)
        consumer.close()

        context.log.info(f"Kafka consumer lag: {total_lag:,}")

        if total_lag > LAG_THRESHOLD:
            context.log.warning(
                f"Kafka lag {total_lag:,} exceeds threshold {LAG_THRESHOLD:,}"
            )
            return SensorResult(
                run_requests=[],
                dynamic_partitions_requests=[],
                skip_reason=None,
            )

        return SensorResult(skip_reason=f"Lag {total_lag:,} within threshold")

    except Exception as exc:
        context.log.warning(f"Lag sensor error: {exc}")
        return SensorResult(skip_reason=f"Error checking lag: {exc}")
