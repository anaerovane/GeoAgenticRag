"""Minimal OpenAI-compatible chat client plus a deterministic mock.

`LLMClient.chat()` is the only way any prompt reaches a model. Structured
outputs are requested with a JSON schema when the endpoint supports it; the
fallback path extracts the first JSON object from the reply. Mock mode never
opens a socket, which is what makes the test suite and the offline demo work.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any

import httpx

from .config import Settings

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class LLMError(RuntimeError):
    """A provider call failed or returned unparseable output."""


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": json_schema},
            }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.model}: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{self.model}: malformed response {body!r:.200}") from exc
        if not content:
            raise LLMError(f"{self.model}: empty completion")
        return content


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply, tolerating fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(stripped)
        if not match:
            raise LLMError(f"no JSON object in reply: {text[:160]!r}") from None
        return json.loads(match.group(0))


class MockLLM:
    """Deterministic stand-in used when JEVRAG_MOCK=1.

    Produces a valid plan, valid JEV decisions, trivial SQL and an extractive
    answer so the whole pipeline runs end-to-end with no providers.
    """

    model = "mock"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        with self._lock:
            self.calls.append((system, user))
        blob = system + "\n" + user
        if system.startswith("You are the planner"):
            return json.dumps(self._plan(system))
        if system.startswith("You are JEV"):
            return json.dumps(
                {
                    "action": "complete",
                    "route_id": self._route_for(blob),
                    "reason": "result matches a declared route",
                }
            )
        if system.startswith("Write one read-only SQL"):
            return json.dumps({"sql": self._sql(system)})
        if system.startswith("You are the answer engine"):
            return self._answer(blob)
        if system.startswith("You are the GeoSPARQL planner"):
            return json.dumps(self._geosparql(user))
        if system.startswith("You are the ontology architect"):
            return self._ontology(system)
        return "{}"

    @staticmethod
    def _route_for(user: str) -> str:
        match = re.search(r'"status":\s*"(success|empty|error)"', user)
        status = match.group(1) if match else "success"
        # Routes arrive as {"id": ..., "when": ...} pairs in the payload.
        pairs = re.findall(r'\{\s*"id":\s*"([^"]+)"\s*,\s*"when":\s*"([^"]+)"\s*\}', user)
        if not pairs:
            # Fall back to planner-style {"when": ..., "id": ...} (reversed keys).
            reversed_pairs = re.findall(
                r'\{\s*"when":\s*"([^"]+)"\s*,\s*"id":\s*"([^"]+)"\s*\}', user)
            pairs = [(b, a) for a, b in reversed_pairs]
        for route_id, when in pairs:
            if when == status:
                return route_id
        return pairs[0][0] if pairs else "r_ok"

    @staticmethod
    def _plan(system: str) -> dict[str, Any]:
        question = system.rsplit("Question:", 1)[-1].strip() if "Question:" in system \
            else "question"
        routes = [{"id": "r_ok", "when": "success"}, {"id": "r_empty", "when": "empty"}]
        return {
            "root": {
                "id": "n1",
                "query": question,
                "tool": "sql",
                "children": [
                    {"id": "n2", "query": "summarize findings for: " + question,
                     "tool": "none", "when": "always", "routes": routes}
                ],
                "routes": routes,
            }
        }

    @staticmethod
    def _sql(system: str) -> str:
        # schema_summary emits lines like: city_poi(name:text, district:text, ...)
        match = re.search(r"^([A-Za-z_][A-Za-z0-9_]*)\(", system, re.M)
        table = match.group(1) if match else "data"
        return f'SELECT * FROM "{table}" LIMIT 20'

    @staticmethod
    def _geosparql(user: str) -> dict[str, Any]:
        try:
            payload = json.loads(user)
        except json.JSONDecodeError:
            payload = {}
        schema = payload.get("predicate_schema") or {}
        preds = sorted(schema)[:3]
        if not preds:
            return {"operation": "unsupported", "reason": "empty predicate schema"}
        return {"operation": "select", "select_predicates": preds,
                "filters": [], "reference_filters": [], "radius_metres": 0,
                "exclude_reference": True}

    @staticmethod
    def _ontology(system: str) -> str:
        # Build a minimal grounded mapping from the embedded profile.
        try:
            profile = json.loads(system.split("Profile\n", 1)[1]
                                 .split("\n\nTree paths", 1)[0])
        except (IndexError, json.JSONDecodeError):
            profile = {"columns": [], "sample": []}
        columns = [c["name"] if isinstance(c, dict) else str(c)
                   for c in profile.get("columns", [])]
        label_col = next((c for c in columns
                          if c in {"name", "title", "label"}), columns[0] if columns else "col0")
        mappings = []
        for col in columns:
            if col == label_col:
                mappings.append({"column": col, "role": "label",
                                 "term": "rdfs:label", "basis": "record label"})
            else:
                mappings.append({"column": col, "role": "other",
                                 "term": "none", "basis": "unmapped attribute"})
        evidence = {"basis": "profile columns", "columns": [label_col], "values": []}
        return json.dumps({
            "record_kind": "unknown", "class_alignment": "none",
            "field_mappings": mappings,
            "category_binding": "unavailable", "category_column": None,
            "limitations": ["demo mapping generated by the mock model"],
            "domain_ontology": {
                "coverage": "partial_proposed_domain_model",
                "concepts": [{"id": "c1", "label": "Record",
                              "definition": "One source record of this dataset.",
                              "kind": "source_record", "alignment": "none",
                              "status": "proposed", "evidence": evidence}],
                "hierarchy": [],
                "relations": [{"id": "r1", "label": "label",
                               "definition": "Human readable label of a record.",
                               "domain": "c1", "range": "xsd:string",
                               "property_kind": "datatype",
                               "standard_term": "rdfs:label", "status": "proposed",
                               "requires": [], "evidence": evidence}],
                "field_links": [{"column": label_col, "concept_id": "c1",
                                 "relation_id": "r1"}],
                "description_bindings": [{"tree_path": "root",
                                          "concept_ids": ["c1"],
                                          "relation_ids": ["r1"],
                                          "columns": [label_col]}],
            },
        })

    @staticmethod
    def _answer(user: str) -> str:
        evidence = user.split("Evidence", 1)[-1] if "Evidence" in user else ""
        cites = list(dict.fromkeys(re.findall(r"\[(e\d+)\]", evidence)))
        if not cites:
            return "No evidence was collected."
        joined = " ".join(f"[{c}]" for c in cites[:3])
        first_line = next((ln.strip() for ln in evidence.splitlines()
                           if ln.strip() and not ln.strip().startswith("[[")),
                          "evidence retrieved")
        return f"Based on the retrieved evidence: {first_line[:160]} {joined}"


def make_llm(settings: Settings, role: str) -> LLMClient | MockLLM:
    """Return the client for a role: planner | jev | answer."""
    if settings.mock:
        return MockLLM()
    if role == "jev":
        return LLMClient(settings.jev_base_url, settings.jev_model, settings.jev_api_key,
                         settings.timeout_seconds)
    if role == "answer":
        return LLMClient(settings.answer_base_url, settings.answer_model, settings.planner_api_key,
                         settings.timeout_seconds)
    return LLMClient(settings.planner_base_url, settings.planner_model, settings.planner_api_key,
                     settings.timeout_seconds)
