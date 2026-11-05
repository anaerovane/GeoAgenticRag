"""HTTP API: request/response contract, SSE stream, artifacts, history."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from jevrag.dataset import build_dataset
from jevrag.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    out = tmp_path / "data"
    csv_path = tmp_path / "city_poi.csv"
    csv_path.write_text(
        "name,category,district\nCedar Park,park,West End\nWillow Cafe,cafe,West End\n",
        encoding="utf-8",
    )
    result = build_dataset([csv_path], out, "demo")
    datasets = out / "datasets.json"
    datasets.write_text(json.dumps({
        "default": "demo",
        "datasets": {"demo": {"db": result["db"], "index": result["index"]}},
    }), encoding="utf-8")

    monkeypatch.setenv("JEVRAG_MOCK", "1")
    monkeypatch.setenv("JEVRAG_DATASETS", str(datasets))
    monkeypatch.setenv("JEVRAG_ARTIFACTS", str(tmp_path / "artifacts"))
    from jevrag.config import Settings
    with TestClient(create_app(Settings.load())) as c:
        yield c


class TestHealth:
    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ready"
        assert body["mock"] is True
        assert body["datasets"] == ["demo"]

    def test_datasets(self, client):
        body = client.get("/api/v1/datasets").json()
        assert body["default"] == "demo"
        assert body["datasets"] == ["demo"]


class TestQuery:
    def test_sync_query(self, client):
        body = client.post("/api/v1/query",
                           json={"question": "Which parks are in the West End?"}
                           ).json()
        assert body["state"] == "succeeded"
        assert body["dataset_id"] == "demo"
        assert body["answer"]
        assert body["evidence_count"] > 0
        assert body["models"]["jev"] == "mock"
        assert set(body["artifacts"]) == {
            "request.json", "events.jsonl", "query_tree.json",
            "evidence.json", "result.json", "status.json"}

    def test_unknown_dataset_404(self, client):
        r = client.post("/api/v1/query",
                        json={"question": "q", "dataset_id": "nope"})
        assert r.status_code == 404

    def test_empty_question_422(self, client):
        assert client.post("/api/v1/query", json={"question": ""}).status_code == 422

    def test_extra_fields_422(self, client):
        r = client.post("/api/v1/query", json={"question": "q", "hack": 1})
        assert r.status_code == 422

    def test_streaming_query(self, client):
        with client.stream("POST", "/api/v1/query/stream",
                           json={"question": "Which parks are in the West End?"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            raw = "".join(r.iter_text())
        assert "event: query_started" in raw
        assert "event: jev_decision" in raw
        assert "event: answer" in raw
        assert "event: done" in raw
        # Every frame wraps {event, data}.
        for chunk in raw.split("\n\n"):
            if not chunk.strip():
                continue
            data_line = next((ln for ln in chunk.splitlines()
                              if ln.startswith("data: ")), None)
            assert data_line is not None
            frame = json.loads(data_line[len("data: "):])
            assert "event" in frame and "data" in frame


class TestArtifactsAndHistory:
    def test_artifacts_written_and_served(self, client):
        body = client.post("/api/v1/query",
                           json={"question": "Which parks are in the West End?"}).json()
        query_id = body["query_id"]
        tree = client.get(body["artifacts"]["query_tree.json"]).json()
        assert tree["id"] == "n1"
        status = client.get(body["artifacts"]["status.json"]).json()
        assert status["state"] == "succeeded"
        events = client.get(body["artifacts"]["events.jsonl"]).text.strip().splitlines()
        assert events and json.loads(events[0])["event"] == "query_started"

    def test_bad_artifact_requests(self, client):
        r = client.get("/api/v1/queries/notahexid/artifacts/result.json")
        assert r.status_code == 400
        r = client.get("/api/v1/queries/" + "0" * 32 + "/artifacts/secret.env")
        assert r.status_code == 404

    def test_history_records_runs(self, client):
        client.post("/api/v1/query",
                    json={"question": "Which parks are in the West End?"})
        history = client.get("/api/v1/history").json()
        assert history["queries"][0]["question"] == "Which parks are in the West End?"
        assert history["queries"][0]["answer"]
