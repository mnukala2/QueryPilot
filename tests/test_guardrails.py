import pytest

from querypilot.guardrails import referenced_tables, validate


def test_all_redteam_attacks_blocked(redteam):
    assert len(redteam) == 60
    leaks = [a["sql"] for a in redteam if validate(a["sql"]).ok]
    assert leaks == []


def test_no_false_positives_on_gold_sql(benchmark):
    rejected = [(b["id"], validate(b["sql"]).reason) for b in benchmark if not validate(b["sql"]).ok]
    assert rejected == []


def test_limit_is_added_and_capped():
    assert validate("SELECT * FROM orders").sql.endswith("LIMIT 1000")
    assert validate("SELECT * FROM orders LIMIT 5").sql.endswith("LIMIT 5")
    assert validate("SELECT * FROM orders LIMIT 999999").sql.endswith("LIMIT 1000")


@pytest.mark.parametrize("sql", [
    "WITH t AS (SELECT * FROM orders) SELECT COUNT(*) FROM t",
    "SELECT state FROM customers UNION SELECT carrier FROM shipments",
    "SELECT c.name, COUNT(*) FROM products p JOIN categories c ON p.category_id = c.category_id GROUP BY 1",
])
def test_legitimate_queries_pass(sql):
    assert validate(sql).ok


def test_rejects_unknown_table_and_empty():
    assert not validate("SELECT * FROM salaries").ok
    assert not validate("   ").ok


def test_referenced_tables_ignores_ctes():
    assert referenced_tables("WITH x AS (SELECT * FROM orders) SELECT * FROM x JOIN customers USING (customer_id)") == {"orders", "customers"}
