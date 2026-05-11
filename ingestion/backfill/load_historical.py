"""Bulk backfill NOAA GHCN-D historical observations via INSERT FROM s3()."""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("backfill.load_historical")

# NOAA GHCN-D dataset — single enriched Parquet file (1B+ rows)
# Source: https://clickhouse.com/docs/getting-started/example-datasets/noaa
NOAA_S3_URL = "https://datasets-documentation.s3.eu-west-3.amazonaws.com/noaa/noaa_enriched.parquet"

INSERT_COLUMNS = """
    station_id, date, tempAvg, tempMax, tempMin,
    precipitation, snowfall, snowDepth, percentDailySun,
    averageWindSpeed, maxWindSpeed, weatherType,
    location, elevation, name
"""

SELECT_COLUMNS = """
    coalesce(station_id, '') AS station_id,
    toDate32(coalesce(date, toDate('1970-01-01'))) AS date,
    coalesce(tempAvg, 0) AS tempAvg,
    coalesce(tempMax, 0) AS tempMax,
    coalesce(tempMin, 0) AS tempMin,
    toUInt32(coalesce(precipitation, 0)) AS precipitation,
    toUInt32(coalesce(snowfall, 0)) AS snowfall,
    toUInt32(coalesce(snowDepth, 0)) AS snowDepth,
    toUInt8(coalesce(percentDailySun, 0)) AS percentDailySun,
    toUInt32(coalesce(averageWindSpeed, 0)) AS averageWindSpeed,
    toUInt32(coalesce(maxWindSpeed, 0)) AS maxWindSpeed,
    toUInt8(coalesce(weatherType, 0)) AS weatherType,
    (coalesce(location.1, 0.0), coalesce(location.2, 0.0)) AS location,
    coalesce(elevation, 0.0) AS elevation,
    coalesce(name, '') AS name
"""


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        database="noaa_raw",
        connect_timeout=30,
        send_receive_timeout=7200,
    )


def already_loaded(client: clickhouse_connect.driver.Client) -> bool:
    """Check if any data exists in observations_historical."""
    result = client.query("SELECT count() FROM noaa_raw.observations_historical")
    return result.result_rows[0][0] > 0


def load_historical(
    client: clickhouse_connect.driver.Client,
    start_year: int,
    end_year: int,
) -> tuple[int, float]:
    """Load observations filtered by year range. Returns (rows_added, seconds)."""
    logger.info(
        f"Loading years {start_year}–{end_year} from {NOAA_S3_URL}"
    )

    start = time.time()
    client.command(
        f"""
        INSERT INTO noaa_raw.observations_historical
            ({INSERT_COLUMNS})
        SELECT
            {SELECT_COLUMNS}
        FROM s3('{NOAA_S3_URL}', 'Parquet')
        WHERE toYear(date) BETWEEN {start_year} AND {end_year}
        """
    )
    elapsed = time.time() - start

    row_count = client.query(
        """
        SELECT count()
        FROM noaa_raw.observations_historical
        WHERE toYear(date) BETWEEN %(start)s AND %(end)s
        """,
        parameters={"start": start_year, "end": end_year},
    ).result_rows[0][0]

    logger.info(
        f"Loaded {row_count:,} rows for {start_year}–{end_year} in {elapsed:.1f}s"
    )
    return row_count, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk backfill NOAA historical observations")
    parser.add_argument(
        "--start-year", type=int, default=1763, help="First year to load (default: 1763)"
    )
    parser.add_argument(
        "--end-year", type=int, default=2010, help="Last year to load inclusive (default: 2010)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reload even if data already exists",
    )
    args = parser.parse_args()

    if args.start_year > args.end_year:
        logger.error("start-year must be <= end-year")
        sys.exit(1)

    client = get_client()

    if not args.force and already_loaded(client):
        count = client.query(
            "SELECT count() FROM noaa_raw.observations_historical"
        ).result_rows[0][0]
        logger.info(
            f"Data already loaded ({count:,} rows). Use --force to reload."
        )
        return

    logger.info(
        f"Starting historical backfill: {args.start_year}–{args.end_year} "
        f"({'force reload' if args.force else 'fresh load'})"
    )
    logger.info(f"Source: {NOAA_S3_URL}")
    logger.warning(
        "This operation reads ~1B rows from S3. Expected duration: 20–60 minutes "
        "depending on network speed."
    )

    start = time.time()
    rows, elapsed = load_historical(client, args.start_year, args.end_year)
    total_time = time.time() - start

    logger.info(
        f"Backfill complete: {rows:,} rows in {total_time:.1f}s "
        f"({rows / total_time:,.0f} rows/s)"
    )


if __name__ == "__main__":
    main()
