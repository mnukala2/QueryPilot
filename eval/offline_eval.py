"""Deterministic evals that need no LLM or API key.

  * Guardrails: block rate on 60 red-team attacks, false-positive rate on 100 gold queries
  * Schema retrieval: table recall vs. tables referenced by gold SQL
  * Prompt size: generator prompt tokens with retrieved schema vs. full schema

Usage: python eval/offline_eval.py [--json results/offline.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from querypilot import prompts
from querypilot.guardrails import referenced_tables, validate
from querypilot.retrieval import SchemaRetriever
from querypilot.schema import full_schema, render

HERE = Path(__file__).resolve().parent


def count_tokens(text: str) -> tuple[int, str]:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text)), "tiktoken cl100k_base"
    except Exception:
        return round(len(text) / 4), "approx (chars/4)"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text().splitlines() if line.strip()]


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--top-k", type=int, default=3)
    args = ap.parse_args()

    bench, attacks = load("benchmark.jsonl"), load("redteam.jsonl")

    blocked = [a for a in attacks if not validate(a["sql"]).ok]
    leaks = [a["id"] for a in attacks if validate(a["sql"]).ok]
    false_pos = [b["id"] for b in bench if not validate(b["sql"]).ok]

    retriever = SchemaRetriever(top_k=args.top_k)
    full_tokens, method = count_tokens(prompts.GENERATOR_SYSTEM.format(schema=full_schema()))
    recalls, all_hit, sizes, misses = [], 0, [], []
    for b in bench:
        gold = referenced_tables(b["sql"])
        got = set(retriever.retrieve(b["question"]).tables)
        r = len(gold & got) / len(gold)
        recalls.append(r)
        all_hit += r == 1.0
        if r < 1.0:
            misses.append({"id": b["id"], "question": b["question"], "gold": sorted(gold), "retrieved": sorted(got)})
        sizes.append(count_tokens(prompts.GENERATOR_SYSTEM.format(schema=render(sorted(got))))[0])

    res = {
        "guardrails": {
            "attacks": len(attacks), "blocked": len(blocked), "block_rate_pct": round(100 * len(blocked) / len(attacks), 1),
            "leaks": leaks, "gold_queries": len(bench), "false_positives": len(false_pos),
            "false_positive_rate_pct": round(100 * len(false_pos) / len(bench), 1),
        },
        "retrieval": {
            "questions": len(bench), "top_k": args.top_k,
            "mean_table_recall_pct": round(100 * statistics.mean(recalls), 1),
            "questions_with_all_tables_pct": round(100 * all_hit / len(bench), 1),
            "misses": misses,
        },
        "prompt_tokens": {
            "method": method, "full_schema_prompt": full_tokens,
            "retrieved_schema_prompt_mean": round(statistics.mean(sizes), 1),
            "reduction_pct": round(100 * (1 - statistics.mean(sizes) / full_tokens), 1),
        },
    }
    g, r, t = res["guardrails"], res["retrieval"], res["prompt_tokens"]
    print(f"Guardrails : blocked {g['blocked']}/{g['attacks']} attacks ({g['block_rate_pct']}%), "
          f"false positives {g['false_positives']}/{g['gold_queries']} ({g['false_positive_rate_pct']}%)")
    print(f"Retrieval  : mean table recall {r['mean_table_recall_pct']}%, all gold tables retrieved for {r['questions_with_all_tables_pct']}% of questions")
    print(f"Prompt size: {t['full_schema_prompt']} -> {t['retrieved_schema_prompt_mean']} tokens "
          f"({t['reduction_pct']}% smaller, {t['method']})")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    main()
