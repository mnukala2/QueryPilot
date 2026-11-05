from querypilot.guardrails import validate


def test_benchmark_shape(benchmark):
    assert len(benchmark) == 100
    assert len({b["id"] for b in benchmark}) == 100
    assert {b["difficulty"] for b in benchmark} == {"easy", "medium", "hard"}


def test_every_gold_query_runs_and_returns_rows(executor, benchmark):
    for b in benchmark:
        r = executor.run(validate(b["sql"]).sql)
        assert r.ok, (b["id"], r.error)
        assert r.rows and r.rows != [(None,)], b["id"]


def test_executor_blocks_file_access_even_without_guardrails(executor):
    r = executor.run("SELECT * FROM read_csv('/etc/passwd')")
    assert not r.ok


def test_executor_is_read_only(executor):
    assert not executor.run("DELETE FROM orders").ok
