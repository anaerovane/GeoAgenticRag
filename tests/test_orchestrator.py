"""Orchestrator: end-to-end mock runs, parallel dispatch, failure propagation."""
from __future__ import annotations

import json
import threading

import pytest

from jevrag.jev import JEV
from jevrag.llm import MockLLM
from jevrag.orchestrator import Orchestrator, RunError
from jevrag.planner import Planner


class PlanScripted(MockLLM):
    """MockLLM whose plan shape is supplied per-test."""

    def __init__(self, plan):
        super().__init__()
        self._plan_obj = plan

    @staticmethod
    def _plan_static(plan, system):
        return plan

    def chat(self, system, user, **kwargs):
        if system.startswith("You are the planner"):
            with self._lock:
                self.calls.append((system, user))
            return json.dumps(self._plan_obj)
        return super().chat(system, user, **kwargs)


def _routes():
    return [{"id": "r_ok", "when": "success"}, {"id": "r_empty", "when": "empty"}]


def _orch(model, demo_dataset, **kw):
    return Orchestrator(planner=Planner(model), jev=JEV(model),
                        answer_model=model, dataset=demo_dataset, **kw)


class TestMockRun:
    def test_end_to_end(self, demo_dataset):
        events = []
        result = _orch(MockLLM(), demo_dataset).run(
            "Which parks are in the West End?",
            lambda e, d: events.append((e, d)))
        assert result["nodes"]["failed"] == 0
        assert result["evidence_count"] > 0
        assert result["answer"]
        assert result["models"]["jev"] == "mock"
        assert [e for e, _ in events][0] == "query_started"
        assert [e for e, _ in events][-1] == "done"
        # JEV decisions are emitted for every finished branch.
        decisions = [d for e, d in events if e == "jev_decision"]
        assert len(decisions) == result["nodes"]["done"]
        assert all(d["action"] in {"complete", "add_child", "prune", "fail"}
                   for d in decisions)

    def test_tree_snapshots_follow_each_decision(self, demo_dataset):
        events = []
        _orch(MockLLM(), demo_dataset).run("q", lambda e, d: events.append(e))
        names = [e for e in events]
        assert names.count("tree") >= 2  # after plan + after each decision
        assert "evidence" in names and "answer" in names


class TestParallelDispatch:
    def test_siblings_dispatched_before_results(self, demo_dataset):
        plan = {"root": {
            "id": "n1", "query": "q1", "tool": "sql", "routes": _routes(),
            "children": [
                {"id": "n2", "query": "q2", "tool": "none", "when": "always",
                 "routes": _routes()},
                {"id": "n3", "query": "q3", "tool": "none", "when": "always",
                 "routes": _routes()},
            ],
        }}
        events = []
        result = _orch(PlanScripted(plan), demo_dataset, max_workers=4).run(
            "q", lambda e, d: events.append((e, d)))
        assert result["nodes"]["done"] == 3
        names = [e for e, _ in events]
        starts = [i for i, e in enumerate(names) if e == "node_start"]
        # Both siblings started before their decisions were applied.
        assert starts[1] < names.index("jev_decision", starts[1]) + 1
        # In-order dispatch of all three node ids.
        ids = [d["node_id"] for e, d in events if e == "node_start"]
        assert ids[0] == "n1" and set(ids[1:]) == {"n2", "n3"}

    def test_max_workers_is_serial_when_one(self, demo_dataset):
        plan = {"root": {
            "id": "n1", "query": "q1", "tool": "sql", "routes": _routes(),
            "children": [
                {"id": "n2", "query": "q2", "tool": "none", "when": "always",
                 "routes": _routes()},
            ],
        }}
        result = _orch(PlanScripted(plan), demo_dataset, max_workers=1).run(
            "q", lambda e, d: None)
        assert result["nodes"]["done"] == 2

    def test_concurrent_branches_do_not_deadlock(self, demo_dataset):
        # Four siblings at once; the pool must drain them all.
        children = [{"id": f"n{i}", "query": f"q{i}", "tool": "none",
                     "when": "always", "routes": _routes()} for i in range(2, 6)]
        plan = {"root": {"id": "n1", "query": "q1", "tool": "sql",
                         "routes": _routes(), "children": children}}
        result = _orch(PlanScripted(plan), demo_dataset, max_workers=4).run(
            "q", lambda e, d: None)
        assert result["nodes"]["done"] == 5


class TestFailures:
    def test_plan_failure_propagates(self, demo_dataset):
        class NoPlan:
            model = "noplan"
            def chat(self, *a, **k):
                from jevrag.llm import LLMError
                raise LLMError("provider down")

        events = []
        with pytest.raises(RunError, match="plan failed"):
            _orch(NoPlan(), demo_dataset).run("q", lambda e, d: events.append((e, d)))
        assert events[-1][0] == "error"
        assert events[-1][1]["stage"] == "plan"

    def test_jev_fail_action_fails_the_run(self, demo_dataset):
        class FailingJEV(MockLLM):
            def chat(self, system, user, **kwargs):
                if system.startswith("You are JEV"):
                    return json.dumps({
                        "action": "fail", "route_id": "r_ok",
                        "reason": "unusable result"})
                return super().chat(system, user, **kwargs)

        events = []
        with pytest.raises(RunError, match="decision rejected"):
            _orch(FailingJEV(), demo_dataset).run("q", lambda e, d: events.append((e, d)))
        stages = [d.get("stage") for e, d in events if e == "error"]
        assert "apply" in stages

    def test_jev_invalid_decision_fails_the_run(self, demo_dataset):
        class BadJEV(MockLLM):
            def chat(self, system, user, **kwargs):
                if system.startswith("You are JEV"):
                    return json.dumps({"action": "complete",
                                       "route_id": "r_invented", "reason": "x"})
                return super().chat(system, user, **kwargs)

        with pytest.raises(RunError, match="JEV decision failed"):
            _orch(BadJEV(), demo_dataset).run("q", lambda e, d: None)

    def test_worker_crash_is_a_run_error(self, demo_dataset):
        plan = {"root": {"id": "n1", "query": "q", "tool": "sql",
                         "routes": _routes()}}
        model = PlanScripted(plan)

        class ExplodingJEV(JEV):
            def decide(self, *a, **k):
                raise RuntimeError("kaboom")

        orch = Orchestrator(planner=Planner(model), jev=ExplodingJEV(model),
                            answer_model=model, dataset=demo_dataset)
        with pytest.raises(RunError, match="crashed"):
            orch.run("q", lambda e, d: None)

    def test_budget_guard_on_runaway_dispatch(self, demo_dataset):
        # A tiny max_nodes keeps the budget small; add_child churn must stop.
        plan = {"root": {"id": "n1", "query": "q", "tool": "none",
                         "routes": _routes()}}
        model = PlanScripted(plan)

        class ChurnJEV(JEV):
            def decide(self, tree, node, result, question):
                from jevrag.jev import Decision
                return Decision(action="add_child", route_id="r_ok",
                                reason="churn",
                                follow_up={"query": "more", "tool": "none"})

        orch = Orchestrator(planner=Planner(model), jev=ChurnJEV(model),
                            answer_model=model, dataset=demo_dataset, max_workers=1)
        with pytest.raises(RunError):
            orch.run("q", lambda e, d: None)


class TestEvidenceSurvives:
    def test_pruned_branch_evidence_still_counted(self, demo_dataset):
        plan = {"root": {
            "id": "n1", "query": "list parks", "tool": "sql", "routes": _routes(),
            "children": [{"id": "n2", "query": "dead end", "tool": "none",
                          "when": "r_empty", "routes": _routes()}],
        }}
        events = []
        result = _orch(PlanScripted(plan), demo_dataset).run(
            "Which parks?", lambda e, d: events.append((e, d)))
        # n2 waits on r_empty but n1 succeeds -> n2 pruned; n1's evidence stays.
        assert result["nodes"]["pruned"] == 1
        assert result["evidence_count"] > 0
        assert result["tree"]["children"][0]["status"] == "pruned"
