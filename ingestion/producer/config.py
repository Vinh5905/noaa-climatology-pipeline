"""Producer configuration and Kafka settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def get_kafka_config() -> dict:
    """Return librdkafka producer config tuned for high throughput."""
    return {
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
        "linger.ms": int(os.getenv("PRODUCER_LINGER_MS", "5")),
        "batch.num.messages": int(os.getenv("PRODUCER_BATCH_SIZE", "10000")),
        "compression.type": "lz4",
        "queue.buffering.max.kbytes": 1048576,
        "queue.buffering.max.messages": 1000000,
        "acks": "1",
        "retries": 3,
        "retry.backoff.ms": 100,
    }


KAFKA_TOPIC_OBSERVATIONS = os.getenv("KAFKA_TOPIC_OBSERVATIONS", "noaa.observations")
KAFKA_TOPIC_STATIONS = os.getenv("KAFKA_TOPIC_STATIONS", "noaa.stations")
PRODUCER_RATE_PER_SEC = int(os.getenv("PRODUCER_RATE_PER_SEC", "500000"))
NOAA_S3_URL = "https://datasets-documentation.s3.eu-west-3.amazonaws.com/noaa/noaa_enriched.parquet"
