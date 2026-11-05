"""Orchestrator: plan -> execute branches -> JEV decides -> evidence -> answer.

The loop is intentionally sequential: every branch reaches a terminal state
before the next starts, so event streams, artifacts and tests are
deterministic. Failures are propagated — there is no fallback provider and
no partial answer.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .evidence import EvidenceError, EvidenceTree, synthesize_answer
from .jev import JEV, JEVError
from .llm import LLMError
from .planner import Planner, PlannerError
from .tools import Dataset, ToolContext, ToolError, execute
from .tree import BranchResult, Node, QueryTree, Status, TreeError

EventSink = Callable[[str, dict[str, Any]], None]


class RunError(RuntimeError):
    """The investigation failed; no answer is returned."""


class Orchestrator:
    def __init__(self, *, planner: Planner, jev: JEV, answer_model,
                 dataset: Dataset, max_evidence: int = 24):
        self.planner = planner
        self.jev = jev
        self.answer_model = answer_model
        self.dataset = dataset
        self.max_evidence = max_evidence

    def run(self, question: str, emit: EventSink) -> dict[str, Any]:
        started = time.monotonic()
        query_id = uuid.uuid4().hex
        emit("query_started", {"query_id": query_id, "question": question})
        try:
            tree = self.planner.plan(question, self.dataset.schema_text)
        except PlannerError as exc:
            emit("error", {"stage": "plan", "message": str(exc)})
            raise RunError(f"plan failed: {exc}") from exc
        emit("tree", {"tree": tree.to_dict()})

        evidence = EvidenceTree(max_items=self.max_evidence)
        ctx = ToolContext(dataset=self.dataset, llm=self.planner.model)
        guard = 0
        budget = tree.max_nodes * 4 + 8

        while True:
            runnable = tree.runnable()
            if not runnable:
                break
            node = runnable[0]
            guard += 1
            if guard > budget:
                emit("error", {"stage": "budget", "message": "execution budget exhausted"})
                raise RunError("execution budget exhausted")

            node.status = Status.RUNNING
            emit("node_start", {"node_id": node.id, "query": node.query,
                                "tool": node.tool})
            result = self._execute(node, ctx)
            node.result = result
            attachable = result
            added = evidence.attach(node, attachable)
            emit("node_result", {
                "node_id": node.id,
                "status": result.status,
                "summary": result.summary,
                "error": result.error,
                "evidence": [e.to_dict() for e in added],
            })

            try:
                decision = self.jev.decide(tree, node, result, question)
            except JEVError as exc:
                emit("error", {"stage": "jev", "node_id": node.id,
                               "message": str(exc)})
                raise RunError(f"JEV decision failed: {exc}") from exc

            try:
                tree.apply(node.id, decision.to_dict())
            except TreeError as exc:
                emit("error", {"stage": "apply", "node_id": node.id,
                               "message": str(exc)})
                raise RunError(f"decision rejected: {exc}") from exc

            emit("jev_decision", {
                "node_id": node.id,
                "action": decision.action,
                "route_id": decision.route_id,
                "reason": decision.reason,
                "follow_up": decision.follow_up,
                "model": self.jev.name,
            })
            emit("tree", {"tree": tree.to_dict()})
            emit("evidence", {"items": [e.to_dict() for e in added],
                              "count": len(evidence.items)})

        failed = [n.id for n in tree.walk() if n.status is Status.FAILED]
        if failed:
            raise RunError(f"branches failed: {failed}")
        if tree.root.status is not Status.DONE:
            emit("error", {"stage": "complete",
                           "message": "tree did not reach a terminal state"})
            raise RunError("tree did not reach a terminal state")

        try:
            answer = synthesize_answer(self.answer_model, question, evidence)
        except EvidenceError as exc:
            emit("error", {"stage": "answer", "message": str(exc)})
            raise RunError(f"answer failed: {exc}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = {
            "query_id": query_id,
            "question": question,
            "answer": answer,
            "nodes": tree.counts(),
            "evidence_count": len(evidence.items),
            "elapsed_ms": elapsed_ms,
            "models": {"planner": self.planner.name, "jev": self.jev.name},
        }
        emit("answer", {"answer": answer, "evidence_count": len(evidence.items)})
        emit("done", {"query_id": query_id, "elapsed_ms": elapsed_ms})
        return {
            **payload,
            "tree": tree.to_dict(),
            "evidence": evidence.to_dict(),
        }

    @staticmethod
    def _execute(node: Node, ctx: ToolContext) -> BranchResult:
        try:
            return execute(node.tool, node.query, ctx)
        except ToolError as exc:
            return BranchResult(status="error", summary=str(exc), error=str(exc))
        except LLMError as exc:  # provider outage on the sql tool path
            return BranchResult(status="error", summary=str(exc), error=str(exc))
