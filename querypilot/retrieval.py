"""BM25 schema retrieval with join-path expansion.

Only the tables a question needs are sent to the LLM, which shrinks the prompt and
reduces the chance of the model joining irrelevant tables.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .schema import CATALOG

_STOP = {
    "the", "a", "an", "of", "in", "on", "for", "to", "by", "and", "or", "is", "are", "was", "were", "what",
    "which", "how", "many", "much", "show", "me", "list", "give", "with", "per", "each", "top", "all", "do",
    "does", "did", "that", "have", "has", "from", "at", "as", "be", "it", "their", "most", "least", "number",
    "total", "average", "count", "than", "more", "less", "between", "during", "this", "last", "who",
}

# A table is always included when the question names it directly (after singularization).
_NAME_HINTS = {
    "customer": "customers", "order": "orders", "product": "products", "category": "categories",
    "payment": "payments", "shipment": "shipments", "review": "reviews", "reviewed": "reviews", "carrier": "shipments",
}


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for t in toks:
        if t in _STOP:
            continue
        out.append(_singular(t))
    return out


def _singular(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


@dataclass
class RetrievalResult:
    tables: list[str]
    scores: dict[str, float]


class SchemaRetriever:
    def __init__(self, top_k: int = 3, rel_threshold: float = 0.25):
        self.names = list(CATALOG)
        self.top_k = top_k
        self.rel_threshold = rel_threshold
        self.bm25 = BM25Okapi([tokenize(CATALOG[n].search_text() + " " + n) for n in self.names])

    def retrieve(self, question: str) -> RetrievalResult:
        q = tokenize(question)
        raw = self.bm25.get_scores(q) if q else [0.0] * len(self.names)
        scores = dict(zip(self.names, map(float, raw)))
        ranked = sorted(scores, key=scores.get, reverse=True)
        best = scores[ranked[0]] or 1.0
        picked = [t for t in ranked[: self.top_k] if scores[t] >= self.rel_threshold * best and scores[t] > 0]
        for tok in q:
            name = _NAME_HINTS.get(tok)
            if name and name not in picked:
                picked.append(name)
        if not picked:
            picked = ranked[:2]
        return RetrievalResult(tables=self._connect(picked), scores=scores)

    @staticmethod
    def _path(a: str, b: str) -> list[str]:
        prev, dq = {a: None}, deque([a])
        while dq:
            cur = dq.popleft()
            if cur == b:
                break
            for nxt in CATALOG[cur].joins:
                if nxt not in prev:
                    prev[nxt] = cur
                    dq.append(nxt)
        path, node = [], b
        while node is not None:
            path.append(node)
            node = prev.get(node)
        return path[::-1]

    def _connect(self, tables: list[str]) -> list[str]:
        """Add the bridge tables needed so every selected table can be joined."""
        result = [tables[0]]
        for t in tables[1:]:
            best = min((self._path(s, t) for s in result), key=len)
            for node in best:
                if node not in result:
                    result.append(node)
        return result
