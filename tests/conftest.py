import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))


@pytest.fixture(scope="session")
def executor(tmp_path_factory):
    from querypilot.data_gen import build
    from querypilot.executor import Executor
    db = tmp_path_factory.mktemp("db") / "warehouse.duckdb"
    build(db)
    return Executor(db)


def _load(name):
    return [json.loads(line) for line in (ROOT / "eval" / name).read_text().splitlines() if line.strip()]


@pytest.fixture(scope="session")
def benchmark():
    return _load("benchmark.jsonl")


@pytest.fixture(scope="session")
def redteam():
    return _load("redteam.jsonl")
