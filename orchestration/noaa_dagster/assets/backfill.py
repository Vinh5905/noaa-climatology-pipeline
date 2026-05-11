"""Dagster asset: historical bulk backfill from NOAA S3."""

import logging

from dagster import AssetExecutionContext, asset

from ..resources.clickhouse import ClickHouseResource

logger = logging.getLogger(__name__)


@asset(
    group_name="ingestion",
    description="Historical observations (1900–2010) bulk-loaded from NOAA S3 into ClickHouse",
    compute_kind="clickhouse",
)
def historical_observations(
    context: AssetExecutionContext,
    clickhouse: ClickHouseResource,
) -> None:
    client = clickhouse.get_client()

    existing = client.query(
        "SELECT count() FROM noaa_raw.observations_historical"
    ).result_rows[0][0]

    if existing > 0:
        context.log.info(f"Already loaded: {existing:,} rows. Skipping backfill.")
        context.add_output_metadata({"rows": existing, "status": "skipped"})
        return

    context.log.info("Starting historical backfill via INSERT FROM s3()...")

    NOAA_S3_URL = (
        "https://datasets-documentation.s3.eu-west-3.amazonaws.com/noaa/noaa_enriched.parquet"
    )

    client.command(
        f"""
        INSERT INTO noaa_raw.observations_historical
            (station_id, date, tempAvg, tempMax, tempMin,
             precipitation, snowfall, snowDepth, percentDailySun,
             averageWindSpeed, maxWindSpeed, weatherType,
             location, elevation, name)
        SELECT
            coalesce(station_id, '') AS station_id,
            toDate32(coalesce(date, toDate('1970-01-01'))) AS date,
            coalesce(tempAvg, 0), coalesce(tempMax, 0), coalesce(tempMin, 0),
            toUInt32(coalesce(precipitation, 0)), toUInt32(coalesce(snowfall, 0)),
            toUInt32(coalesce(snowDepth, 0)),
            toUInt8(coalesce(percentDailySun, 0)),
            toUInt32(coalesce(averageWindSpeed, 0)), toUInt32(coalesce(maxWindSpeed, 0)),
            toUInt8(coalesce(weatherType, 0)) AS weatherType,
            (coalesce(location.1, 0.0), coalesce(location.2, 0.0)) AS location,
            coalesce(elevation, 0.0) AS elevation,
            coalesce(name, '') AS name
        FROM s3('{NOAA_S3_URL}', 'Parquet')
        WHERE toYear(date) BETWEEN 1763 AND 2010
        """
    )

    final_count = client.query(
        "SELECT count() FROM noaa_raw.observations_historical"
    ).result_rows[0][0]

    context.log.info(f"Backfill complete: {final_count:,} rows")
    context.add_output_metadata({"rows": final_count, "status": "loaded"})
