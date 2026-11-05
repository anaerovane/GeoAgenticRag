"""Evidence Tree: persistent observations that survive branch pruning.

Every retrieval hit and tool output is attached as an evidence item keyed by
id. The tree never drops items when a branch is pruned — only the *plan*
changes; recorded observations stay. The final answer prompt sees exactly
this list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import prompts
from .llm import LLMError
from .tree import BranchResult, Node


class EvidenceError(RuntimeError):
    """Answer synthesis failed."""


@dataclass(slots=True)
class EvidenceItem:
    id: str
    node_id: str
    source: str          # sql | search | tool
    text: str
    score: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "node_id": self.node_id, "source": self.source,
                "text": self.text, "score": self.score, "payload": self.payload}


class EvidenceTree:
    def __init__(self, max_items: int = 24):
        self.max_items = max_items
        self.items: list[EvidenceItem] = []
        self._seen: set[str] = set()

    def attach(self, node: Node, result: BranchResult) -> list[EvidenceItem]:
        added: list[EvidenceItem] = []
        for raw in result.evidence:
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            fingerprint = f"{node.id}:{raw.get('source')}:{text[:120]}"
            if fingerprint in self._seen:
                continue
            if len(self.items) >= self.max_items:
                break
            self._seen.add(fingerprint)
            item = EvidenceItem(
                id=f"e{len(self.items) + 1}",
                node_id=node.id,
                source=str(raw.get("source", "tool")),
                text=text[:600],
                payload=raw.get("payload", {}) or {},
            )
            self.items.append(item)
            added.append(item)
        return added

    def to_prompt(self) -> str:
        lines = []
        for item in self.items:
            lines.append(f"[{item.id}] ({item.source}, node {item.node_id}) {item.text}")
        return "\n".join(lines) or "[e1] (none) no evidence collected"

    def to_dict(self) -> dict[str, Any]:
        return {"items": [i.to_dict() for i in self.items],
                "count": len(self.items)}


def synthesize_answer(model, question: str, evidence: EvidenceTree) -> str:
    """Final answer from evidence only (one call, temperature 0)."""
    try:
        reply = model.chat(
            prompts.ANSWER.format(question=question, evidence=evidence.to_prompt()),
            "Produce the final answer now.",
            max_tokens=600,
        )
    except LLMError as exc:
        raise EvidenceError(str(exc)) from exc
    return reply.strip()
