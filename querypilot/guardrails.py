"""AST-level SQL guardrails built on sqlglot.

Every generated query must pass these checks before it reaches the database:
  1. exactly one statement, and it must be a read-only query (SELECT / WITH / UNION)
  2. no DDL, DML, or administrative nodes anywhere in the tree
  3. only tables from the approved catalog (CTE names allowed), no system schemas
  4. no file / network / system table functions
  5. an automatic row limit on the outermost query
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .schema import CATALOG

logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "duckdb"
MAX_ROWS = 1000

_FORBIDDEN_NODES = tuple(
    getattr(exp, n)
    for n in ("Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "TruncateTable", "Command",
              "Copy", "Attach", "Detach", "Pragma", "Set", "Use", "Transaction", "Commit", "Rollback",
              "Grant", "Revoke", "Install", "Load", "LoadData", "Export", "Into")
    if hasattr(exp, n)
)

_FORBIDDEN_FUNCS = {
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
    "read_json_objects", "read_ndjson", "read_text", "read_blob", "read_xlsx", "glob", "sqlite_scan",
    "sqlite_attach", "postgres_scan", "postgres_attach", "mysql_scan", "iceberg_scan", "delta_scan",
    "getenv", "current_setting", "pg_sleep", "sleep", "query", "query_table", "load_extension",
    "duckdb_settings", "duckdb_extensions", "duckdb_tables", "duckdb_columns", "duckdb_databases",
    "duckdb_secrets", "pragma_table_info", "pragma_database_list", "which_secret", "system",
    "range", "generate_series", "repeat_row",
}
_FORBIDDEN_SCHEMAS = {"information_schema", "pg_catalog", "system", "temp", "duckdb"}


@dataclass
class GuardResult:
    ok: bool
    sql: str | None = None
    reason: str | None = None


def _fail(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def validate(sql: str, allowed_tables: set[str] | None = None, max_rows: int = MAX_ROWS) -> GuardResult:
    allowed = {t.lower() for t in (allowed_tables or CATALOG)}
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return _fail("empty query")
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except ParseError as e:
        return _fail(f"parse error: {str(e).splitlines()[0]}")
    except Exception as e:  # tokenizer errors etc.
        return _fail(f"parse error: {type(e).__name__}")
    if len(statements) != 1:
        return _fail("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        return _fail(f"only read-only SELECT queries are allowed (got {type(tree).__name__})")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return _fail(f"forbidden operation: {type(node).__name__}")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        schema = (table.db or "").lower()
        catalog = (table.catalog or "").lower()
        if isinstance(table.this, exp.Func) or not name:
            fname = (table.this.sql_name() if isinstance(table.this, exp.Func) else "").lower()
            return _fail(f"table functions are not allowed ({fname or 'unknown'})")
        if schema in _FORBIDDEN_SCHEMAS or catalog in _FORBIDDEN_SCHEMAS or name.startswith(("duckdb_", "pragma_", "sqlite_")):
            return _fail(f"system tables are not allowed ({table.sql(dialect=DIALECT)})")
        if schema not in ("", "main") or catalog not in ("",):
            return _fail(f"cross-database access is not allowed ({table.sql(dialect=DIALECT)})")
        if name in cte_names:
            continue
        if name not in allowed:
            return _fail(f"table not in allow-list: {name}")

    for func in tree.find_all(exp.Func):
        fname = func.sql_name().lower() if not isinstance(func, exp.Anonymous) else str(func.this).lower()
        if fname in _FORBIDDEN_FUNCS:
            return _fail(f"function not allowed: {fname}")

    if tree.args.get("limit") is None:
        tree = tree.limit(max_rows, copy=True)
    else:
        lim = tree.args["limit"].expression
        if isinstance(lim, exp.Literal) and lim.is_int and int(lim.this) > max_rows:
            tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return GuardResult(ok=True, sql=tree.sql(dialect=DIALECT))


def referenced_tables(sql: str) -> set[str]:
    """Base tables referenced by a query (CTE aliases excluded). Used to score retrieval recall."""
    tree = sqlglot.parse_one(sql, read=DIALECT)
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in ctes}
