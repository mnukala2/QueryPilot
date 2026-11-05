"""FastAPI service.

    uvicorn querypilot.api:app --reload
    curl -X POST localhost:8000/ask -H 'content-type: application/json' -d '{"question": "Revenue by category?"}'
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .executor import Executor
from .graph import QueryPilot
from .guardrails import validate
from .llm import get_llm
from .schema import CATALOG

app = FastAPI(title="QueryPilot", version="0.1.0", description="Multi-agent text-to-SQL analytics copilot")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class AskResponse(BaseModel):
    status: str
    answer: str | None = None
    sql: str | None = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    tables: list[str] = []
    attempts: int = 0
    latency_ms: float | None = None
    trace: list[dict] = []


class SQLRequest(BaseModel):
    sql: str = Field(..., min_length=6, max_length=5000)


@lru_cache
def get_executor() -> Executor:
    return Executor()


@lru_cache
def get_pilot() -> QueryPilot:
    return QueryPilot(get_llm(), executor=get_executor())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> dict:
    return {name: {"description": t.description, "columns": t.columns} for name, t in CATALOG.items()}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, pilot: QueryPilot = Depends(get_pilot)) -> AskResponse:
    s = pilot.ask(req.question)
    return AskResponse(
        status=s.get("status", "failed"), answer=s.get("answer"), sql=s.get("safe_sql") or s.get("sql"),
        columns=s.get("columns", []), rows=[list(r) for r in s.get("rows", [])[:200]], tables=s.get("tables", []),
        attempts=s.get("attempts", 0), latency_ms=s.get("latency_ms"), trace=s.get("trace", []),
    )


@app.post("/sql")
def run_sql(req: SQLRequest, ex: Executor = Depends(get_executor)) -> dict:
    g = validate(req.sql)
    if not g.ok:
        raise HTTPException(status_code=400, detail=f"blocked by guardrails: {g.reason}")
    r = ex.run(g.sql)
    if not r.ok:
        raise HTTPException(status_code=400, detail=r.error)
    return {"sql": g.sql, "columns": r.columns, "rows": [list(x) for x in r.rows[:200]], "ms": round(r.ms, 2)}
