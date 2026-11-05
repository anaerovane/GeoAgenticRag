"""Runtime configuration, read once from the environment.

Every external service is explicit; there is no silent fallback to a
different provider or to CPU. Set JEVRAG_MOCK=1 for offline runs (tests,
demos) where a deterministic stand-in replaces every model call.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    # Provider endpoints (OpenAI-compatible chat completions).
    planner_base_url: str = "http://127.0.0.1:8000/v1"
    planner_model: str = "planner"
    planner_api_key: str = "local"
    jev_base_url: str = "http://127.0.0.1:8100/v1"
    jev_model: str = "jev"
    jev_api_key: str = "local"
    answer_base_url: str = ""  # empty -> reuse planner endpoint
    answer_model: str = ""
    rerank_url: str = ""       # empty -> no cross-encoder rerank
    timeout_seconds: float = 60.0

    # Deterministic offline mode: no network, no GPU.
    mock: bool = False

    # Execution.
    max_nodes: int = 16
    max_depth: int = 5
    max_evidence: int = 24
    retrieval_k: int = 8
    max_workers: int = 4      # concurrent branch executions (like local)

    # Service.
    host: str = "127.0.0.1"
    port: int = 8080
    artifacts_dir: Path = Path(".runtime/artifacts")
    datasets_file: Path = Path(".runtime/data/datasets.json")

    # Optional extra settings from a JSON file (JEVRAG_CONFIG).
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        s.mock = _env_bool("JEVRAG_MOCK", False)
        s.planner_base_url = os.getenv("JEVRAG_PLANNER_URL", s.planner_base_url)
        s.planner_model = os.getenv("JEVRAG_PLANNER_MODEL", s.planner_model)
        s.planner_api_key = os.getenv("JEVRAG_PLANNER_KEY", s.planner_api_key)
        s.jev_base_url = os.getenv("JEVRAG_JEV_URL", s.jev_base_url)
        s.jev_model = os.getenv("JEVRAG_JEV_MODEL", s.jev_model)
        s.jev_api_key = os.getenv("JEVRAG_JEV_KEY", s.jev_api_key)
        s.answer_base_url = os.getenv("JEVRAG_ANSWER_URL", s.answer_base_url) or s.planner_base_url
        s.answer_model = os.getenv("JEVRAG_ANSWER_MODEL", s.answer_model) or s.planner_model
        s.rerank_url = os.getenv("JEVRAG_RERANK_URL", s.rerank_url)
        s.timeout_seconds = float(os.getenv("JEVRAG_TIMEOUT", s.timeout_seconds))
        s.max_workers = int(os.getenv("JEVRAG_MAX_WORKERS", s.max_workers))
        s.host = os.getenv("JEVRAG_HOST", s.host)
        s.port = int(os.getenv("JEVRAG_PORT", s.port))
        s.artifacts_dir = Path(os.getenv("JEVRAG_ARTIFACTS", s.artifacts_dir))
        s.datasets_file = Path(os.getenv("JEVRAG_DATASETS", s.datasets_file))
        config_path = os.getenv("JEVRAG_CONFIG")
        if config_path and Path(config_path).exists():
            s.extra = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return s
