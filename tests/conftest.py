"""Shared fixtures: a tiny built dataset, mock models, and settings."""
from __future__ import annotations

import pytest

from jevrag.config import Settings
from jevrag.dataset import build_dataset
from jevrag.llm import MockLLM
from jevrag.tools import load_dataset


@pytest.fixture(scope="session")
def demo_dataset(tmp_path_factory):
    """One CSV -> sqlite + tables profile + source index, built once per session."""
    out = tmp_path_factory.mktemp("data")
    csv_path = out / "city_poi.csv"
    csv_path.write_text(
        "name,category,district,lat,lon,rating\n"
        "Cedar Park,park,West End,41.8895,-87.6412,4.7\n"
        "Willow Cafe,cafe,West End,41.8877,-87.6445,4.4\n"
        "Harbor Books,bookstore,Downtown,41.8789,-87.6359,4.2\n",
        encoding="utf-8",
    )
    result = build_dataset([csv_path], out, "demo")
    return load_dataset("demo", {"db": result["db"], "index": result["index"]})


@pytest.fixture()
def mock_model():
    return MockLLM()


@pytest.fixture()
def mock_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVRAG_MOCK", "1")
    monkeypatch.setenv("JEVRAG_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("JEVRAG_DATASETS", str(tmp_path / "missing.json"))
    return Settings.load()
