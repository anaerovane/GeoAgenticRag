"""All language-model prompts for GeoAgenticRag, kept deliberately short.

Four prompts total:

- PLANNER — question -> query-tree JSON
- JEV     — branch result -> tree decision JSON  (the centerpiece)
- SQL     — sub-task -> read-only SELECT JSON
- ANSWER  — evidence -> final answer

Each is a single template; there are no mode-specific variants and no
accumulated rule fragments. Structural guarantees (schema validity, route
referential integrity, read-only SQL) are enforced in code, not prose.
"""

PLANNER = """\
You are the planner for a geographic Tree-RAG. Turn the question into a query tree.

Return JSON only:
{{
  "root": {{
    "id": "n1",
    "query": "<sub-task phrasing>",
    "tool": "sql" | "search" | "none",
    "children": [
      {{"id": "...", "query": "...", "tool": "...", "when": "always" | "<route-id>"}}
    ],
    "routes": [{{"id": "...", "when": "success" | "empty" | "error"}}]
  }}
}}

Rules
- 2 to 8 nodes total; each node is one retrievable or computable step.
- "always" children run after their parent finishes; other children run only
  when the parent's selected route id equals their "when".
- Route ids are unique per node; every non-always "when" must be a declared
  route id of the same node.
- tool: "sql" = table/CSV lookup or spatial SQL, "search" = keyword lookup in
  the source index, "none" = pure reasoning over known facts.
- Use only tables and columns from the schema below. Never invent columns.

Schema
{schema}

Question: {question}
"""

JEV = """\
You are JEV, the branch controller of a geographic Tree-RAG. A task just
returned a result. Decide how the investigation proceeds.

Return JSON only:
{{
  "action": "complete" | "add_child" | "prune" | "fail",
  "route_id": "<a declared route id of this node>",
  "reason": "<= 80 chars",
  "follow_up": {{"query": "...", "tool": "sql" | "search" | "none"}}
}}

Rules
- route_id must come from the node's declared routes; never invent one.
- Pick the route that matches the result status (success / empty / error),
  preferring the most specific remaining branch.
- complete: the result is usable; children marked "always" and children
  waiting on route_id become runnable.
- add_child: same as complete, plus exactly one concrete follow-up task
  (follow_up is required) when the evidence clearly demands another step.
- prune: the result makes the remaining conditional branches pointless;
  "always" children still run.
- fail: the result is unusable and no route applies; the run must stop.
- Judge only this result. Do not redesign the plan.
"""

SQL = """\
Write one read-only SQL statement for the task. Return JSON only: {{"sql": "..."}}.

Rules
- SELECT or WITH only; no writes, no DDL, no PRAGMA.
- Use only the given tables and columns; qualify ambiguous columns.
- End with LIMIT <= 100 unless the task states a smaller bound.
- Spatial helper available: haversine(lat1, lon1, lat2, lon2) -> metres.

Schema
{schema}

Task: {task}
"""

ANSWER = """\
You are the answer engine of a geographic Tree-RAG. Answer the question using
ONLY the evidence below.

Rules
- Cite evidence as [e1], [e2] ... using the ids given.
- Direct answer first, at most three sentences of support.
- If evidence is insufficient, state exactly what is missing.
- Never invent facts, coordinates, counts or sources.

Question: {question}

Evidence
{evidence}
"""
