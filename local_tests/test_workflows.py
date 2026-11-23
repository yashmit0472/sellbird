import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from sellbird.local.__main__ import reject_external_socket
from sellbird.local.app import create_app
from sellbird.local.engine import ENDPOINT, MODELS, Workflow, finalize_score, matched_exclusion, validate_citations
from sellbird.local.store import Store
from sellbird.dashboard_auth import TokenStore


def test_offline_workspace_and_product_scoping(tmp_path, monkeypatch):
    monkeypatch.setenv("SELLBIRD_LOCAL_OFFLINE", "1")
    # Prevent the worker from making calls in the API unit test.
    async def idle(_self):
        await asyncio.sleep(3600)
    monkeypatch.setattr(Workflow, "work", idle)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/workspace").status_code == 401
        token = TokenStore(tmp_path / "dashboard-token").get()
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.post("/api/capture", json={
            "name": "Example", "url": "https://example.org", "permitted": True,
        }).status_code == 409
        seed = client.post("/api/demo", json={}).json()
        workspace = client.get("/api/workspace").json()
        assert len(workspace["products"]) == 2
        prospect = workspace["prospects"][0]["id"]
        for product in workspace["products"]:
            payload = {"product_id": product["id"], "prospect_id": prospect, "model": MODELS[0], "reply": seed["reply"]}
            invalid = client.post("/api/jobs", json={**payload, "model": "qwen3:cloud"})
            assert invalid.status_code == 422
            job = client.post("/api/jobs", json=payload)
            assert job.status_code == 202
            selected = client.get(f"/api/jobs/{job.json()['id']}").json()
            assert selected["input"]["product"]["name"] == product["name"]
            assert len(selected["input"]["steps"]) == 8


def test_local_connection_failure_preserves_job(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    product = store.write("INSERT INTO products(company, name, brief) VALUES ('C', 'P', 'Brief')")
    inputs = {"product": {"name": "P"}, "steps": ["profile", "icp"]}
    job = store.write("INSERT INTO jobs(product_id, model, input) VALUES (?, ?, ?)", (product, MODELS[0], json.dumps(inputs)))
    seen = []
    actual = httpx.AsyncClient

    def fake_client(**kwargs):
        assert not kwargs["trust_env"]
        assert not kwargs["follow_redirects"]

        def fail(request):
            seen.append(str(request.url))
            raise httpx.ConnectError("Offline", request=request)
        return actual(transport=httpx.MockTransport(fail), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    claimed = store.claim()
    asyncio.run(Workflow(store, None).run(claimed))
    assert seen == [f"{ENDPOINT}/api/chat"]
    assert store.rows("SELECT status FROM jobs WHERE id = ?", (job,)) == [{"status": "waiting"}]
    assert store.rows("SELECT status, endpoint FROM inference") == [{"status": "error", "endpoint": ENDPOINT}]
    assert store.claim() is None


def test_quote_must_match_its_source():
    evidence = [{"evidence_id": 2, "text": "We are hiring a dispatcher. We use spreadsheets."}]
    validate_citations({"facts": [{"evidence_id": 2, "quote": "hiring a dispatcher"}]}, evidence)
    with pytest.raises(ValueError):
        validate_citations({"facts": [{"evidence_id": 3, "quote": "hiring a dispatcher"}]}, evidence)

def test_offline_socket_guard_allows_loopback():
    reject_external_socket("socket.getaddrinfo", (b"127.0.0.1", 11435))
    reject_external_socket("socket.connect", (None, ("::1", 11435, 0, 0)))
    with pytest.raises(PermissionError):
        reject_external_socket("socket.getaddrinfo", ("example.com", 443))
    with pytest.raises(PermissionError):
        reject_external_socket("socket.connect", (None, ("192.0.2.1", 443)))


def test_static_extraction_preserves_only_readable_evidence():
    from sellbird.local.research import extract

    result = extract("https://example.com/", b"""
        <html><body><nav>Ignore navigation</nav>
        <main><p>Our repair business is hiring three field technicians this month.</p>
        <script>fake evidence</script></main></body></html>
        """, "utf-8")
    assert result == "Our repair business is hiring three field technicians this month."


def test_running_workspace_excludes_a_second_worker(tmp_path, monkeypatch):
    async def idle(_self):
        await asyncio.sleep(3600)

    monkeypatch.setattr(Workflow, "work", idle)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8765"):
        with pytest.raises(RuntimeError, match="already open"), TestClient(create_app(tmp_path)):
            pytest.fail("A second worker entered the same workspace")

def test_score_caps_intent_to_the_observed_signal():
    score = {"fit": 30, "intent": 25, "evidence_quality": 20, "rationale": "One source."}
    result = finalize_score(score, "weak")
    assert result["intent"] == 6
    assert result["model_intent"] == 25
    assert result["total"] == 56
    assert finalize_score(score, "insufficient_evidence")["total"] == 50
    assert finalize_score(score, "strong")["total"] == 75

def test_unverified_daemon_keeps_job_without_requesting_inference(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite3")
    store.initialize()
    product = store.write("INSERT INTO products(company, name, brief) VALUES ('C', 'P', 'Brief')")
    inputs = {"product": {"name": "P"}, "steps": ["profile", "icp"]}
    store.write("INSERT INTO jobs(product_id, model, input) VALUES (?, ?, ?)", (product, MODELS[0], json.dumps(inputs)))

    async def unexpected_request(*args):
        pytest.fail("Unverified local daemon received a model request")

    workflow = Workflow(store, None, inference_verified=False)
    monkeypatch.setattr(workflow, "complete", unexpected_request)
    asyncio.run(workflow.run(store.claim()))
    job = store.rows("SELECT status, error FROM jobs")[0]
    assert job["status"] == "waiting"
    assert "could not verify" in job["error"]
    assert store.rows("SELECT * FROM inference") == []

def test_product_exclusions_use_exact_persisted_evidence():
    evidence = [{"id": 4, "body": "The business does NOT currently sell maintenance plans."}]
    matched = matched_exclusion({"exclusion_phrases": "does not currently sell maintenance plans"}, evidence)
    assert matched and "source #4" in matched
    assert matched_exclusion({"exclusion_phrases": "uses a spreadsheet"}, evidence) is None
    assert matched_exclusion({}, evidence) is None
    score = finalize_score({"fit": 35, "intent": 25, "evidence_quality": 20}, "moderate", matched)
    assert (score["fit"], score["intent"], score["total"]) == (0, 0, 20)
    assert score["model_fit"] == 35
