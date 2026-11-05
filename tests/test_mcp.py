import asyncio
import json

from querypilot import mcp_server


def call(executor, tool, args):
    mcp_server._executor = executor
    res = asyncio.run(mcp_server.mcp.call_tool(tool, args))
    content = res.content if hasattr(res, "content") else res[0]
    return json.loads(content[0].text)


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"list_tables", "describe_table", "run_sql", "ask"} <= names


def test_run_sql_and_guardrails(executor):
    assert call(executor, "run_sql", {"sql": "SELECT COUNT(*) FROM customers"})["rows"] == [["2000"]]
    assert "blocked" in call(executor, "run_sql", {"sql": "DROP TABLE customers"})["error"]


def test_describe_table(executor):
    assert "rating" in call(executor, "describe_table", {"table": "reviews"})["columns"]
    assert "error" in call(executor, "describe_table", {"table": "nope"})
