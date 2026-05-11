"""Load NOAA GHCN-D station metadata into noaa_raw.stations via INSERT FROM url()."""

import logging
import os
import sys
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("backfill.load_stations")

# NOAA GHCN stations metadata — fixed-width format
STATIONS_URL = "https://datasets-documentation.s3.eu-west-3.amazonaws.com/noaa/noaa_enriched/stations.parquet"


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        database="noaa_raw",
        connect_timeout=30,
        send_receive_timeout=600,
    )


def stations_already_loaded(client: clickhouse_connect.driver.Client) -> bool:
    result = client.query("SELECT count() FROM noaa_raw.stations")
    return result.result_rows[0][0] > 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Load NOAA station metadata")
    parser.add_argument(
        "--force", action="store_true", help="Reload even if stations already exist"
    )
    args = parser.parse_args()

    client = get_client()

    if not args.force and stations_already_loaded(client):
        count = client.query("SELECT count() FROM noaa_raw.stations").result_rows[0][0]
        logger.info(f"Stations already loaded ({count:,} rows). Use --force to reload.")
        return

    logger.info(f"Loading station metadata from {STATIONS_URL}")

    client.command(
        f"""
        INSERT INTO noaa_raw.stations (id, name, country, state, latitude, longitude, elevation, wmo_id)
        SELECT
            station_id AS id,
            name,
            country,
            state,
            latitude,
            longitude,
            elevation,
            wmo_id
        FROM s3('{STATIONS_URL}', 'Parquet')
        """
    )

    count = client.query("SELECT count() FROM noaa_raw.stations").result_rows[0][0]
    logger.info(f"Stations loaded: {count:,} rows")


if __name__ == "__main__":
    main()
