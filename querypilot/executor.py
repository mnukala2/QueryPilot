"""Read-only DuckDB executor with external access disabled and a query timeout."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from .config import settings


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    error: str | None = None
    ms: float = 0.0


class Executor:
    def __init__(self, db_path: str | Path | None = None, timeout_s: float | None = None):
        self.db_path = str(db_path or settings.db_path)
        self.timeout_s = timeout_s or settings.query_timeout_s
        if not Path(self.db_path).exists():
            from .data_gen import build
            build(self.db_path)
        self._lock = threading.Lock()
        self.con = duckdb.connect(
            self.db_path,
            read_only=True,
            config={"enable_external_access": False, "autoload_known_extensions": False, "autoinstall_known_extensions": False},
        )
        self.con.execute("SET lock_configuration = true")

    def run(self, sql: str) -> ExecResult:
        start = time.perf_counter()
        with self._lock:
            cur = self.con.cursor()
            timer = threading.Timer(self.timeout_s, cur.interrupt)
            timer.start()
            try:
                rel = cur.execute(sql)
                cols = [d[0] for d in rel.description or []]
                rows = rel.fetchall()
                return ExecResult(True, cols, rows, ms=(time.perf_counter() - start) * 1000)
            except duckdb.InterruptException:
                return ExecResult(False, error=f"query timed out after {self.timeout_s}s", ms=(time.perf_counter() - start) * 1000)
            except duckdb.Error as e:
                return ExecResult(False, error=str(e).splitlines()[0][:500], ms=(time.perf_counter() - start) * 1000)
            finally:
                timer.cancel()
                cur.close()
