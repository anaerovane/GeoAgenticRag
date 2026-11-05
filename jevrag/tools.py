"""Tool registry: sql, search, none — plus a clear extension point.

Every tool is `run(task, context) -> BranchResult`. The sql tool executes
read-only statements against SQLite tables registered from CSV/GeoJSON files
and exposes a haversine() helper for spatial filters. Read-only is enforced
by a SQLite authorizer, not by string matching.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import prompts
from .llm import LLMError, extract_json
from .retrieval import SourceIndex
from .tree import BranchResult

SQL_LIMIT = 100


class ToolError(RuntimeError):
    """A tool could not execute the requested task."""


def _authorizer(action: int, arg1: str | None, arg2: str | None,
                db: str | None, trigger: str | None) -> int:
    # SQLITE_READ=20, SQLITE_SELECT=21, SQLITE_FUNCTION=31, SQLITE_RECURSIVE=33.
    # Everything else (DDL/DML/PRAGMA/ATTACH/...) is denied: read-only by
    # construction, not by string matching.
    if action in (20, 21, 31, 33):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# Dataset: registered tables in one SQLite database
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Dataset:
    id: str
    tables: list[dict[str, Any]]
    index: SourceIndex
    db_path: Path
    _conn: sqlite3.Connection | None = None

    @property
    def schema_text(self) -> str:
        from .planner import schema_summary
        return schema_summary(self.tables)

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.db_path.exists():
                raise ToolError(f"dataset database missing: {self.db_path}")
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True,
                                   check_same_thread=False)
            conn.create_function("haversine", 4, _haversine, deterministic=True)
            conn.set_authorizer(_authorizer)
            conn.row_factory = sqlite3.Row
            self._conn = conn
        return self._conn


def load_dataset(dataset_id: str, spec: dict[str, Any]) -> Dataset:
    """Open a dataset: SQLite db (built by `jevrag index`) + source index JSON."""
    db_path = Path(spec["db"])
    index_path = Path(spec.get("index", db_path.with_suffix(".index.json")))
    if not index_path.exists():
        raise ToolError(f"source index missing: {index_path}")
    tables = json.loads(db_path.with_suffix(".tables.json").read_text(encoding="utf-8")) \
        if db_path.with_suffix(".tables.json").exists() else []
    return Dataset(id=dataset_id, tables=tables,
                   index=SourceIndex.load(index_path), db_path=db_path)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ToolContext:
    dataset: Dataset
    llm: Any  # planner-role LLM used for text->SQL


def run_sql(task: str, ctx: ToolContext) -> BranchResult:
    schema = ctx.dataset.schema_text
    try:
        reply = ctx.llm.chat(
            prompts.SQL.format(schema=schema, task=task),
            f"Task: {task}",
            max_tokens=400,
        )
        payload = extract_json(reply)
        sql = str(payload.get("sql", "")).strip().rstrip(";")
    except (LLMError, AttributeError, json.JSONDecodeError) as exc:
        raise ToolError(f"sql generation failed: {exc}") from exc
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        raise ToolError(f"only SELECT/WITH allowed, got: {sql[:80]!r}")
    if ";" in sql:
        raise ToolError("multiple statements are not allowed")
    try:
        conn = ctx.dataset.connect()
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = [dict(zip(columns, row)) for row in cursor.fetchmany(SQL_LIMIT + 1)]
    except sqlite3.Error as exc:
        return BranchResult(status="error", summary=f"SQL failed: {exc}",
                            error=str(exc))
    truncated = len(rows) > SQL_LIMIT
    rows = rows[:SQL_LIMIT]
    status = "success" if rows else "empty"
    summary = (f"{len(rows)} rows from SQL"
               + (" (truncated)" if truncated else "")) if rows else "SQL returned no rows"
    evidence = [{
        "source": "sql",
        "text": ", ".join(f"{k}={v}" for k, v in list(row.items())[:8]),
        "payload": {"sql": sql, "row_count": len(rows)},
    } for row in rows[:8]]
    return BranchResult(status=status, summary=summary, rows=rows, evidence=evidence)


def run_search(task: str, ctx: ToolContext) -> BranchResult:
    hits = ctx.dataset.index.search(task, k=8)
    if not hits:
        return BranchResult(status="empty", summary="no matching sources")
    evidence = [{
        "source": "search",
        "text": f"{h['doc']['title']}: {h['doc']['description'][:240]}",
        "payload": {"doc_id": h["doc"]["id"], "bm25": h["score"]},
    } for h in hits[:6]]
    summary = "; ".join(h["doc"]["title"] for h in hits[:4])
    return BranchResult(status="success", summary=f"sources: {summary}",
                        evidence=evidence)


def run_none(task: str, ctx: ToolContext) -> BranchResult:
    return BranchResult(status="success",
                        summary=f"reasoning step completed: {task[:160]}",
                        evidence=[])


TOOLS: dict[str, Callable[[str, ToolContext], BranchResult]] = {
    "sql": run_sql,
    "search": run_search,
    "none": run_none,
}


def execute(tool: str, task: str, ctx: ToolContext) -> BranchResult:
    fn = TOOLS.get(tool)
    if fn is None:
        raise ToolError(f"unknown tool {tool!r}")
    try:
        return fn(task, ctx)
    except ToolError:
        raise
    except Exception as exc:  # tool crashes become branch errors, not run crashes
        return BranchResult(status="error", summary=f"{type(exc).__name__}: {exc}",
                            error=str(exc))
