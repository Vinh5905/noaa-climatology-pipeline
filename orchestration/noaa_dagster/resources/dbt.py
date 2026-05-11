"""dbt resource for Dagster."""

import os
from pathlib import Path

from dagster_dbt import DbtCliResource

DBT_PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "transform"


def get_dbt_resource() -> DbtCliResource:
    return DbtCliResource(
        project_dir=os.fspath(DBT_PROJECT_DIR),
        profiles_dir=os.fspath(DBT_PROJECT_DIR),
    )
