"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    db_path: str = os.getenv("QP_DB_PATH", str(ROOT / "data" / "warehouse.duckdb"))
    provider: str = os.getenv("QP_LLM_PROVIDER", "openai")  # openai | anthropic | bedrock | fake
    model: str = os.getenv("QP_LLM_MODEL", "")
    temperature: float = float(os.getenv("QP_TEMPERATURE", "0"))
    max_repairs: int = int(os.getenv("QP_MAX_REPAIRS", "3"))
    top_k_tables: int = int(os.getenv("QP_TOP_K_TABLES", "3"))
    query_timeout_s: float = float(os.getenv("QP_QUERY_TIMEOUT_S", "10"))
    max_rows: int = int(os.getenv("QP_MAX_ROWS", "1000"))


settings = Settings()
