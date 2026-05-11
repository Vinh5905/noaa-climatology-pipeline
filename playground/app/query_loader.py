"""Load predefined queries from YAML files."""

import hashlib
from pathlib import Path

import yaml

from .models import QueryDefinition

QUERIES_DIR = Path(__file__).parent.parent / "queries"

_cache: dict[str, QueryDefinition] | None = None


def _make_id(category: str, filename: str) -> str:
    return f"{category}/{filename.replace('.yaml', '').replace('.yml', '')}"


def load_all_queries() -> dict[str, list[QueryDefinition]]:
    """Return queries grouped by category."""
    result: dict[str, list[QueryDefinition]] = {}
    for category_dir in sorted(QUERIES_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        queries = []
        for yaml_file in sorted(category_dir.glob("*.yaml")):
            try:
                with yaml_file.open() as f:
                    data = yaml.safe_load(f)
                qid = _make_id(category, yaml_file.name)
                queries.append(
                    QueryDefinition(
                        id=qid,
                        name=data.get("name", yaml_file.stem),
                        description=data.get("description", ""),
                        category=category,
                        tags=data.get("tags", []),
                        sql=data.get("sql", "").strip(),
                    )
                )
            except Exception:
                pass
        if queries:
            result[category] = queries
    return result


def get_query(query_id: str) -> QueryDefinition | None:
    """Find a query by its ID (e.g. 'analytics/avg_precipitation_by_country')."""
    parts = query_id.split("/", 1)
    if len(parts) != 2:
        return None
    category, name = parts
    yaml_path = QUERIES_DIR / category / f"{name}.yaml"
    if not yaml_path.exists():
        return None
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    return QueryDefinition(
        id=query_id,
        name=data.get("name", name),
        description=data.get("description", ""),
        category=category,
        tags=data.get("tags", []),
        sql=data.get("sql", "").strip(),
    )
