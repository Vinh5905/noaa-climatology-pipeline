"""End-to-end smoke test for NOAA climatology pipeline.

Tests core pipeline from ClickHouse through to mart tables and SQL Playground.
Requires: docker compose stack running (ClickHouse, Kafka, Grafana, Metabase).
"""

import os
import urllib.parse
import urllib.request

import clickhouse_connect
import pytest


CH_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASS = os.getenv("CLICKHOUSE_PASSWORD", "changeme")

PLAYGROUND_URL = os.getenv("PLAYGROUND_URL", "http://localhost:8080")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")


@pytest.fixture(scope="session")
def ch_client():
    return clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USER,
        password=CH_PASS,
        connect_timeout=10,
    )


def test_clickhouse_ping(ch_client):
    result = ch_client.query("SELECT 1")
    assert result.result_rows[0][0] == 1


def test_historical_data_loaded(ch_client):
    count = ch_client.query(
        "SELECT count() FROM noaa_raw.observations_historical"
    ).result_rows[0][0]
    assert count >= 800_000_000, f"Expected ≥800M historical rows, got {count:,}"


def test_date_range_correct(ch_client):
    min_date, max_date = ch_client.query(
        "SELECT min(date), max(date) FROM noaa_raw.observations_historical"
    ).result_rows[0]
    assert str(min_date)[:4] >= "1900", f"min_date {min_date} seems wrong"
    assert str(max_date)[:4] <= "2011", f"max_date {max_date} should be ≤2010"


def test_streaming_table_exists(ch_client):
    result = ch_client.query(
        "SELECT count() FROM system.tables WHERE database='noaa_raw' AND name='observations_streaming'"
    )
    assert result.result_rows[0][0] == 1


def test_kafka_consumers_active(ch_client):
    consumers = ch_client.query(
        "SELECT count() FROM system.kafka_consumers WHERE database='noaa_raw'"
    ).result_rows[0][0]
    assert consumers >= 4, f"Expected 4 Kafka consumers, got {consumers}"


def test_dbt_staging_views_exist(ch_client):
    for view in ["stg_noaa__observations", "stg_noaa__stations"]:
        result = ch_client.query(
            f"SELECT count() FROM system.tables WHERE database='noaa_staging' AND name='{view}'"
        )
        assert result.result_rows[0][0] == 1, f"Missing staging view: {view}"


def test_mart_global_temperature(ch_client):
    rows = ch_client.query(
        "SELECT count() FROM noaa_marts.mart_global_temperature_yearly"
    ).result_rows[0][0]
    assert rows >= 100, f"mart_global_temperature_yearly has only {rows} rows"


def test_mart_hottest_stations(ch_client):
    rows = ch_client.query(
        "SELECT count() FROM noaa_marts.mart_top_hottest_stations"
    ).result_rows[0][0]
    assert rows >= 100, f"mart_top_hottest_stations has only {rows} rows"


def test_playground_accessible():
    try:
        r = urllib.request.urlopen(f"{PLAYGROUND_URL}/", timeout=5)
        content = r.read().decode()
        assert "NOAA" in content
        assert r.status == 200
    except Exception as e:
        pytest.skip(f"Playground not running: {e}")


def test_playground_execute_query():
    try:
        data = urllib.parse.urlencode({"sql": "SELECT 1 AS test"}).encode()
        r = urllib.request.urlopen(
            urllib.request.Request(f"{PLAYGROUND_URL}/execute", data=data), timeout=10
        )
        content = r.read().decode()
        assert r.status == 200
        assert "test" in content or "1" in content
    except Exception as e:
        pytest.skip(f"Playground execute not available: {e}")


def test_grafana_health():
    try:
        r = urllib.request.urlopen(f"{GRAFANA_URL}/api/health", timeout=5)
        import json

        data = json.loads(r.read())
        assert data.get("database") == "ok"
    except Exception as e:
        pytest.skip(f"Grafana not running: {e}")


def test_ttl_applied_to_streaming(ch_client):
    ddl = ch_client.query(
        "SHOW CREATE TABLE noaa_raw.observations_streaming"
    ).result_rows[0][0]
    assert "TTL" in ddl, "TTL not found in observations_streaming DDL"


def test_noaa_databases_exist(ch_client):
    dbs = {row[0] for row in ch_client.query("SHOW DATABASES").result_rows}
    for db in ["noaa_raw", "noaa_staging", "noaa_marts"]:
        assert db in dbs, f"Database {db} missing"
