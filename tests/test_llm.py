"""JSON extraction tolerances for model replies."""
from __future__ import annotations

import pytest

from jevrag.llm import LLMError, extract_json


def test_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_bare_fence():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_embedded_in_prose():
    assert extract_json('Sure! Here you go: {"a": 1} hope that helps') == {"a": 1}


def test_no_json_raises():
    with pytest.raises(LLMError, match="no JSON"):
        extract_json("I cannot answer that.")


def test_mock_llm_answers_each_role(mock_model):
    import json

    plan = mock_model.chat("You are the planner ... Question: find parks", "go")
    assert "root" in json.loads(plan)

    jev = mock_model.chat("You are JEV ...", 'Decision context: {"result": '
                          '{"status": "success"}, "branch": {"routes": '
                          '[{"id": "r_ok", "when": "success"}]}}')
    assert json.loads(jev)["action"] == "complete"

    sql = mock_model.chat("Write one read-only SQL statement ... city_poi(a)", "go")
    assert json.loads(sql)["sql"].startswith("SELECT")

    answer = mock_model.chat("You are the answer engine ...",
                             "Evidence\n[e1] (sql, node n1) Cedar Park")
    assert "[e1]" in answer
