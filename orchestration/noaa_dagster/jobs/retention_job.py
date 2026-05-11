"""Job: partition cleanup and TTL enforcement."""

from dagster import define_asset_job

from ..assets.lifecycle import partitions_cleanup

partitions_cleanup_job = define_asset_job(
    name="partitions_cleanup_job",
    selection=[partitions_cleanup],
    description="Enforce TTL and compact partitions in raw streaming tables",
)
