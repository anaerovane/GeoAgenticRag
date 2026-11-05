"""Source index: BM25 keyword retrieval over dataset descriptions.

The index describes *sources* (tables, columns, categories), not raw rows —
it answers "where should I look", while the sql tool answers "what is the
value". Pure-Python BM25 keeps the dependency surface small; an optional
cross-encoder endpoint can rerank the fused candidates.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass(slots=True)
class Doc:
    id: str
    title: str
    description: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "description": self.description,
                "meta": self.meta}


class SourceIndex:
    """In-memory BM25 index over Doc records, persistable as JSON."""

    def __init__(self, docs: list[Doc] | None = None, *, k1: float = 1.5,
                 b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[Doc] = docs or []
        self._postings: dict[str, list[tuple[int, int]]] = {}
        self._doc_len: list[int] = []
        self._avg_len = 0.0
        self._build()

    # -- indexing ----------------------------------------------------------
    def _build(self) -> None:
        self._postings = {}
        self._doc_len = []
        for idx, doc in enumerate(self.docs):
            tokens = _tokenize(f"{doc.title} {doc.description}")
            self._doc_len.append(len(tokens))
            for token, count in Counter(tokens).items():
                self._postings.setdefault(token, []).append((idx, count))
        self._avg_len = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0

    def add(self, doc: Doc) -> None:
        self.docs.append(doc)
        self._build()

    @property
    def size(self) -> int:
        return len(self.docs)

    # -- search ------------------------------------------------------------
    def search(self, query: str, k: int = 8) -> list[dict[str, Any]]:
        if not self.docs:
            return []
        tokens = _tokenize(query)
        n = len(self.docs)
        scores = [0.0] * n
        for token in tokens:
            postings = self._postings.get(token)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for idx, tf in postings:
                dl = self._doc_len[idx] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                scores[idx] += idf * tf * (self.k1 + 1) / denom
        ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
        hits = []
        for idx in ranked[:k]:
            if scores[idx] <= 0:
                break
            doc = self.docs[idx]
            hits.append({"doc": doc.to_dict(), "score": round(scores[idx], 4)})
        return hits

    def rerank(self, query: str, hits: list[dict[str, Any]],
               rerank_url: str) -> list[dict[str, Any]]:
        """Optional cross-encoder rerank via POST {rerank_url} {query, texts}."""
        if not rerank_url or not hits:
            return hits
        import httpx

        texts = [f"{h['doc']['title']} {h['doc']['description']}" for h in hits]
        try:
            response = httpx.post(rerank_url, json={"query": query, "texts": texts},
                                  timeout=30.0)
            response.raise_for_status()
            scores = response.json()["scores"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return hits  # rerank is best-effort; BM25 order stands
        for hit, score in zip(hits, scores):
            hit["score"] = round(float(score), 4)
        return sorted(hits, key=lambda h: h["score"], reverse=True)

    # -- persistence -------------------------------------------------------
    def save(self, path: str | Path) -> None:
        payload = {"docs": [d.to_dict() for d in self.docs]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "SourceIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        docs = [Doc(id=d["id"], title=d["title"], description=d["description"],
                    meta=d.get("meta", {})) for d in payload["docs"]]
        return cls(docs)


def index_from_tables(tables: list[dict[str, Any]]) -> SourceIndex:
    """Build description docs from registered table profiles.

    Emits one doc per table and one per column; category-valued columns also
    get a doc per observed value. This is what the search tool queries.
    """
    docs: list[Doc] = []
    for table in tables:
        name = table.get("name", "data")
        docs.append(Doc(
            id=f"table:{name}",
            title=name,
            description=f"Table {name} with {len(table.get('columns', []))} columns. "
                        + table.get("description", ""),
            meta={"kind": "table", "table": name},
        ))
        for col in table.get("columns", []):
            col_name = col.get("name", "?")
            docs.append(Doc(
                id=f"column:{name}.{col_name}",
                title=f"{name}.{col_name}",
                description=(f"Column {col_name} ({col.get('type', 'text')}) of {name}. "
                             + str(col.get("description", ""))),
                meta={"kind": "column", "table": name, "column": col_name},
            ))
            values = col.get("values") or []
            if 0 < len(values) <= 40:
                docs.append(Doc(
                    id=f"values:{name}.{col_name}",
                    title=f"{col_name} values",
                    description=f"Observed values of {name}.{col_name}: "
                                + ", ".join(str(v) for v in values[:30]),
                    meta={"kind": "values", "table": name, "column": col_name},
                ))
    return SourceIndex(docs)
