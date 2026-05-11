"""ClickHouse resource for Dagster."""

import os
from typing import Any

import clickhouse_connect
from dagster import ConfigurableResource


class ClickHouseResource(ConfigurableResource):
    host: str = "localhost"
    port: int = 8123
    username: str = "default"
    password: str = "changeme"
    database: str = "noaa_raw"

    def get_client(self) -> clickhouse_connect.driver.Client:
        return clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database=self.database,
            connect_timeout=30,
            send_receive_timeout=300,
        )

    def query(self, sql: str, **kwargs: Any) -> Any:
        with self.get_client() as client:
            return client.query(sql, **kwargs)

    def command(self, sql: str, **kwargs: Any) -> Any:
        with self.get_client() as client:
            return client.command(sql, **kwargs)

    def row_count(self, table: str, database: str | None = None) -> int:
        db = database or self.database
        result = self.get_client().query(f"SELECT count() FROM {db}.{table}")
        return result.result_rows[0][0]


def clickhouse_resource_from_env() -> ClickHouseResource:
    return ClickHouseResource(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "changeme"),
        database="noaa_raw",
    )
