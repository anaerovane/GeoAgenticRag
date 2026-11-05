"""Orchestrator: plan -> execute branches in parallel -> JEV decides -> answer.

Independent branches run concurrently on a thread pool (like the reference
implementation): retrieval/tool work and the JEV call happen inside the
worker, while every tree mutation and every event is serialized back on the
caller thread through `QueryTree.apply` — the single write gate. Failures are
propagated; there is no fallback provider and no partial answer.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable

from .evidence import EvidenceError, EvidenceTree, synthesize_answer
from .jev import Decision, JEV, JEVError
from .llm import LLMError
from .planner import Planner, PlannerError
from .tools import Dataset, ToolContext, ToolError, execute
from .tree import BranchResult, Node, QueryTree, Status, TreeError

EventSink = Callable[[str, dict[str, Any]], None]


class RunError(RuntimeError):
    """The investigation failed; no answer is returned."""


class Orchestrator:
    def __init__(self, *, planner: Planner, jev: JEV, answer_model,
                 dataset: Dataset, max_evidence: int = 24,
                 max_workers: int = 4):
        self.planner = planner
        self.jev = jev
        self.answer_model = answer_model
        self.dataset = dataset
        self.max_evidence = max_evidence
        self.max_workers = max(1, int(max_workers))

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
        budget = tree.max_nodes * 4 + 8
        dispatched = 0
        in_flight: dict[str, Future] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers,
                                thread_name_prefix="branch") as pool:
            while True:
                for node in tree.runnable():
                    if node.id in in_flight:
                        continue
                    dispatched += 1
                    if dispatched > budget:
                        emit("error", {"stage": "budget",
                                       "message": "execution budget exhausted"})
                        raise RunError("execution budget exhausted")
                    node.status = Status.RUNNING
                    emit("node_start", {"node_id": node.id, "query": node.query,
                                        "tool": node.tool})
                    in_flight[node.id] = pool.submit(
                        self._branch, node, ctx, question, tree)
                if not in_flight:
                    break

                finished, _ = wait(list(in_flight.values()),
                                   return_when=FIRST_COMPLETED)
                for future in finished:
                    node_id = next(k for k, v in in_flight.items() if v is future)
                    del in_flight[node_id]
                    node = tree.get(node_id)
                    try:
                        result, decision = future.result()
                    except JEVError as exc:
                        emit("error", {"stage": "jev", "node_id": node_id,
                                       "message": str(exc)})
                        raise RunError(f"JEV decision failed: {exc}") from exc
                    except Exception as exc:  # noqa: BLE001 — worker crash
                        emit("error", {"stage": "branch", "node_id": node_id,
                                       "message": f"{type(exc).__name__}: {exc}"})
                        raise RunError(f"branch {node_id} crashed: {exc}") from exc

                    node.result = result
                    added = evidence.attach(node, result)
                    emit("node_result", {
                        "node_id": node.id,
                        "status": result.status,
                        "summary": result.summary,
                        "error": result.error,
                        "evidence": [e.to_dict() for e in added],
                    })
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

    # -- worker side (runs on pool threads) --------------------------------
    def _branch(self, node: Node, ctx: ToolContext, question: str,
                tree: QueryTree) -> tuple[BranchResult, Decision]:
        """Execute one branch and ask JEV for its decision.

        Reads of the tree are safe here (workers only read `size`/`routes`);
        every write happens later on the caller thread.
        """
        result = self._execute(node, ctx)
        decision = self.jev.decide(tree, node, result, question)
        return result, decision

    @staticmethod
    def _execute(node: Node, ctx: ToolContext) -> BranchResult:
        try:
            return execute(node.tool, node.query, ctx)
        except ToolError as exc:
            return BranchResult(status="error", summary=str(exc), error=str(exc))
        except LLMError as exc:  # provider outage on the sql tool path
            return BranchResult(status="error", summary=str(exc), error=str(exc))
