"""Model Context Protocol (MCP) server exposing the warehouse to AI assistants (Claude Desktop, Cursor, ...).

Run:  python -m querypilot.mcp_server          (stdio transport)
Every SQL call goes through the same AST guardrails and read-only executor as the API.
"""
from __future__ import annotations

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .executor import Executor
from .guardrails import validate
from .schema import CATALOG

mcp = _Server("querypilot")
_executor: Executor | None = None


def _ex() -> Executor:
    global _executor
    if _executor is None:
        _executor = Executor()
    return _executor


@mcp.tool()
def list_tables() -> list[dict]:
    """List the tables in the analytics warehouse with a one-line description."""
    return [{"table": n, "description": t.description} for n, t in CATALOG.items()]


@mcp.tool()
def describe_table(table: str) -> dict:
    """Return the columns of a table with their descriptions and join keys."""
    t = CATALOG.get(table)
    if not t:
        return {"error": f"unknown table {table!r}; choose one of {sorted(CATALOG)}"}
    return {"table": t.name, "description": t.description, "columns": t.columns, "joins": t.joins}


@mcp.tool()
def run_sql(sql: str) -> dict:
    """Run a read-only DuckDB SELECT query. Writes, file access and system tables are blocked."""
    g = validate(sql)
    if not g.ok:
        return {"error": f"blocked by guardrails: {g.reason}"}
    r = _ex().run(g.sql)
    if not r.ok:
        return {"error": r.error, "sql": g.sql}
    return {"sql": g.sql, "columns": r.columns, "rows": [list(map(str, row)) for row in r.rows[:100]], "row_count": len(r.rows)}


@mcp.tool()
def ask(question: str) -> dict:
    """Answer a plain-English analytics question with the full multi-agent pipeline (needs an LLM key)."""
    from .graph import QueryPilot
    from .llm import get_llm
    s = QueryPilot(get_llm(), executor=_ex()).ask(question)
    return {"status": s.get("status"), "answer": s.get("answer"), "sql": s.get("safe_sql"),
            "rows": [list(map(str, r)) for r in s.get("rows", [])[:50]]}


if __name__ == "__main__":
    mcp.run()
