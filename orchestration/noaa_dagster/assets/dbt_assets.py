"""Dagster dbt assets — each dbt model becomes an asset with automatic lineage."""

from pathlib import Path

from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, dbt_assets, DbtProject

DBT_PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "transform"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR, profiles_dir=DBT_PROJECT_DIR)
dbt_project.prepare_if_dev()


@dbt_assets(manifest=dbt_project.manifest_path)
def noaa_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
