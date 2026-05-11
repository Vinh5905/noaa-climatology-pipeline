"""Job definitions for dbt transform pipeline."""

from dagster import define_asset_job

from ..assets.dbt_assets import noaa_dbt_assets
from ..assets.monitoring import pipeline_health_check

# Run all dbt models
dbt_full_job = define_asset_job(
    name="dbt_full_build",
    selection=[noaa_dbt_assets],
    description="Run all dbt models: staging → intermediate → marts",
)

# Run only staging + intermediate
dbt_staging_job = define_asset_job(
    name="dbt_staging_intermediate",
    selection="tag:staging or tag:intermediate",
    description="Refresh staging and intermediate dbt layers",
)

# Health check job
health_check_job = define_asset_job(
    name="pipeline_health_check_job",
    selection=[pipeline_health_check],
    description="Check pipeline row counts and Kafka consumers",
)
