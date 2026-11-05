"""End-to-end LLM benchmark: execution accuracy, self-repair recovery, latency and token usage.

Requires an LLM provider key (see .env.example). Example:
    QP_LLM_PROVIDER=openai OPENAI_API_KEY=sk-... python eval/run_eval.py --json results/llm.json
    python eval/run_eval.py --limit 20 --no-retrieval      # ablation: full schema in every prompt
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from querypilot.executor import Executor
from querypilot.graph import QueryPilot
from querypilot.llm import get_llm

HERE = Path(__file__).resolve().parent


def _norm(v):
    if isinstance(v, (float, Decimal)):
        return round(float(v), 2)
    return v


def _rows(rows) -> list[tuple]:
    return sorted((tuple(_norm(v) for v in r) for r in rows), key=repr)


def results_match(pred_rows, gold_rows) -> bool:
    """Execution match: same multiset of rows (order-insensitive, values rounded to 2dp).
    Also accepts a prediction whose columns are a superset of gold's, e.g. an extra label column."""
    p, g = _rows(pred_rows), _rows(gold_rows)
    if p == g:
        return True
    if not p or not g or len(p) != len(g):
        return False
    gcols, pcols = len(g[0]), len(p[0])
    if pcols < gcols:
        return False
    # try to find gold columns inside prediction columns
    pt = list(zip(*p)) if p else []
    gt = list(zip(*g))
    used, mapping = set(), []
    for gc in gt:
        hit = next((i for i, pc in enumerate(pt) if i not in used and sorted(map(repr, pc)) == sorted(map(repr, gc))), None)
        if hit is None:
            return False
        used.add(hit)
        mapping.append(hit)
    return _rows([tuple(r[i] for i in mapping) for r in pred_rows]) == g


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-retrieval", action="store_true", help="ablation: send the full schema every time")
    ap.add_argument("--max-repairs", type=int, default=None)
    args = ap.parse_args()

    bench = [json.loads(line) for line in (HERE / "benchmark.jsonl").read_text().splitlines() if line.strip()]
    if args.limit:
        bench = bench[: args.limit]
    ex = Executor()
    qp = QueryPilot(get_llm(args.provider, args.model), executor=ex, answer=False,
                    use_retrieval=not args.no_retrieval, max_repairs=args.max_repairs)

    rows = []
    for b in bench:
        gold = ex.run(b["sql"])
        try:
            s = qp.ask(b["question"])
            ok = s.get("status") == "ok" and results_match(s.get("rows", []), gold.rows)
            first_pass_sql_ok = bool(s.get("first_pass_ok"))
            first_pass_correct = first_pass_sql_ok and s.get("attempts") == 1 and ok
        except Exception as e:  # provider errors, rate limits
            s, ok, first_pass_correct = {"status": "error", "error": str(e)}, False, False
        rows.append({
            "id": b["id"], "difficulty": b["difficulty"], "correct": ok, "first_pass_correct": first_pass_correct,
            "attempts": s.get("attempts", 0), "status": s.get("status"), "sql": s.get("safe_sql") or s.get("sql"),
            "latency_ms": s.get("latency_ms"), "prompt_tokens": s.get("prompt_tokens", 0),
            "completion_tokens": s.get("completion_tokens", 0),
        })
        print(f"{b['id']} {'PASS' if ok else 'FAIL'} attempts={s.get('attempts', 0)} {s.get('latency_ms', 0):.0f}ms")

    n = len(rows)
    first_fail = [r for r in rows if not r["first_pass_correct"]]
    # A query "needed repair" when its first SQL failed guardrails or execution; recovered = repaired and correct.
    needed_repair = [r for r in rows if r["attempts"] > 1]
    recovered = [r for r in needed_repair if r["correct"]]
    lat = sorted(r["latency_ms"] for r in rows if r["latency_ms"])
    summary = {
        "questions": n,
        "execution_accuracy_pct": pct(sum(r["correct"] for r in rows), n),
        "first_pass_accuracy_pct": pct(sum(r["first_pass_correct"] for r in rows), n),
        "by_difficulty": {d: pct(sum(r["correct"] for r in rows if r["difficulty"] == d), sum(r["difficulty"] == d for r in rows))
                          for d in ("easy", "medium", "hard")},
        "queries_needing_repair": len(needed_repair),
        "repair_recovery_pct": pct(len(recovered), len(needed_repair)),
        "first_pass_failures": len(first_fail),
        "latency_p50_ms": round(statistics.median(lat), 1) if lat else None,
        "latency_p95_ms": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None,
        "avg_prompt_tokens": round(statistics.mean(r["prompt_tokens"] for r in rows), 1) if rows else 0,
        "retrieval": not args.no_retrieval,
    }
    print(json.dumps(summary, indent=2))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))


if __name__ == "__main__":
    main()
