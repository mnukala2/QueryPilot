from langchain_core.language_models.fake_chat_models import FakeListChatModel

from querypilot.graph import QueryPilot, extract_sql


def pilot(executor, responses, **kw):
    return QueryPilot(FakeListChatModel(responses=responses), executor=executor, **kw)


def test_extract_sql():
    assert extract_sql("Here:\n```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("SELECT 2") == "SELECT 2"


def test_happy_path(executor):
    s = pilot(executor, ["```sql\nSELECT COUNT(*) FROM orders\n```", "12,000 orders."]).ask("How many orders?")
    assert s["status"] == "ok" and s["rows"] == [(12000,)] and s["attempts"] == 1 and s["first_pass_ok"]


def test_repairs_execution_error(executor):
    s = pilot(executor, ["```sql\nSELECT COUNT(order_idd) FROM orders\n```",
                         "```sql\nSELECT COUNT(order_id) FROM orders\n```", "ok"]).ask("How many orders?")
    assert s["status"] == "ok" and s["attempts"] == 2 and not s["first_pass_ok"]
    assert any(t.get("node") == "execute" and not t["ok"] for t in s["trace"])


def test_repairs_guardrail_rejection(executor):
    s = pilot(executor, ["```sql\nDELETE FROM orders\n```", "```sql\nSELECT COUNT(*) FROM orders\n```", "ok"]).ask("count orders")
    assert s["status"] == "ok" and s["attempts"] == 2


def test_gives_up_after_max_repairs(executor):
    bad = "```sql\nSELECT nope FROM orders\n```"
    s = pilot(executor, [bad] * 5, max_repairs=2, answer=False).ask("?")
    assert s["status"] == "failed" and s["attempts"] == 3


def test_cannot_answer(executor):
    s = pilot(executor, ["CANNOT_ANSWER"]).ask("What is the CEO's salary?")
    assert s["status"] == "cannot_answer"


def test_oracle_llm_scores_100_percent(executor, benchmark):
    """Sanity check for the eval harness: an LLM that returns gold SQL must score 100%."""
    from run_eval import results_match
    for b in benchmark[:25]:
        s = pilot(executor, [f"```sql\n{b['sql']}\n```"], answer=False).ask(b["question"])
        assert results_match(s["rows"], executor.run(b["sql"]).rows), b["id"]
