"""QueryTree contract: validation, single write gate, route pruning."""
from __future__ import annotations

import pytest

from jevrag.tree import QueryTree, Status, TreeError


def _plan(children=None, routes=None):
    routes = routes or [{"id": "r_ok", "when": "success"},
                        {"id": "r_empty", "when": "empty"}]
    return {
        "root": {
            "id": "n1", "query": "root task", "tool": "sql", "routes": routes,
            "children": children or [],
        }
    }


def _child(cid, when="always", routes=None):
    return {"id": cid, "query": f"task {cid}", "tool": "none", "when": when,
            "routes": routes or [{"id": "r_ok", "when": "success"}]}


class TestBuild:
    def test_builds_and_indexes(self):
        tree = QueryTree.build(_plan([_child("n2")]))
        assert tree.size == 2
        assert tree.get("n2").when == "always"

    def test_accepts_wrapped_root(self):
        tree = QueryTree.build({"root": _plan()["root"]})
        assert tree.root.id == "n1"

    def test_rejects_duplicate_ids(self):
        with pytest.raises(TreeError, match="duplicate"):
            QueryTree.build(_plan([_child("n1")]))

    def test_rejects_unknown_tool(self):
        plan = _plan()
        plan["root"]["tool"] = "shell"
        with pytest.raises(TreeError, match="unknown tool"):
            QueryTree.build(plan)

    def test_rejects_empty_query(self):
        plan = _plan()
        plan["root"]["query"] = "  "
        with pytest.raises(TreeError, match="empty query"):
            QueryTree.build(plan)

    def test_rejects_node_without_routes(self):
        plan = _plan()
        plan["root"]["routes"] = []
        with pytest.raises(TreeError, match="at least one route"):
            QueryTree.build(plan)

    def test_rejects_child_on_undeclared_route(self):
        with pytest.raises(TreeError, match="undeclared route"):
            QueryTree.build(_plan([_child("n2", when="r_missing")]))

    def test_rejects_bad_route_when(self):
        plan = _plan(routes=[{"id": "r_ok", "when": "maybe"}])
        with pytest.raises(TreeError, match="bad when"):
            QueryTree.build(plan)

    def test_rejects_too_many_nodes(self):
        children = [_child(f"n{i}", when="always") for i in range(2, 12)]
        with pytest.raises(TreeError, match="max is"):
            QueryTree.build(_plan(children), max_nodes=10)

    def test_rejects_too_deep(self):
        plan = {"root": _child("n1")}
        node = plan["root"]
        for i in range(2, 6):
            node["children"] = [_child(f"n{i}")]
            node = node["children"][0]
        with pytest.raises(TreeError, match="deeper"):
            QueryTree.build(plan, max_depth=3)


class TestApply:
    def _running_tree(self, children=None):
        tree = QueryTree.build(_plan(children))
        tree.get("n1").status = Status.RUNNING
        return tree

    def test_complete_prunes_unselected_conditional_children(self):
        tree = self._running_tree([
            _child("n2", when="r_ok"),
            _child("n3", when="r_empty"),
            _child("n4", when="always"),
        ])
        tree.apply("n1", {"action": "complete", "route_id": "r_ok", "reason": "ok"})
        assert tree.get("n1").status is Status.DONE
        assert tree.get("n2").status is Status.PENDING
        assert tree.get("n3").status is Status.PRUNED
        assert tree.get("n4").status is Status.PENDING
        runnable = {n.id for n in tree.runnable()}
        assert runnable == {"n2", "n4"}

    def test_add_child_creates_validated_node(self):
        tree = self._running_tree()
        tree.apply("n1", {
            "action": "add_child", "route_id": "r_ok", "reason": "need more",
            "follow_up": {"query": "drill down", "tool": "search"},
        })
        fresh = [n for n in tree.walk() if n.id != "n1"]
        assert len(fresh) == 1
        assert fresh[0].query == "drill down"
        assert fresh[0].tool == "search"
        assert fresh[0].when == "r_ok"

    def test_add_child_respects_budget(self):
        tree = self._running_tree()
        tree.max_nodes = 1
        with pytest.raises(TreeError, match="budget"):
            tree.apply("n1", {
                "action": "add_child", "route_id": "r_ok", "reason": "x",
                "follow_up": {"query": "more", "tool": "none"},
            })

    def test_add_child_requires_query(self):
        tree = self._running_tree()
        with pytest.raises(TreeError, match="empty"):
            tree.apply("n1", {
                "action": "add_child", "route_id": "r_ok", "reason": "x",
                "follow_up": {"query": "", "tool": "none"},
            })

    def test_prune_keeps_always_children_only(self):
        tree = self._running_tree([
            _child("n2", when="r_ok"),
            _child("n3", when="always"),
        ])
        tree.apply("n1", {"action": "prune", "route_id": "r_ok", "reason": "done"})
        assert tree.get("n2").status is Status.PRUNED
        assert {n.id for n in tree.runnable()} == {"n3"}

    def test_fail_marks_node_and_raises(self):
        tree = self._running_tree()
        with pytest.raises(TreeError, match="failed branch"):
            tree.apply("n1", {"action": "fail", "route_id": "r_ok", "reason": "unusable"})
        assert tree.get("n1").status is Status.FAILED

    def test_rejects_unknown_action(self):
        tree = self._running_tree()
        with pytest.raises(TreeError, match="unknown action"):
            tree.apply("n1", {"action": "explode", "route_id": "r_ok", "reason": "x"})

    def test_rejects_undeclared_route(self):
        tree = self._running_tree()
        with pytest.raises(TreeError, match="not declared"):
            tree.apply("n1", {"action": "complete", "route_id": "r_nope", "reason": "x"})

    def test_rejects_apply_on_non_running_node(self):
        tree = QueryTree.build(_plan())
        with pytest.raises(TreeError, match="not running"):
            tree.apply("n1", {"action": "complete", "route_id": "r_ok", "reason": "x"})

    def test_records_decision(self):
        tree = self._running_tree()
        tree.apply("n1", {"action": "complete", "route_id": "r_ok", "reason": "fine"})
        assert tree.get("n1").decision == {
            "action": "complete", "route_id": "r_ok", "reason": "fine", "applied": True}


class TestScheduling:
    def test_runnable_is_root_first(self):
        tree = QueryTree.build(_plan([_child("n2")]))
        assert [n.id for n in tree.runnable()] == ["n1"]

    def test_children_runnable_after_parent_done(self):
        tree = QueryTree.build(_plan([_child("n2")]))
        tree.get("n1").status = Status.RUNNING
        tree.apply("n1", {"action": "complete", "route_id": "r_ok", "reason": "ok"})
        assert [n.id for n in tree.runnable()] == ["n2"]

    def test_counts(self):
        tree = QueryTree.build(_plan([_child("n2", when="r_empty")]))
        tree.get("n1").status = Status.RUNNING
        tree.apply("n1", {"action": "complete", "route_id": "r_ok", "reason": "ok"})
        counts = tree.counts()
        assert counts["done"] == 1
        assert counts["pruned"] == 1

    def test_round_trip_to_dict(self):
        tree = QueryTree.build(_plan([_child("n2")]))
        rebuilt = QueryTree.build({"root": tree.to_dict()})
        assert rebuilt.size == 2
        assert rebuilt.get("n2").query == "task n2"
