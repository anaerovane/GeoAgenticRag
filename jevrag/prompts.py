"""All language-model prompts for GeoAgenticRag, kept deliberately short.

Six prompts total:

- PLANNER  — question -> query-tree JSON
- JEV      — branch result -> tree decision JSON  (the centerpiece)
- SQL      — sub-task -> read-only SELECT JSON
- GEOSPARQL — task -> GeoSPARQL query-spec JSON (never raw SPARQL)
- ONTOLOGY — dataset profile -> source mapping + domain ontology JSON
- ANSWER   — evidence -> final answer

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
    "tool": "sql" | "search" | "geosparql" | "none",
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
  the source index, "geosparql" = query the materialized RDF graph, "none" =
  pure reasoning over known facts.
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
- Pick the route matching the result status (success / empty / error).
- complete: result is usable; "always" children and children waiting on
  route_id become runnable.
- add_child: complete, plus one concrete follow_up (required) when the
  evidence clearly demands another step.
- prune: remaining conditional branches are pointless; "always" children
  still run.
- fail: result unusable and no route applies; the run must stop.
- Judge only this result; do not redesign the plan.
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


GEOSPARQL = """\
You are the GeoSPARQL planner of a geographic Tree-RAG. Turn the task into a
query spec over ONE verified RDF graph. Never write SPARQL.

Return JSON only:
{
  "operation": "select" | "ask" | "within" | "intersects" | "distance" | "unsupported",
  "select_predicates": ["<term from the predicate schema>", ...],
  "filters": [{"predicate": "...", "value": "..."}],
  "reference_filters": [{"predicate": "...", "value": "..."}],
  "radius_metres": 0,
  "exclude_reference": true,
  "reason": "<why, when unsupported>"
}

Rules
- Predicates must come from the predicate schema; values must be exact.
- within/intersects/distance need verified geometry_crs and a reference in
  reference_filters; distance tasks set radius_metres and exclude_reference.
- No CRS, no predicate, or task inexpressible -> "unsupported" + reason.
"""

ONTOLOGY = """\
You are the ontology architect of a geographic Tree-RAG. From the dataset
profile below, produce the record alignment and the domain ontology. Axioms
are PROPOSALS grounded in observed evidence, never instance facts.

Return JSON only:
{{
  "record_kind": "spatial_feature" | "concept_vocabulary" | "records" | "unknown",
  "class_alignment": "geo:Feature" | "skos:Concept" | "none",
  "field_mappings": [{{"column": "...", "role": "label" | "latitude" |
    "longitude" | "category" | "identifier" | "other", "term": "<role term>",
    "basis": "...", "requires": ["crs_confirmation", ...]}}],
  "category_binding": "observed_column" | "vocabulary_only" | "unavailable",
  "category_column": "<column or null>",
  "limitations": ["..."],
  "domain_ontology": {{
    "coverage": "partial_proposed_domain_model",
    "concepts": [{{"id": "c1", "label": "...", "definition": "...",
      "kind": "source_record" | "domain_category" | "geometry" | "coverage",
      "alignment": "none" | "geo:Feature" | "geo:Geometry" | "skos:Concept",
      "status": "proposed" | "observed_label",
      "evidence": {{"basis": "...", "columns": ["..."],
                   "values": [{{"column": "...", "value": "..."}}]}}}}],
    "hierarchy": [{{"child": "cN", "parent": "cN" | "geo:Feature" | ...,
                   "status": "proposed", "evidence": {{...}}}}],
    "relations": [{{"id": "r1", "label": "...", "definition": "...",
      "domain": "...", "range": "...", "property_kind": "object" | "datatype",
      "standard_term": "geo:hasGeometry" | "geo:sfWithin" | ... | "none",
      "status": "proposed", "requires": [...], "evidence": {{...}}}}],
    "field_links": [{{"column": "...", "concept_id": "cN", "relation_id": "rN"}}],
    "description_bindings": [{{"tree_path": "root", "concept_ids": ["cN"],
      "relation_ids": ["rN"], "columns": ["..."]}}]
  }}
}}

Rules
- Map EVERY column exactly once. Role terms: label -> rdfs:label or
  skos:prefLabel; latitude -> wgs84:lat; longitude -> wgs84:long; category ->
  rdf:type; identifier -> dcterms:identifier; other -> none.
- Use local ids c1../r1.. only. No row individuals, no owl:sameAs.
- Only a domain_category grounded in an observed category value may be
  observed_label; group such leaves under a proposed abstract parent.
- geo:* relations require crs_confirmation + geometry_materialization
  (+ spatial_evaluation); wgs84:* require crs_confirmation. Prerequisites are
  not proof a geometry exists.
- Evidence cites exact observed values (whole cells only) and real tree paths
  (root, root.0, ...). Keep coverage=partial_proposed_domain_model and state
  limitations (e.g. CRS unverified).

Profile
{profile}

Tree paths
{tree_paths}
"""
