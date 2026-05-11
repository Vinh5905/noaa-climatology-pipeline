"""Verify backfill completeness: row counts, date ranges, partition sizes."""

import logging
import os
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("backfill.verify")


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        connect_timeout=30,
    )


def verify(client: clickhouse_connect.driver.Client) -> bool:
    ok = True

    # Total row count
    total = client.query(
        "SELECT count() FROM noaa_raw.observations_historical"
    ).result_rows[0][0]
    logger.info(f"Total rows: {total:,}")

    # Date range
    result = client.query(
        "SELECT min(date), max(date) FROM noaa_raw.observations_historical"
    )
    min_date, max_date = result.result_rows[0]
    logger.info(f"Date range: {min_date} → {max_date}")

    # Partition stats
    parts = client.query(
        """
        SELECT
            partition,
            sum(rows) AS rows,
            formatReadableSize(sum(bytes_on_disk)) AS size
        FROM system.parts
        WHERE database = 'noaa_raw'
          AND table = 'observations_historical'
          AND active = 1
        GROUP BY partition
        ORDER BY partition
        """
    )
    logger.info(f"Partitions loaded: {len(parts.result_rows)}")
    for row in parts.result_rows[:10]:
        logger.info(f"  partition={row[0]}  rows={row[1]:,}  size={row[2]}")
    if len(parts.result_rows) > 10:
        logger.info(f"  ... and {len(parts.result_rows) - 10} more partitions")

    # Station count
    stations = client.query("SELECT count() FROM noaa_raw.stations").result_rows[0][0]
    logger.info(f"Stations loaded: {stations:,}")

    # Basic validation
    if total == 0:
        logger.error("FAIL: observations_historical is empty")
        ok = False
    if stations == 0:
        logger.warning("WARN: stations table is empty — run load_stations.py")

    return ok


def main() -> None:
    client = get_client()
    logger.info("=== Backfill Verification ===")
    success = verify(client)
    if success:
        logger.info("Verification PASSED")
    else:
        logger.error("Verification FAILED")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
