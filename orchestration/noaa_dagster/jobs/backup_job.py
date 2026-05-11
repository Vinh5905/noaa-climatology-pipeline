"""Job: ClickHouse daily backup."""

from datetime import datetime

from dagster import OpExecutionContext, job, op

from ..resources.backup import BackupResource


@op
def run_clickhouse_backup(context: OpExecutionContext, backup: BackupResource) -> str:
    name = f"noaa-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    context.log.info(f"Creating backup: {name}")
    output = backup.create_backup(name)
    context.log.info(output)
    return name


@job(
    name="clickhouse_backup_job",
    description="Create daily ClickHouse backup via clickhouse-backup",
)
def clickhouse_backup_job() -> None:
    run_clickhouse_backup()
