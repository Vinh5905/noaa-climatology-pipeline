"""ClickHouse query execution for playground."""

import os
import time

import clickhouse_connect
from dotenv import load_dotenv

from .models import QueryResult

load_dotenv()


def _get_client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "playground_readonly"),
        password=os.getenv("PLAYGROUND_RO_PASSWORD", "playground_readonly"),
        connect_timeout=10,
        send_receive_timeout=int(os.getenv("PLAYGROUND_QUERY_TIMEOUT_SEC", "30")),
    )


async def execute_query(sql: str) -> QueryResult:
    client = _get_client()
    start = time.time()

    result = client.query(
        sql,
        settings={
            "max_execution_time": int(os.getenv("PLAYGROUND_QUERY_TIMEOUT_SEC", "30")),
            "max_result_rows": int(os.getenv("PLAYGROUND_MAX_ROWS", "10000")),
            "result_overflow_mode": "break",
        },
    )

    elapsed = time.time() - start
    summary = result.summary or {}

    return QueryResult(
        columns=list(result.column_names),
        rows=[list(row) for row in result.result_rows],
        query_time_sec=round(elapsed, 3),
        rows_read=int(summary.get("read_rows", 0)),
        bytes_read=int(summary.get("read_bytes", 0)),
        rows_returned=len(result.result_rows),
    )
