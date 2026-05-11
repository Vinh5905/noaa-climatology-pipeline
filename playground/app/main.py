"""FastAPI entry point for NOAA SQL Playground."""

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .clickhouse_client import execute_query
from .query_loader import get_query, load_all_queries

app = FastAPI(title="NOAA SQL Playground")

_base = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_base / "static")), name="static")
templates = Jinja2Templates(directory=str(_base / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    queries = load_all_queries()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"queries": queries, "current_sql": "", "result": None},
    )


@app.get("/queries/{category}/{name}", response_class=HTMLResponse)
async def load_query(category: str, name: str, request: Request) -> HTMLResponse:
    query_id = f"{category}/{name}"
    query = get_query(query_id)
    if query is None:
        return HTMLResponse("<p>Query not found</p>", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="partials/editor_content.html",
        context={"query": query},
    )


@app.post("/execute", response_class=HTMLResponse)
async def run_query(request: Request, sql: str = Form(...)) -> HTMLResponse:
    try:
        result = await execute_query(sql)
        return templates.TemplateResponse(
            request=request,
            name="partials/result_table.html",
            context={"result": result, "error": None, "sql": sql},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/result_table.html",
            context={"result": None, "error": str(exc), "sql": sql},
        )
