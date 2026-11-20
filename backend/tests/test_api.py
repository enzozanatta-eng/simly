from conftest import needs_solver
from fastapi.testclient import TestClient

from simly import api
from simly.llm import ToolCall

client = TestClient(api.app)


def test_health_and_templates():
    assert client.get("/api/health").status_code == 200
    t = client.get("/api/templates").json()
    assert set(t["templates"]) == {"cantilever_beam", "plate_with_hole"}
    assert "steel" in t["materials"]


def test_plan_endpoint(monkeypatch):
    class Fake:
        def call(self, system, history, tools):
            return ToolCall("a", "propose_plate_with_hole", {
                "length": 300, "width": 100, "thickness": 6, "hole_diameter": 20, "load": 5000,
            })

    monkeypatch.setattr(api, "make_client", lambda: Fake())
    r = client.post("/api/plan", json={"prompt": "placa com furo"})
    assert r.status_code == 200 and r.json()["spec"]["template"] == "plate_with_hole"


def test_plan_without_key_is_503(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SIMLY_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert client.post("/api/plan", json={"prompt": "x"}).status_code == 503


def test_simulate_rejects_bad_spec_with_field_messages():
    r = client.post("/api/simulate", json={"spec": {
        "template": "cantilever_beam", "length": 100, "width": 80, "height": 80, "load": 1}})
    assert r.status_code == 422
    assert "not a beam" in r.json()["detail"]["errors"][0]["message"]


@needs_solver
def test_simulate_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    r = client.post("/api/simulate", json={"spec": {
        "template": "cantilever_beam", "length": 800, "width": 40, "height": 40,
        "load": 200, "mesh": "coarse"}})
    assert r.status_code == 200
    body = r.json()
    assert body["comparisons"][0]["status"] == "PASS"
    assert len(body["display"]["indices"]) % 3 == 0


def test_ai_budget_per_ip(monkeypatch):
    class Fake:
        def call(self, system, history, tools):
            return ToolCall("a", "cannot_simulate", {"reason": "no"})

    monkeypatch.setattr(api, "make_client", lambda: Fake())
    monkeypatch.setattr(api, "AI_PER_HOUR", 2)
    api._ai_calls.clear()
    codes = [client.post("/api/plan", json={"prompt": "x"}).status_code for _ in range(3)]
    assert codes == [422, 422, 429]  # two declined requests, then the budget is spent
    api._ai_calls.clear()
