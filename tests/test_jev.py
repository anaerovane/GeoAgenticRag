"""JEV decision contract: validation is code, not prose."""
from __future__ import annotations

import pytest

from jevrag.jev import JEV, JEVError, build_payload, validate_decision
from jevrag.tree import BranchResult, Node, QueryTree, Route, Status


def _node():
    return Node(
        id="n1", query="find parks", tool="sql",
        routes=[Route("r_ok", "success"), Route("r_empty", "empty")],
    )


def _result(status="success", rows=None):
    return BranchResult(status=status, summary="2 rows from SQL",
                        rows=rows or [{"name": "Cedar Park"}],
                        evidence=[{"source": "sql", "text": "Cedar Park"}],
                        error="" if status != "error" else "boom")


class TestValidateDecision:
    def test_complete_ok(self):
        d = validate_decision(
            {"action": "complete", "route_id": "r_ok", "reason": "usable"},
            _node(), max_nodes=8)
        assert d.action == "complete"
        assert d.follow_up is None

    def test_add_child_requires_follow_up(self):
        with pytest.raises(JEVError, match="follow_up"):
            validate_decision({"action": "add_child", "route_id": "r_ok",
                               "reason": "x"}, _node(), max_nodes=8)

    def test_add_child_parses_follow_up(self):
        d = validate_decision(
            {"action": "add_child", "route_id": "r_ok", "reason": "x",
             "follow_up": {"query": "then count them", "tool": "sql"}},
            _node(), max_nodes=8)
        assert d.follow_up == {"query": "then count them", "tool": "sql"}

    def test_rejects_unknown_action(self):
        with pytest.raises(JEVError, match="unknown action"):
            validate_decision({"action": "retry", "route_id": "r_ok",
                               "reason": "x"}, _node(), max_nodes=8)

    def test_rejects_invented_route(self):
        with pytest.raises(JEVError, match="not declared"):
            validate_decision({"action": "complete", "route_id": "r_ghost",
                               "reason": "x"}, _node(), max_nodes=8)

    def test_rejects_bad_follow_up_tool(self):
        with pytest.raises(JEVError, match="unknown"):
            validate_decision(
                {"action": "add_child", "route_id": "r_ok", "reason": "x",
                 "follow_up": {"query": "q", "tool": "shell"}},
                _node(), max_nodes=8)

    def test_rejects_non_object(self):
        with pytest.raises(JEVError, match="must be an object"):
            validate_decision(["complete"], _node(), max_nodes=8)

    def test_reason_is_trimmed(self):
        d = validate_decision({"action": "complete", "route_id": "r_ok",
                               "reason": "  ok  "}, _node(), max_nodes=8)
        assert d.reason == "ok"

    def test_tolerates_stray_follow_up_on_complete(self):
        d = validate_decision(
            {"action": "complete", "route_id": "r_ok", "reason": "x",
             "follow_up": {"query": "ignored", "tool": "none"}},
            _node(), max_nodes=8)
        assert d.follow_up is None


class TestPayload:
    def test_payload_shape(self):
        payload = build_payload(_node(), _result(), "Which parks?")
        assert payload["question"] == "Which parks?"
        assert payload["branch"]["id"] == "n1"
        assert payload["branch"]["routes"][0]["id"] == "r_ok"
        assert payload["result"]["status"] == "success"
        assert payload["result"]["row_count"] == 1
        assert payload["result"]["evidence"] == [
            {"source": "sql", "text": "Cedar Park"}]


class TestJEVDecide:
    def test_decide_happy_path(self, mock_model):
        jev = JEV(mock_model, max_nodes=8)
        tree = QueryTree.build({"root": {
            "id": "n1", "query": "q", "tool": "sql",
            "routes": [{"id": "r_ok", "when": "success"},
                       {"id": "r_empty", "when": "empty"}],
        }})
        decision = jev.decide(tree, tree.get("n1"), _result(), "Which parks?")
        assert decision.action == "complete"
        assert decision.route_id == "r_ok"

    def test_decide_budget_exhausted(self, mock_model):
        jev = JEV(mock_model, max_nodes=1)
        tree = QueryTree.build({"root": {
            "id": "n1", "query": "q", "tool": "sql",
            "routes": [{"id": "r_ok", "when": "success"}],
        }})
        bad = {"action": "add_child", "route_id": "r_ok", "reason": "x",
               "follow_up": {"query": "more", "tool": "none"}}
        mock_model.chat = lambda *a, **k: __import__("json").dumps(bad)
        with pytest.raises(JEVError, match="budget"):
            jev.decide(tree, tree.get("n1"), _result(), "q")

    def test_decide_unparseable(self):
        class Echo:
            model = "echo"
            def chat(self, *a, **k):
                return "not json at all"

        jev = JEV(Echo(), max_nodes=8)
        tree = QueryTree.build({"root": {
            "id": "n1", "query": "q", "tool": "sql",
            "routes": [{"id": "r_ok", "when": "success"}],
        }})
        with pytest.raises(JEVError, match="unparseable"):
            jev.decide(tree, tree.get("n1"), _result(), "q")
