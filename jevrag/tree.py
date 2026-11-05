"""Query Tree: the operational contract of one investigation.

A tree is planned once, then mutated only through `QueryTree.apply`, which
validates every JEV proposal before anything changes. Nodes declare routes;
each child names the route ("always" or a route id) that activates it. When a
branch finishes, the selected route keeps its children pending and every other
conditional child is pruned. This module does no I/O and makes no model calls,
so it can be unit-tested alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    PRUNED = "pruned"
    FAILED = "failed"


class Tool(str, Enum):
    SQL = "sql"
    SEARCH = "search"
    NONE = "none"


VALID_TOOLS = {t.value for t in Tool}
_ROUTE_WHEN = {"success", "empty", "error"}
_ACTIONS = {"complete", "add_child", "prune", "fail"}


class TreeError(ValueError):
    """A plan or decision violates the tree contract."""


@dataclass(slots=True)
class Route:
    id: str
    when: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "when": self.when}


@dataclass(slots=True)
class BranchResult:
    status: str                     # success | empty | error
    summary: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "rows": self.rows[:20],
            "evidence": self.evidence,
            "error": self.error,
        }


@dataclass(slots=True)
class Node:
    id: str
    query: str
    tool: str
    when: str = "always"
    status: Status = Status.PENDING
    routes: list[Route] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    result: BranchResult | None = None
    decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "tool": self.tool,
            "when": self.when,
            "status": self.status.value,
            "routes": [r.to_dict() for r in self.routes],
            "result": self.result.to_dict() if self.result else None,
            "decision": self.decision,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        node = cls(
            id=str(data["id"]),
            query=str(data.get("query", "")),
            tool=str(data.get("tool", Tool.NONE.value)),
            when=str(data.get("when", "always")),
            routes=[Route(str(r["id"]), str(r.get("when", "success")))
                    for r in data.get("routes", [])],
        )
        if "status" in data:
            try:
                node.status = Status(data["status"])
            except ValueError:
                node.status = Status.PENDING
        node.children = [cls.from_dict(c) for c in data.get("children", [])]
        return node


class QueryTree:
    """Validated wrapper around the root node with a single write gate."""

    def __init__(self, root: Node, *, max_nodes: int = 16, max_depth: int = 5):
        self.root = root
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self._index: dict[str, Node] = {}
        self._parent: dict[str, Node | None] = {}
        self._rebuild_index()

    # -- indexing ----------------------------------------------------------
    def _rebuild_index(self) -> None:
        self._index = {}
        self._parent = {self.root.id: None}
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node.id in self._index:
                raise TreeError(f"duplicate node id {node.id!r}")
            self._index[node.id] = node
            for child in node.children:
                if child.id in self._parent:
                    raise TreeError(f"duplicate node id {child.id!r}")
                self._parent[child.id] = node
                stack.append(child)

    def walk(self) -> Iterator[Node]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def get(self, node_id: str) -> Node:
        try:
            return self._index[node_id]
        except KeyError as exc:
            raise TreeError(f"unknown node {node_id!r}") from exc

    def parent_of(self, node_id: str) -> Node | None:
        return self._parent.get(node_id)

    @property
    def size(self) -> int:
        return len(self._index)

    # -- construction / validation ----------------------------------------
    @classmethod
    def build(cls, root_data: dict[str, Any], *, max_nodes: int = 16,
              max_depth: int = 5) -> "QueryTree":
        if "root" in root_data:
            root_data = root_data["root"]
        root = Node.from_dict(root_data)
        tree = cls(root, max_nodes=max_nodes, max_depth=max_depth)
        tree._validate_structure(root)
        tree._rebuild_index()
        return tree

    def _validate_structure(self, root: Node) -> None:
        seen: set[str] = set()

        def visit(node: Node, depth: int) -> None:
            if depth > self.max_depth:
                raise TreeError(f"tree deeper than {self.max_depth} at {node.id}")
            if node.id in seen:
                raise TreeError(f"duplicate node id {node.id!r}")
            seen.add(node.id)
            if node.tool not in VALID_TOOLS:
                raise TreeError(f"node {node.id}: unknown tool {node.tool!r}")
            if not node.query.strip():
                raise TreeError(f"node {node.id}: empty query")
            if not node.routes:
                raise TreeError(f"node {node.id}: must declare at least one route")
            route_ids = [r.id for r in node.routes]
            if len(route_ids) != len(set(route_ids)):
                raise TreeError(f"node {node.id}: duplicate route ids")
            for route in node.routes:
                if route.when not in _ROUTE_WHEN:
                    raise TreeError(f"node {node.id}: route {route.id} bad when {route.when!r}")
            for child in node.children:
                if child.when != "always" and child.when not in route_ids:
                    raise TreeError(
                        f"node {node.id}: child {child.id} waits on undeclared route {child.when!r}"
                    )
                visit(child, depth + 1)

        visit(root, 1)
        if len(seen) > self.max_nodes:
            raise TreeError(f"tree has {len(seen)} nodes; max is {self.max_nodes}")

    # -- scheduling --------------------------------------------------------
    def runnable(self) -> list[Node]:
        """Pending nodes ready to execute: the root, or children of a DONE parent."""
        out: list[Node] = []
        for node in self.walk():
            if node.status is not Status.PENDING:
                continue
            parent = self._parent.get(node.id)
            if parent is None or parent.status is Status.DONE:
                out.append(node)
        return out

    def unsettled(self) -> list[Node]:
        return [n for n in self.walk() if n.status in (Status.PENDING, Status.RUNNING)]

    # -- mutation (single write gate) --------------------------------------
    def apply(self, node_id: str, decision: dict[str, Any]) -> list[Node]:
        """Validate and commit one JEV decision; return newly runnable nodes."""
        node = self.get(node_id)
        if node.status is not Status.RUNNING:
            raise TreeError(f"node {node_id} is {node.status.value}, not running")
        action = decision.get("action")
        route_id = decision.get("route_id")
        if action not in _ACTIONS:
            raise TreeError(f"unknown action {action!r}")
        route_ids = {r.id for r in node.routes}
        if route_id not in route_ids:
            raise TreeError(f"route {route_id!r} not declared on {node_id}")

        if action == "fail":
            node.status = Status.FAILED
            node.decision = dict(decision, applied=True)
            raise TreeError(f"JEV failed branch {node_id}: {decision.get('reason', '')}")

        if action == "add_child":
            follow = decision.get("follow_up") or {}
            child = Node(
                id=self._fresh_id(str(follow.get("query", "follow-up"))),
                query=str(follow.get("query", "")).strip(),
                tool=str(follow.get("tool", Tool.NONE.value)),
                when=route_id,
            )
            if child.tool not in VALID_TOOLS:
                raise TreeError(f"follow_up tool {child.tool!r} unknown")
            if not child.query:
                raise TreeError("follow_up.query is empty")
            if self.size + 1 > self.max_nodes:
                raise TreeError("node budget exhausted")
            node.children.append(child)
            self._parent[child.id] = node
            self._index[child.id] = child

        # Activate always + selected-route children; prune the rest.
        # "prune" is stricter: every conditional child is dropped, even one
        # waiting on the selected route (the route is still recorded).
        for child in node.children:
            if child.status is not Status.PENDING or child.when == "always":
                continue
            if action != "prune" and child.when == route_id:
                continue
            child.status = Status.PRUNED

        node.decision = dict(decision, applied=True)
        node.status = Status.DONE
        return self.runnable()

    def _fresh_id(self, hint: str) -> str:
        base = "".join(ch for ch in hint.lower() if ch.isalnum())[:10] or "task"
        index = 1
        while f"{base}_{index}" in self._index:
            index += 1
        return f"{base}_{index}"

    # -- output ------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return self.root.to_dict()

    def counts(self) -> dict[str, int]:
        tally = {s.value: 0 for s in Status}
        for node in self.walk():
            tally[node.status.value] += 1
        return tally
