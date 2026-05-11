"""High-throughput NOAA observations Kafka producer.

Uses confluent-kafka (librdkafka) for maximum throughput.
Target: ~1M rows/s (realistic on laptop: 200K–800K rows/s).

Supports two data sources:
  --source parquet  Read from local Parquet cache (downloads 2.3GB on first run)
  --source clickhouse  Read from ClickHouse (fast, requires Docker network access)

Message key = station_id|date for idempotent consumer deduplication.
Serialization: JSON (production would use Avro + Schema Registry).
"""

import argparse
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from confluent_kafka import KafkaError, Producer
from pydantic import BaseModel, field_validator

from .config import KAFKA_TOPIC_OBSERVATIONS, NOAA_S3_URL, get_kafka_config
from .rate_limiter import TokenBucketRateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("producer.noaa_producer")

_LOCAL_CACHE = Path(os.getenv("NOAA_LOCAL_CACHE", "/tmp/noaa_enriched.parquet"))


class ObservationRecord(BaseModel):
    """Pydantic model for NOAA observation — validates before sending to Kafka."""

    station_id: str
    date: str
    tempAvg: int
    tempMax: int
    tempMin: int
    precipitation: int
    snowfall: int
    snowDepth: int
    percentDailySun: int
    averageWindSpeed: int
    maxWindSpeed: int
    weatherType: int
    lat: float
    lon: float
    elevation: float
    name: str

    @field_validator("station_id")
    @classmethod
    def station_id_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("station_id cannot be empty")
        return v

    @field_validator("weatherType")
    @classmethod
    def weather_type_valid(cls, v: int) -> int:
        if not (0 <= v <= 20):
            raise ValueError(f"weatherType {v} out of range 0–20")
        return v


def delivery_report(err: KafkaError | None, _msg: Any) -> None:
    if err is not None:
        logger.warning(f"Delivery failed: {err}")


def row_to_record(row: dict) -> ObservationRecord | None:
    """Convert a data row to ObservationRecord, returning None on error."""
    try:
        location = row.get("location") or {}
        if isinstance(location, dict):
            lat = float(location.get("2") or location.get("lat") or 0.0)
            lon = float(location.get("1") or location.get("lon") or 0.0)
        elif isinstance(location, (list, tuple)) and len(location) >= 2:
            lon, lat = float(location[0]), float(location[1])
        else:
            lat, lon = 0.0, 0.0

        date_val = row.get("date")
        date_str = str(date_val) if date_val else "1970-01-01"

        return ObservationRecord(
            station_id=str(row.get("station_id") or ""),
            date=date_str,
            tempAvg=int(row.get("tempAvg") or 0),
            tempMax=int(row.get("tempMax") or 0),
            tempMin=int(row.get("tempMin") or 0),
            precipitation=int(row.get("precipitation") or 0),
            snowfall=int(row.get("snowfall") or 0),
            snowDepth=int(row.get("snowDepth") or 0),
            percentDailySun=int(row.get("percentDailySun") or 0),
            averageWindSpeed=int(row.get("averageWindSpeed") or 0),
            maxWindSpeed=int(row.get("maxWindSpeed") or 0),
            weatherType=int(row.get("weatherType") or 0),
            lat=lat,
            lon=lon,
            elevation=float(row.get("elevation") or 0.0),
            name=str(row.get("name") or "").strip(),
        )
    except Exception:
        return None


def _ensure_local_cache() -> Path:
    """Download NOAA Parquet to local cache if not already present."""
    if _LOCAL_CACHE.exists():
        logger.info(f"Using cached Parquet file: {_LOCAL_CACHE}")
        return _LOCAL_CACHE

    logger.info(f"Downloading NOAA dataset to {_LOCAL_CACHE} (~2.3 GB, one-time)...")
    import urllib.request

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0 and block_num % 2000 == 0:
            pct = min(block_num * block_size * 100 // total_size, 100)
            logger.info(f"  {block_num * block_size // 1024 // 1024} MB ({pct}%)")

    urllib.request.urlretrieve(NOAA_S3_URL, _LOCAL_CACHE, reporthook=_progress)
    logger.info(f"Download complete: {_LOCAL_CACHE}")
    return _LOCAL_CACHE


def rows_from_parquet(years: list[int] | None, max_rows: int | None) -> Iterator[dict]:
    """Yield rows from local Parquet cache, filtered by year."""
    source_path = _ensure_local_cache()
    logger.info(f"Streaming from Parquet: {source_path}")

    filters = _build_year_filter(years) if years else None
    table = pq.read_table(source_path, filters=filters)
    logger.info(f"Loaded {len(table):,} rows from Parquet")

    count = 0
    for batch in table.to_batches(max_chunksize=10000):
        for row in batch.to_pylist():
            if max_rows and count >= max_rows:
                return
            yield row
            count += 1


def rows_from_clickhouse(years: list[int] | None, max_rows: int | None) -> Iterator[dict]:
    """Yield rows from ClickHouse observations_historical, filtered by year."""
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
    )

    year_filter = ""
    if years:
        year_filter = f"WHERE toYear(date) BETWEEN {min(years)} AND {max(years)}"

    limit = f"LIMIT {max_rows}" if max_rows else ""
    query = f"""
        SELECT
            station_id,
            toString(date) AS date_str,
            tempAvg, tempMax, tempMin,
            precipitation, snowfall, snowDepth,
            percentDailySun, averageWindSpeed, maxWindSpeed,
            toUInt8(weatherType) AS weatherType,
            location.1 AS lon,
            location.2 AS lat,
            elevation, name
        FROM noaa_raw.observations_historical
        {year_filter}
        ORDER BY date
        {limit}
    """

    logger.info(f"Streaming from ClickHouse: {year_filter or 'all years'}")
    result = client.query(query)
    cols = result.column_names
    logger.info(f"Loaded {len(result.result_rows):,} rows from ClickHouse")

    for row_tuple in result.result_rows:
        row = dict(zip(cols, row_tuple))
        row["date"] = row.pop("date_str", "1970-01-01")
        row["location"] = {"1": row.pop("lon", 0.0), "2": row.pop("lat", 0.0)}
        yield row


def produce_rows(
    row_iterator: Iterator[dict],
    producer: Producer,
    topic: str,
    rate_limiter: TokenBucketRateLimiter,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Produce rows to Kafka from an iterator. Returns (sent, errors)."""
    sent = 0
    errors = 0
    start = time.time()
    last_report = start

    for row in row_iterator:
        record = row_to_record(row)
        if record is None:
            errors += 1
            continue

        rate_limiter.acquire(1)

        key = f"{record.station_id}|{record.date}"
        value = record.model_dump_json().encode("utf-8")

        if not dry_run:
            producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=value,
                on_delivery=delivery_report,
            )
            producer.poll(0)

        sent += 1

        now = time.time()
        if now - last_report >= 1.0:
            elapsed = now - start
            actual_rate = sent / elapsed
            logger.info(
                f"[rate] target={rate_limiter.rate:.0f} actual={actual_rate:.0f} rows/s"
                f"  sent={sent:,}  errors={errors}"
            )
            last_report = now

    if not dry_run:
        producer.flush()

    return sent, errors


def _build_year_filter(years: list[int]) -> list:
    """Build PyArrow filters for year selection."""
    from datetime import date

    return [
        ("date", ">=", date(min(years), 1, 1)),
        ("date", "<=", date(max(years), 12, 31)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="High-throughput NOAA Kafka producer")
    parser.add_argument(
        "--rate",
        type=int,
        default=500000,
        help="Target rows/second (default: 500000)",
    )
    parser.add_argument(
        "--years",
        type=str,
        default=None,
        help="Comma-separated years, e.g. 2011,2012,2013",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Stop after N rows (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate but don't send to Kafka",
    )
    parser.add_argument(
        "--source",
        choices=["parquet", "clickhouse"],
        default="parquet",
        help="Data source: 'parquet' (local cache) or 'clickhouse' (Docker network)",
    )
    parser.add_argument(
        "--topic",
        default=KAFKA_TOPIC_OBSERVATIONS,
        help=f"Kafka topic (default: {KAFKA_TOPIC_OBSERVATIONS})",
    )
    args = parser.parse_args()

    years: list[int] | None = None
    if args.years:
        years = [int(y.strip()) for y in args.years.split(",")]

    logger.info(
        f"Starting producer: rate={args.rate} rows/s  "
        f"source={args.source}  years={years}  "
        f"max_rows={args.max_rows}  dry_run={args.dry_run}"
    )

    config = get_kafka_config()
    producer = Producer(config)
    rate_limiter = TokenBucketRateLimiter(rate=args.rate)

    if args.source == "clickhouse":
        row_iter = rows_from_clickhouse(years, args.max_rows)
    else:
        row_iter = rows_from_parquet(years, args.max_rows)

    start = time.time()
    sent, errors = produce_rows(
        row_iterator=row_iter,
        producer=producer,
        topic=args.topic,
        rate_limiter=rate_limiter,
        dry_run=args.dry_run,
    )
    elapsed = time.time() - start

    logger.info(
        f"Done: sent={sent:,}  errors={errors}  "
        f"elapsed={elapsed:.1f}s  "
        f"avg_rate={sent / elapsed:,.0f} rows/s"
    )

    if errors > 0:
        logger.warning(f"{errors} rows failed validation")


if __name__ == "__main__":
    main()
