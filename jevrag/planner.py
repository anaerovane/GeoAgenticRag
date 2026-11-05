"""Planner: question + dataset schema -> validated QueryTree.

One LLM call, one validation pass, one repair retry with the validation
error fed back. There is no mode switch and no accumulated rule set —
anything the validator can enforce is enforced in code.
"""
from __future__ import annotations

import json
from typing import Any

from . import prompts
from .llm import LLMError, extract_json
from .tree import QueryTree, TreeError


class PlannerError(RuntimeError):
    """The planner could not produce a valid tree."""


class Planner:
    def __init__(self, model, *, max_nodes: int = 16, max_depth: int = 5,
                 repairs: int = 1):
        self.model = model
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.repairs = repairs

    @property
    def name(self) -> str:
        return getattr(self.model, "model", type(self.model).__name__)

    def plan(self, question: str, schema: str) -> QueryTree:
        if not question.strip():
            raise PlannerError("empty question")
        user = prompts.PLANNER.format(schema=schema or "(no schema registered)",
                                      question=question)
        last_error = "unknown"
        for attempt in range(self.repairs + 1):
            system = user if attempt == 0 else (
                user + f"\n\nYour previous plan was rejected:\n{last_error}\n"
                       "Return a corrected plan as JSON."
            )
            try:
                reply = self.model.chat(system, "Return the query tree JSON.",
                                        max_tokens=1200)
            except LLMError as exc:
                raise PlannerError(str(exc)) from exc
            try:
                data = extract_json(reply)
                return QueryTree.build(data, max_nodes=self.max_nodes,
                                       max_depth=self.max_depth)
            except (LLMError, TreeError, KeyError, TypeError) as exc:
                last_error = str(exc)
        raise PlannerError(f"plan invalid after {self.repairs + 1} attempts: {last_error}")


def schema_summary(tables: list[dict[str, Any]]) -> str:
    """Compact text schema for the planner prompt (tables + columns)."""
    lines: list[str] = []
    for table in tables:
        name = table.get("name", "data")
        cols = ", ".join(
            f"{c.get('name')}:{c.get('type', '?')}" for c in table.get("columns", [])
        )
        lines.append(f"{name}({cols})")
        for row in table.get("sample", [])[:2]:
            preview = ", ".join(f"{k}={v!r}" for k, v in list(row.items())[:6])
            lines.append(f"  e.g. {preview}")
    return "\n".join(lines) or "(no tables)"
