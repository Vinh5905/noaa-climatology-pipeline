"""Sensor: alert when mart data freshness exceeds SLO threshold."""

from dagster import SensorEvaluationContext, SensorResult, sensor

STALENESS_THRESHOLD_SECONDS = 7200  # 2 hours


@sensor(
    description="Alert if mart_ingestion_metrics data is stale > 2 hours",
    minimum_interval_seconds=300,
)
def freshness_sensor(context: SensorEvaluationContext) -> SensorResult:
    try:
        import os

        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        )

        result = client.query(
            """
            SELECT
                source_type,
                dateDiff('second', updated_at, now()) AS staleness_sec
            FROM noaa_marts.mart_ingestion_metrics
            ORDER BY staleness_sec DESC
            LIMIT 2
            """
        )

        max_staleness = 0
        for row in result.result_rows:
            source_type, staleness = row
            context.log.info(f"Freshness [{source_type}]: {staleness}s stale")
            max_staleness = max(max_staleness, staleness)

        if max_staleness > STALENESS_THRESHOLD_SECONDS:
            context.log.warning(
                f"Data staleness {max_staleness}s exceeds SLO threshold "
                f"{STALENESS_THRESHOLD_SECONDS}s. See SLA.md §SLO-001."
            )

        return SensorResult(
            skip_reason=f"Max staleness: {max_staleness}s "
                        f"({'ALERT' if max_staleness > STALENESS_THRESHOLD_SECONDS else 'OK'})"
        )

    except Exception as exc:
        return SensorResult(skip_reason=f"Freshness check error: {exc}")
