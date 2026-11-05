import statistics

from querypilot.guardrails import referenced_tables
from querypilot.retrieval import SchemaRetriever, tokenize


def test_tokenize_singularizes():
    assert tokenize("Categories and orders") == ["category", "order"]


def test_bridge_tables_are_added():
    tables = SchemaRetriever().retrieve("What is total revenue by product category?").tables
    assert {"order_items", "products", "categories"} <= set(tables)


def test_recall_on_benchmark(benchmark):
    r = SchemaRetriever()
    recalls = []
    for b in benchmark:
        gold = referenced_tables(b["sql"])
        got = set(r.retrieve(b["question"]).tables)
        recalls.append(len(gold & got) / len(gold))
    assert statistics.mean(recalls) >= 0.95
