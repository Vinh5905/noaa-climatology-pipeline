"""Pydantic models for playground."""

from pydantic import BaseModel


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list]
    query_time_sec: float
    rows_read: int
    bytes_read: int
    rows_returned: int

    @property
    def rows_per_sec(self) -> float:
        if self.query_time_sec > 0:
            return self.rows_read / self.query_time_sec
        return 0.0

    @property
    def bytes_per_sec(self) -> float:
        if self.query_time_sec > 0:
            return self.bytes_read / self.query_time_sec
        return 0.0


class QueryDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str
    tags: list[str] = []
    sql: str
