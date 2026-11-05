from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from querypilot import api
from querypilot.graph import QueryPilot


def client(executor, responses):
    api.app.dependency_overrides[api.get_executor] = lambda: executor
    api.app.dependency_overrides[api.get_pilot] = lambda: QueryPilot(FakeListChatModel(responses=responses), executor=executor)
    return TestClient(api.app)


def test_health_and_schema(executor):
    c = client(executor, [])
    assert c.get("/health").json() == {"status": "ok"}
    assert "orders" in c.get("/schema").json()


def test_ask(executor):
    c = client(executor, ["```sql\nSELECT channel, COUNT(*) AS n FROM orders GROUP BY channel ORDER BY n DESC\n```", "Web leads."])
    r = c.post("/ask", json={"question": "Orders by channel?"}).json()
    assert r["status"] == "ok" and r["columns"] == ["channel", "n"] and len(r["rows"]) == 3


def test_sql_endpoint_blocks_writes(executor):
    c = client(executor, [])
    assert c.post("/sql", json={"sql": "DROP TABLE orders"}).status_code == 400
    assert c.post("/sql", json={"sql": "SELECT COUNT(*) FROM orders"}).json()["rows"] == [[12000]]
