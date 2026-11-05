"""HTTP API: synchronous query, SSE stream, artifacts, dataset listing.

Contract (schema_version 1.0):

- GET  /health
- GET  /api/v1/datasets
- POST /api/v1/query            {question, dataset_id?} -> full result
- POST /api/v1/query/stream     same body -> text/event-stream
- GET  /api/v1/queries/{id}/artifacts/{name}
- GET  /api/v1/history

Every accepted run writes six artifacts: request.json, events.jsonl,
query_tree.json, evidence.json, result.json, status.json.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .evidence import EvidenceTree  # noqa: F401  (re-export for tests)
from .llm import make_llm
from .orchestrator import Orchestrator, RunError
from .planner import Planner
from .jev import JEV
from .tools import Dataset, load_dataset

ARTIFACT_FILES = ("request.json", "events.jsonl", "query_tree.json",
                  "evidence.json", "result.json", "status.json")
_QUERY_ID = re.compile(r"^[0-9a-f]{32}$")
SCHEMA_VERSION = "1.0"


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    dataset_id: str | None = None

    model_config = {"extra": "forbid"}


class Catalog:
    """Loaded datasets + per-dataset orchestrator factories."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.datasets: dict[str, Dataset] = {}
        self.default_id: str | None = None
        self._load()

    def _load(self) -> None:
        path = self.settings.datasets_file
        if not path.exists():
            return
        spec = json.loads(path.read_text(encoding="utf-8"))
        self.default_id = spec.get("default")
        for dataset_id, entry in (spec.get("datasets") or {}).items():
            self.datasets[dataset_id] = load_dataset(dataset_id, entry)

    def get(self, dataset_id: str | None) -> Dataset:
        wanted = dataset_id or self.default_id
        if wanted is None:
            raise HTTPException(status_code=400, detail="no dataset configured")
        if wanted not in self.datasets:
            raise HTTPException(status_code=404, detail=f"unknown dataset {wanted!r}")
        return self.datasets[wanted]


def build_orchestrator(settings: Settings, dataset: Dataset) -> Orchestrator:
    return Orchestrator(
        planner=Planner(make_llm(settings, "planner"),
                        max_nodes=settings.max_nodes, max_depth=settings.max_depth),
        jev=JEV(make_llm(settings, "jev"), max_nodes=settings.max_nodes),
        answer_model=make_llm(settings, "answer"),
        dataset=dataset,
        max_evidence=settings.max_evidence,
        max_workers=settings.max_workers,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(title="GeoAgenticRag", version=SCHEMA_VERSION,
                  description="JEV-driven Geographic Tree-RAG")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    catalog = Catalog(settings)
    app.state.settings = settings
    app.state.catalog = catalog
    history: list[dict[str, Any]] = []
    history_lock = threading.Lock()

    def _run(question: str, dataset: Dataset, emit, query_id: str,
             artifacts_dir: Path) -> dict[str, Any]:
        events: list[tuple[str, dict[str, Any]]] = []

        def sink(event: str, data: dict[str, Any]) -> None:
            events.append((event, data))
            emit(event, data)

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "request.json").write_text(json.dumps(
            {"query_id": query_id, "question": question,
             "dataset_id": dataset.id, "schema_version": SCHEMA_VERSION},
            ensure_ascii=False, indent=2), encoding="utf-8")
        status_path = artifacts_dir / "status.json"
        status_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
        try:
            orch = build_orchestrator(settings, dataset)
            result = orch.run(question, sink)
        except RunError as exc:
            status_path.write_text(json.dumps(
                {"state": "failed", "error": str(exc)}, ensure_ascii=False),
                encoding="utf-8")
            (artifacts_dir / "events.jsonl").write_text(
                "".join(json.dumps({"event": e, "data": d}, ensure_ascii=False) + "\n"
                        for e, d in events), encoding="utf-8")
            raise
        (artifacts_dir / "query_tree.json").write_text(
            json.dumps(result["tree"], ensure_ascii=False, indent=2),
            encoding="utf-8")
        (artifacts_dir / "evidence.json").write_text(
            json.dumps(result["evidence"], ensure_ascii=False, indent=2),
            encoding="utf-8")
        (artifacts_dir / "result.json").write_text(
            json.dumps({k: result[k] for k in
                        ("query_id", "question", "answer", "nodes",
                         "evidence_count", "elapsed_ms", "models")},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (artifacts_dir / "events.jsonl").write_text(
            "".join(json.dumps({"event": e, "data": d}, ensure_ascii=False) + "\n"
                    for e, d in events), encoding="utf-8")
        status_path.write_text(json.dumps({"state": "succeeded"}), encoding="utf-8")
        return result

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "mock": settings.mock,
            "datasets": sorted(catalog.datasets),
        }

    @app.get("/api/v1/datasets")
    def datasets() -> dict[str, Any]:
        return {"default": catalog.default_id,
                "datasets": sorted(catalog.datasets)}

    @app.post("/api/v1/query")
    def query(body: QueryRequest) -> dict[str, Any]:
        dataset = catalog.get(body.dataset_id)
        query_id = _new_query_id()
        artifacts_dir = settings.artifacts_dir / query_id

        def sink(event: str, data: dict[str, Any]) -> None:
            pass

        try:
            result = _run(body.question, dataset, sink, query_id, artifacts_dir)
        except RunError as exc:
            raise HTTPException(status_code=500, detail={
                "query_id": query_id, "state": "failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }) from exc
        with history_lock:
            history.insert(0, {"query_id": query_id,
                               "question": body.question,
                               "answer": result["answer"],
                               "elapsed_ms": result["elapsed_ms"],
                               "created_at": time.time()})
            del history[100:]
        return {
            "schema_version": SCHEMA_VERSION,
            "query_id": query_id,
            "dataset_id": dataset.id,
            "state": "succeeded",
            "answer": result["answer"],
            "nodes": result["nodes"],
            "evidence_count": result["evidence_count"],
            "elapsed_ms": result["elapsed_ms"],
            "models": result["models"],
            "artifacts": {name: f"/api/v1/queries/{query_id}/artifacts/{name}"
                          for name in ARTIFACT_FILES},
        }

    @app.post("/api/v1/query/stream")
    def query_stream(body: QueryRequest) -> StreamingResponse:
        dataset = catalog.get(body.dataset_id)
        query_id = _new_query_id()
        artifacts_dir = settings.artifacts_dir / query_id
        queue: list[str] = []
        done = threading.Event()

        def emit(event: str, data: dict[str, Any]) -> None:
            queue.append(f"event: {event}\ndata: "
                         f"{json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n")

        def worker() -> None:
            try:
                _run(body.question, dataset, emit, query_id, artifacts_dir)
            except RunError as exc:
                emit("error", {"message": str(exc)})
            except Exception as exc:  # noqa: BLE001 — surface anything to the client
                emit("error", {"message": f"{type(exc).__name__}: {exc}"})
            finally:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def stream():
            cursor = 0
            while not done.is_set() or cursor < len(queue):
                if cursor < len(queue):
                    chunk = "".join(queue[cursor:])
                    cursor = len(queue)
                    yield chunk
                else:
                    time.sleep(0.02)
            yield ""

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/v1/queries/{query_id}/artifacts/{name}")
    def artifact(query_id: str, name: str) -> FileResponse:
        if not _QUERY_ID.match(query_id):
            raise HTTPException(status_code=400, detail="bad query id")
        if name not in ARTIFACT_FILES:
            raise HTTPException(status_code=404, detail="unknown artifact")
        path = settings.artifacts_dir / query_id / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(path)

    @app.get("/api/v1/history")
    def get_history(limit: int = 50) -> dict[str, Any]:
        with history_lock:
            return {"queries": history[:max(1, min(limit, 100))]}

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True),
                  name="frontend")

    return app


def _new_query_id() -> str:
    import uuid
    return uuid.uuid4().hex
