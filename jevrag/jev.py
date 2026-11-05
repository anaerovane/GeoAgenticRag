"""JEV — the branch controller.

After every branch result, JEV reads the result plus the node's declared
routes and proposes exactly one decision: complete, add_child, prune or fail.
The proposal is checked against the declared contract here; the QueryTree
performs the actual state change. Decoding is plain JSON (temperature 0) so
the same prompt works against any OpenAI-compatible endpoint, including a
small dedicated JEV model served by vLLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from . import prompts
from .llm import LLMError, MockLLM, extract_json
from .tree import BranchResult, Node, QueryTree, TreeError

_ACTIONS = {"complete", "add_child", "prune", "fail"}
_FOLLOW_UP_TOOLS = {"sql", "search", "none"}


class JEVError(RuntimeError):
    """JEV returned something that violates the decision contract."""


@dataclass(slots=True)
class Decision:
    action: str
    route_id: str
    reason: str
    follow_up: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "action": self.action,
            "route_id": self.route_id,
            "reason": self.reason,
        }
        if self.follow_up:
            out["follow_up"] = self.follow_up
        return out


class ChatModel(Protocol):
    model: str

    def chat(self, system: str, user: str, *, json_schema: dict | None = None,
             temperature: float = 0.0, max_tokens: int = 1024) -> str: ...


def build_payload(node: Node, result: BranchResult, question: str) -> dict[str, Any]:
    """The exact context JEV sees for one branch."""
    return {
        "question": question,
        "branch": {
            "id": node.id,
            "query": node.query,
            "tool": node.tool,
            "routes": [r.to_dict() for r in node.routes],
        },
        "result": {
            "status": result.status,
            "summary": result.summary[:2000],
            "error": result.error[:400],
            "row_count": len(result.rows),
            "evidence_ids": [e.get("id") for e in result.evidence[:12]],
        },
    }


def validate_decision(raw: Any, node: Node, *, max_nodes: int) -> Decision:
    """Enforce the decision contract; raise JEVError on any violation."""
    if not isinstance(raw, dict):
        raise JEVError(f"decision must be an object, got {type(raw).__name__}")
    action = raw.get("action")
    if action not in _ACTIONS:
        raise JEVError(f"unknown action {action!r}")
    route_id = raw.get("route_id")
    declared = {r.id for r in node.routes}
    if route_id not in declared:
        raise JEVError(f"route {route_id!r} not declared (have {sorted(declared)})")
    reason = str(raw.get("reason", "")).strip()[:160]
    follow_up = None
    if action == "add_child":
        follow = raw.get("follow_up")
        if not isinstance(follow, dict):
            raise JEVError("add_child requires a follow_up object")
        query = str(follow.get("query", "")).strip()
        tool = str(follow.get("tool", "")).strip()
        if not query:
            raise JEVError("follow_up.query is empty")
        if tool not in _FOLLOW_UP_TOOLS:
            raise JEVError(f"follow_up.tool {tool!r} unknown")
        if len(query) > 300:
            raise JEVError("follow_up.query too long")
        follow_up = {"query": query, "tool": tool}
    elif raw.get("follow_up") is not None and action != "add_child":
        # Tolerate but drop extraneous follow_up on other actions.
        pass
    return Decision(action=action, route_id=route_id, reason=reason, follow_up=follow_up)


class JEV:
    """One JEV instance bound to a chat model (real or mock)."""

    def __init__(self, model: ChatModel, *, max_nodes: int = 16):
        self.model = model
        self.max_nodes = max_nodes

    @property
    def name(self) -> str:
        return getattr(self.model, "model", type(self.model).__name__)

    def decide(self, tree: QueryTree, node: Node, result: BranchResult,
               question: str) -> Decision:
        payload = build_payload(node, result, question)
        try:
            reply = self.model.chat(
                prompts.JEV,
                f"Decision context: {payload}",
                max_tokens=400,
            )
        except LLMError as exc:
            raise JEVError(str(exc)) from exc
        try:
            raw = extract_json(reply)
        except LLMError as exc:
            raise JEVError(f"unparseable decision: {exc}") from exc
        decision = validate_decision(raw, node, max_nodes=self.max_nodes)
        # Cross-check against tree budget before the tree sees it.
        if decision.action == "add_child" and tree.size >= self.max_nodes:
            raise JEVError("node budget exhausted; add_child rejected")
        return decision


def jev_from_settings(settings) -> JEV:
    """Build the JEV instance described by settings (mock-aware)."""
    from .llm import make_llm
    model = make_llm(settings, "jev")
    if not settings.mock and isinstance(model, MockLLM):  # pragma: no cover - defensive
        raise JEVError("JEV model misconfigured")
    return JEV(model, max_nodes=settings.max_nodes)
