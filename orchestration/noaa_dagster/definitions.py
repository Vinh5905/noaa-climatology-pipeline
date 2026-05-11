"""Dagster Definitions — entry point for the NOAA pipeline."""

import os
from pathlib import Path

from dagster import Definitions, load_assets_from_modules
from dagster_dbt import DbtCliResource

from .assets import backfill, dbt_assets, kafka_topics, lifecycle, monitoring
from .jobs.backup_job import clickhouse_backup_job
from .jobs.retention_job import partitions_cleanup_job
from .jobs.transform_job import dbt_full_job, health_check_job
from .resources.backup import BackupResource
from .resources.clickhouse import ClickHouseResource
from .resources.kafka import KafkaResource
from .schedules import (
    clickhouse_backup_daily,
    compaction_status_daily,
    dbt_marts_hourly,
    dbt_staging_hourly,
    dbt_test_full_daily,
    partitions_cleanup_weekly,
    streaming_health_5min,
)
from .sensors.freshness_sensor import freshness_sensor
from .sensors.kafka_lag_sensor import kafka_consumer_lag_sensor

DBT_PROJECT_DIR = Path(__file__).parent.parent.parent / "transform"

all_assets = load_assets_from_modules([
    backfill,
    kafka_topics,
    dbt_assets,
    monitoring,
    lifecycle,
])

defs = Definitions(
    assets=all_assets,
    resources={
        "clickhouse": ClickHouseResource(
            host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        ),
        "kafka": KafkaResource(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
        ),
        "dbt": DbtCliResource(
            project_dir=os.fspath(DBT_PROJECT_DIR),
            profiles_dir=os.fspath(DBT_PROJECT_DIR),
        ),
        "backup": BackupResource(container_name="clickhouse-backup"),
    },
    jobs=[
        dbt_full_job,
        health_check_job,
        clickhouse_backup_job,
        partitions_cleanup_job,
    ],
    schedules=[
        streaming_health_5min,
        dbt_staging_hourly,
        dbt_marts_hourly,
        dbt_test_full_daily,
        clickhouse_backup_daily,
        compaction_status_daily,
        partitions_cleanup_weekly,
    ],
    sensors=[
        kafka_consumer_lag_sensor,
        freshness_sensor,
    ],
)
