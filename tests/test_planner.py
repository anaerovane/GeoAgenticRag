"""Planner: one shot, one repair, then a hard failure."""
from __future__ import annotations

import json

import pytest

from jevrag.llm import MockLLM
from jevrag.planner import Planner, PlannerError, schema_summary


class Scripted:
    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, *args, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


_VALID = json.dumps({"root": {
    "id": "n1", "query": "q", "tool": "sql",
    "routes": [{"id": "r_ok", "when": "success"}],
}})
_INVALID = json.dumps({"root": {
    "id": "n1", "query": "q", "tool": "sql", "routes": [],
}})


class TestPlan:
    def test_mock_plan_is_valid(self, mock_model):
        tree = Planner(mock_model).plan("Which parks?", "city_poi(name, district)")
        assert tree.root.id == "n1"
        assert tree.root.tool == "sql"
        assert tree.size == 2

    def test_repair_retry_fed_back(self):
        model = Scripted([_INVALID, _VALID])
        tree = Planner(model, repairs=1).plan("q", "schema")
        assert tree.size == 1
        assert model.calls == 2

    def test_gives_up_after_repairs(self):
        model = Scripted([_INVALID, _INVALID, _INVALID])
        with pytest.raises(PlannerError, match="invalid after"):
            Planner(model, repairs=1).plan("q", "schema")

    def test_empty_question_rejected(self, mock_model):
        with pytest.raises(PlannerError, match="empty question"):
            Planner(mock_model).plan("   ", "schema")


class TestSchemaSummary:
    def test_compact_text(self):
        text = schema_summary([{
            "name": "city_poi",
            "columns": [{"name": "name", "type": "text"},
                        {"name": "rating", "type": "real"}],
            "sample": [{"name": "Cedar Park", "rating": 4.7}],
        }])
        assert "city_poi(name:text, rating:real)" in text
        assert "e.g." in text

    def test_empty(self):
        assert schema_summary([]) == "(no tables)"
