"""Dagster asset: partition cleanup and TTL enforcement (Phase 11)."""

import logging

from dagster import AssetExecutionContext, asset

from ..resources.clickhouse import ClickHouseResource

logger = logging.getLogger(__name__)


@asset(
    group_name="ops",
    description="Force TTL cleanup and partition compaction for raw streaming data",
    compute_kind="clickhouse",
)
def partitions_cleanup(
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
) -> None:
    client = clickhouse.get_client()

    context.log.info("Materializing TTL for observations_streaming...")
    client.command(
        "ALTER TABLE noaa_raw.observations_streaming MATERIALIZE TTL"
    )

    context.log.info("Materializing TTL for observations_dlq...")
    client.command(
        "ALTER TABLE noaa_raw.observations_dlq MATERIALIZE TTL"
    )

    context.log.info("Running OPTIMIZE on observations_streaming...")
    client.command(
        "OPTIMIZE TABLE noaa_raw.observations_streaming FINAL"
    )

    result = client.query(
        """
        SELECT
            count() AS part_count,
            sum(rows) AS total_rows,
            formatReadableSize(sum(bytes_on_disk)) AS disk_size
        FROM system.parts
        WHERE database = 'noaa_raw'
          AND table = 'observations_streaming'
          AND active = 1
        """
    )
    row = result.result_rows[0]
    context.log.info(f"After cleanup: {row[0]} parts, {row[1]:,} rows, {row[2]}")
    context.add_output_metadata({
        "active_parts": row[0],
        "rows": row[1],
        "disk_size": row[2],
    })
