"""GeoSPARQL query layer over the ontology-materialized RDF graph.

A branch whose tool is ``geosparql`` binds exactly one verified RDF graph
(manifest with graph IRI, source hashes, predicate schema, geometry CRS),
compiles a JSON **query spec** — the model never writes raw SPARQL — and
executes SELECT/ASK under the GEOF function allowlist.

Two engines, chosen by the manifest:

- ``rdflib``      — in-process execution (default): the graph file plus
  GEOF functions implemented on shapely (sfWithin, sfIntersects, distance ...).
- ``jena-fuseki`` — the same SPARQL posted to an Apache Jena GeoSPARQL
  Fuseki endpoint (what the research pipeline runs at scale).

The manifest keeps geometry honesty the same way the ontology keeps axiom
honesty: spatial functions stay disabled until ``geometry_crs`` is verified,
and every result echoes its provenance.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GEOF = "http://www.opengis.net/def/function/geosparql/"
GEO = "http://www.opengis.net/ont/geosparql#"

# Function allowlist — anything else is rejected before execution.
FUNCTIONS = {
    "sfWithin", "sfContains", "sfIntersects", "sfDisjoint", "sfEquals",
    "sfTouches", "sfOverlaps", "sfCrosses", "distance", "getSRID",
    "isEmpty", "isSimple",
}
# The compiled spec only ever emits these; the allowlist guards hand-written
# queries too.
_BLOCKED = re.compile(
    r"\b(GRAPH|SERVICE|FROM|INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|MOVE|COPY|ADD)\b",
    re.IGNORECASE)
_FUNCTION_CALL = re.compile(r"<([^>]+)>\s*\(")
_TERM = re.compile(r"[?\"'<]([a-zA-Z][a-zA-Z0-9_]*:)?")


class GeoSPARQLError(ValueError):
    """Query, binding or geometry is not allowed or not grounded."""


@dataclass
class Manifest:
    graph_iri: str
    engine: str = "rdflib"
    status: str = "loaded"
    sources: list[dict[str, Any]] = field(default_factory=list)
    predicate_schema: dict[str, str] = field(default_factory=dict)
    geometry_crs: str | None = None
    geometry_columns: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    graph_file: str | None = None
    endpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_iri": self.graph_iri, "engine": self.engine,
            "status": self.status, "sources": self.sources,
            "predicate_schema": self.predicate_schema,
            "geometry_crs": self.geometry_crs,
            "geometry_columns": self.geometry_columns,
            "limitations": self.limitations,
            "graph_file": self.graph_file, "endpoint": self.endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        return cls(
            graph_iri=str(data["graph_iri"]),
            engine=str(data.get("engine", "rdflib")),
            status=str(data.get("status", "")),
            sources=list(data.get("sources", [])),
            predicate_schema=dict(data.get("predicate_schema", {})),
            geometry_crs=data.get("geometry_crs"),
            geometry_columns=list(data.get("geometry_columns", [])),
            limitations=list(data.get("limitations", [])),
            graph_file=data.get("graph_file"),
            endpoint=data.get("endpoint"),
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path, expected_sources: list[Path] | None = None) -> Manifest:
    """Load a manifest and verify it is a single loaded, drift-free graph."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest = Manifest.from_dict(data)
    if manifest.status != "loaded":
        raise GeoSPARQLError(f"graph status is {manifest.status!r}, not 'loaded'")
    if not manifest.graph_iri:
        raise GeoSPARQLError("manifest missing graph_iri")
    if manifest.engine not in {"rdflib", "jena-fuseki"}:
        raise GeoSPARQLError(f"unknown engine {manifest.engine!r}")
    if manifest.engine == "rdflib" and not manifest.graph_file:
        raise GeoSPARQLError("rdflib engine requires graph_file")
    if manifest.engine == "jena-fuseki" and not manifest.endpoint:
        raise GeoSPARQLError("jena-fuseki engine requires endpoint")
    if not manifest.sources:
        raise GeoSPARQLError("manifest declares no sources")
    for source in manifest.sources:
        src = Path(source["path"])
        if not src.exists():
            raise GeoSPARQLError(f"source missing: {src}")
        if _sha256(src) != source.get("sha256"):
            raise GeoSPARQLError(f"source drift: {src}")
    if expected_sources is not None:
        declared = {str(Path(s["path"])) for s in manifest.sources}
        wanted = {str(p) for p in expected_sources}
        if declared != wanted:
            raise GeoSPARQLError("manifest sources do not match the bound pointers")
    return manifest


# --------------------------------------------------------------------------
# Materialization: dataset rows + ontology mapping -> one RDF graph
# --------------------------------------------------------------------------

def materialize(tables: list[dict[str, Any]], rows_by_table: dict[str, list[tuple]],
                mapping: "Any", out_dir: Path, graph_iri: str,
                source_files: list[Path] | None = None) -> Manifest:
    """Map tables into an RDF graph driven by the ontology field mappings.

    ``mapping`` is a jevrag.ontology.SourceMapping. Every column value is
    asserted twice: as its standard term (rdfs:label, wgs84:lat, rdf:type ...)
    and as provenance under ``urn:ioc:column:<name>``. Category values map to
    ontology class IRIs when a grounded domain_category claims them.
    """
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, XSD

    from .ontology import PROPERTIES, source_hash_for

    out_dir.mkdir(parents=True, exist_ok=True)
    hash_ = source_hash_for({"name": graph_iri})
    ont = Namespace(f"urn:ioc:ontology:{hash_}:")
    vocab = Namespace("urn:ioc:vocab:")
    col_ns = Namespace("urn:ioc:column:")
    row_ns = Namespace("urn:ioc:row:")
    wkt = URIRef(GEO + "asWKT")
    has_geom = URIRef(GEO + "hasGeometry")

    # Grounded category values -> ontology class IRIs.
    class_for_value: dict[tuple[str, str], URIRef] = {}
    for concept in mapping.domain.concepts:
        if concept.kind == "domain_category":
            for item in concept.evidence.values:
                class_for_value[(str(item.get("column")), str(item.get("value")))] = \
                    ont[f"class/{concept.id}"]

    graph = Graph()
    predicates_used: dict[str, str] = {}
    geometry_columns = {fm.column for fm in mapping.field_mappings
                        if fm.term == "geo:hasGeometry"}
    lon_lat: dict[str, str] = {}
    for fm in mapping.field_mappings:
        if fm.role == "longitude":
            lon_lat["lon"] = fm.column
        elif fm.role == "latitude":
            lon_lat["lat"] = fm.column
    verified_crs = mapping.category_binding is not None and any(
        "crs_confirmation" in fm.requires and fm.role in {"latitude", "longitude"}
        for fm in mapping.field_mappings) and bool(lon_lat)

    for table in tables:
        name = table["name"]
        columns = [c["name"] for c in table["columns"]]
        col_index = {c: i for i, c in enumerate(columns)}
        for row_no, row in enumerate(rows_by_table.get(name, [])):
            subject = row_ns[f"{name}:{row_no}"]
            graph.add((subject, RDF.type, URIRef(f"urn:ioc:record:{name}")))
            for fm in mapping.field_mappings:
                if fm.column not in col_index:
                    continue
                value = row[col_index[fm.column]]
                if value in (None, ""):
                    continue
                lexical = str(value)
                graph.add((subject, col_ns[fm.column], Literal(lexical)))
                term = fm.term
                if term == "none":
                    continue
                pred = PROPERTIES.get(term) or URIRef(
                    "http://purl.org/dc/terms/identifier"
                    if term == "dcterms:identifier" else
                    "http://www.w3.org/2004/02/skos/core#prefLabel"
                    if term == "skos:prefLabel" else term)
                pred = URIRef(str(pred))
                predicates_used[term] = str(pred)
                if fm.role in {"latitude", "longitude"}:
                    graph.add((subject, pred,
                               Literal(lexical, datatype=XSD.double)))
                elif fm.role == "category":
                    target = class_for_value.get((fm.column, lexical),
                                                 vocab[_slug(lexical)])
                    graph.add((subject, RDF.type, target))
                    graph.add((subject, pred, target))
                else:
                    graph.add((subject, pred, Literal(lexical)))
            if verified_crs and set(lon_lat.values()) <= set(col_index):
                lon = row[col_index[lon_lat["lon"]]]
                lat = row[col_index[lon_lat["lat"]]]
                if lon not in (None, "") and lat not in (None, ""):
                    geom = ont[f"geom/{name}:{row_no}"]
                    graph.add((subject, has_geom, geom))
                    graph.add((geom, wkt,
                               Literal(f"POINT({lon} {lat})",
                                       datatype=URIRef(GEO + "wktLiteral"))))
                    predicates_used["geo:hasGeometry"] = str(has_geom)

    graph_file = out_dir / "graph.ttl"
    graph.serialize(destination=str(graph_file), format="turtle")
    source_records = [{"path": str(p), "sha256": _sha256(p),
                       "rows": None} for p in (source_files or [])]
    if not source_records:
        source_records = [{"path": str(graph_file), "sha256": _sha256(graph_file),
                           "rows": sum(len(v) for v in rows_by_table.values())}]
    manifest = Manifest(
        graph_iri=graph_iri, engine="rdflib", status="loaded",
        sources=source_records,
        predicate_schema={term: pred for term, pred in predicates_used.items()},
        geometry_crs="CRS84" if verified_crs else None,
        geometry_columns=["geo:asWKT"] if verified_crs else [],
        limitations=[] if verified_crs else
        ["geometry_crs unverified: spatial functions disabled"],
        graph_file=str(graph_file),
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return manifest


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower() or "value"


# --------------------------------------------------------------------------
# Query spec -> SPARQL (the model never writes SPARQL)
# --------------------------------------------------------------------------

_PREFIX = f"PREFIX geof: <{GEOF}>\nPREFIX geo: <{GEO}>\n" \
          "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" \
          "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n" \
          "PREFIX wgs84: <http://www.w3.org/2003/01/geo/wgs84_pos#>\n"


def _term_token(raw: str) -> str:
    raw = str(raw)
    if raw.startswith("http://") or raw.startswith("urn:"):
        return f"<{raw}>"
    if raw.startswith("?"):
        raise GeoSPARQLError("variables are not allowed in filters")
    return json.dumps(raw)


def compile_spec(spec: dict[str, Any], manifest: Manifest) -> str:
    """Compile a JSON query spec into allowlisted SELECT/ASK SPARQL."""
    op = str(spec.get("operation", "")).lower()
    if op == "unsupported":
        raise GeoSPARQLError(str(spec.get("reason", "unsupported operation")))
    known = set(manifest.predicate_schema)
    for key in ("filters", "reference_filters"):
        for f in spec.get(key, []) or []:
            pred = str(f.get("predicate", ""))
            if pred not in known and pred not in {"rdf:type"}:
                raise GeoSPARQLError(f"predicate not observed in this graph: {pred!r}")

    def triples(var: str, filters: list[dict[str, Any]]) -> str:
        out = []
        for f in filters or []:
            pred = str(f.get("predicate", ""))
            iri = manifest.predicate_schema.get(pred, pred if pred.startswith("http")
                                                else "")
            if pred == "rdf:type":
                iri = "rdf:type"
            if not iri:
                raise GeoSPARQLError(f"cannot resolve predicate {pred!r}")
            out.append(f"  {var} <{iri}> {_term_token(f.get('value', ''))} ."
                       if iri.startswith("http") else
                       f"  {var} {iri} {_term_token(f.get('value', ''))} .")
        return "\n".join(out)

    if op == "select":
        preds = spec.get("select_predicates") or sorted(known)
        for p in preds:
            if p not in known:
                raise GeoSPARQLError(f"unknown select predicate {p!r}")
        values = " ".join(f"<{manifest.predicate_schema[p]}>" for p in preds)
        body = f"?s ?p ?o . FILTER(?p IN ({values}))\n{triples('?s', spec.get('filters'))}"
        return _PREFIX + f"SELECT ?s ?p ?o WHERE {{\n{body}\n}} LIMIT 200"
    if op == "ask":
        body = triples("?s", spec.get("filters"))
        return _PREFIX + f"ASK WHERE {{\n{body}\n}}"
    if op in {"within", "intersects"}:
        if not manifest.geometry_crs:
            raise GeoSPARQLError("spatial operation requires a verified geometry_crs")
        fn = "sfWithin" if op == "within" else "sfIntersects"
        ref = triples("?ref", spec.get("reference_filters"))
        sel = triples("?s", spec.get("filters"))
        return _PREFIX + (
            f"SELECT ?s WHERE {{\n{sel}\n{ref}\n"
            f"  ?s geo:hasGeometry ?sg . ?sg geo:asWKT ?g .\n"
            f"  ?ref geo:hasGeometry ?rgn . ?rgn geo:asWKT ?rg .\n"
            f"  FILTER(geof:{fn}(?g, ?rg))\n}} LIMIT 200")
    if op == "distance":
        if not manifest.geometry_crs:
            raise GeoSPARQLError("distance requires a verified geometry_crs")
        radius = float(spec.get("radius_metres", 0))
        if radius <= 0:
            raise GeoSPARQLError("distance requires a positive radius_metres")
        ref = triples("?ref", spec.get("reference_filters"))
        sel = triples("?s", spec.get("filters"))
        exclude = "  FILTER(?s != ?ref)\n" if spec.get("exclude_reference") else ""
        return _PREFIX + (
            f"SELECT ?s ?d WHERE {{\n{sel}\n{ref}\n"
            f"  ?s geo:hasGeometry ?sg . ?sg geo:asWKT ?g .\n"
            f"  ?ref geo:hasGeometry ?rgn . ?rgn geo:asWKT ?rg .\n"
            f"{exclude}"
            f"  BIND(geof:distance(?g, ?rg) AS ?d)\n"
            f"  FILTER(?d <= {radius})\n}} ORDER BY ?d LIMIT 200")
    raise GeoSPARQLError(f"unknown operation {op!r}")


def guard_query(sparql: str) -> None:
    """Reject anything outside SELECT/ASK with the GEOF allowlist."""
    stripped = re.sub(r"#[^\n]*", "", sparql).strip()
    if not (stripped.upper().startswith(("SELECT", "ASK", "PREFIX"))):
        raise GeoSPARQLError("only SELECT/ASK queries are allowed")
    if re.match(r"(?is)^\s*(PREFIX\s+\S+\s+<[^>]+>\s*)*(INSERT|DELETE|LOAD|CLEAR|"
                r"CREATE|DROP|MOVE|COPY|ADD)\b", stripped):
        raise GeoSPARQLError("update operations are not allowed")
    for keyword in ("GRAPH", "SERVICE", " FROM "):
        if re.search(rf"(?i)\b{keyword.strip()}\b", stripped):
            raise GeoSPARQLError(f"{keyword.strip()} is not allowed")
    for match in _FUNCTION_CALL.finditer(stripped):
        iri = match.group(1)
        if iri.startswith(GEOF):
            name = iri[len(GEOF):]
            if name not in FUNCTIONS:
                raise GeoSPARQLError(f"function not allowed: {name}")
        elif iri.startswith("http://www.w3.org/2001/XMLSchema#"):
            continue
        else:
            raise GeoSPARQLError(f"extension function not allowed: {iri}")

# --------------------------------------------------------------------------
# Execution engines
# --------------------------------------------------------------------------

_GEOM_CACHE: dict[str, Any] = {}


def _geom(lexical: str):
    from shapely import wkt as shapely_wkt
    if lexical not in _GEOM_CACHE:
        _GEOM_CACHE[lexical] = shapely_wkt.loads(lexical)
    return _GEOM_CACHE[lexical]


def _register_geof(geometry_crs: str | None) -> None:
    """Register GEOF functions on rdflib (idempotent)."""
    from rdflib import Literal, URIRef
    from rdflib.plugins.sparql.operators import register_custom_function

    def _two(name):
        def call(a, b):
            return Literal(getattr(_geom(str(a)), name)(_geom(str(b))))
        return call

    def distance(a, b):
        import math
        ga, gb = _geom(str(a)), _geom(str(b))
        # Equirectangular metre approximation on the lon/lat sphere.
        lat0 = math.radians((ga.centroid.y + gb.centroid.y) / 2.0)
        dx = (ga.centroid.x - gb.centroid.x) * 111_320.0 * math.cos(lat0)
        dy = (ga.centroid.y - gb.centroid.y) * 110_540.0
        planar = ((dx * dx + dy * dy) ** 0.5
                  if ga.geom_type == "Point" and gb.geom_type == "Point"
                  else ga.distance(gb) * 111_320.0)
        return Literal(round(planar, 3))

    def is_empty(a):
        return Literal(_geom(str(a)).is_empty)

    def is_simple(a):
        return Literal(_geom(str(a)).is_simple)

    def get_srid(a):
        return Literal(4326 if geometry_crs else 0)

    registry = {
        "sfWithin": _two("within"), "sfContains": _two("contains"),
        "sfIntersects": _two("intersects"), "sfDisjoint": _two("disjoint"),
        "sfEquals": _two("equals"), "sfTouches": _two("touches"),
        "sfOverlaps": _two("overlaps"), "sfCrosses": _two("crosses"),
        "distance": distance, "isEmpty": is_empty, "isSimple": is_simple,
        "getSRID": get_srid,
    }
    for name, func in registry.items():
        try:
            register_custom_function(URIRef(GEOF + name), func, override=True)
        except TypeError:  # already registered with same signature
            pass


def execute(sparql: str, manifest: Manifest, max_rows: int = 200) -> dict[str, Any]:
    """Run allowlisted SELECT/ASK and return rows plus provenance."""
    guard_query(sparql)
    provenance = {
        "sparql": sparql, "graph_iri": manifest.graph_iri,
        "engine": manifest.engine, "sources": manifest.sources,
        "geometry_crs": manifest.geometry_crs,
        "limitations": manifest.limitations,
    }
    if manifest.engine == "jena-fuseki":
        return _execute_http(sparql, manifest, provenance, max_rows)

    from rdflib import Graph
    _register_geof(manifest.geometry_crs)
    graph = Graph()
    if manifest.graph_file:
        graph.parse(manifest.graph_file, format="turtle")
    result = graph.query(sparql)
    if result.type == "ASK":
        return {"status": "completed" if bool(result.askAnswer) else "no_match",
                "rows": [], "row_count": 0,
                "sparql_result": {"type": "ask", "value": bool(result.askAnswer)},
                **provenance}
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(result):
        if i >= max_rows:
            raise GeoSPARQLError(f"row limit exceeded ({max_rows})")
        rows.append({str(v): str(row[v]) for v in result.vars if row[v] is not None})
    status = "completed" if rows else "no_match"
    return {"status": status, "rows": rows, "row_count": len(rows),
            "sparql_result": {"type": "select"}, **provenance}


def _execute_http(sparql: str, manifest: Manifest, provenance: dict[str, Any],
                  max_rows: int) -> dict[str, Any]:
    import httpx
    try:
        response = httpx.post(
            str(manifest.endpoint),
            data={"query": sparql, "default-graph-uri": manifest.graph_iri},
            headers={"Accept": "application/sparql-results+json"},
            timeout=30.0)
        if response.status_code >= 500:
            response = httpx.post(
                str(manifest.endpoint),
                data={"query": sparql, "default-graph-uri": manifest.graph_iri},
                headers={"Accept": "application/sparql-results+json"},
                timeout=30.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 — surface engine errors verbatim
        raise GeoSPARQLError(f"endpoint error: {exc}") from exc
    if payload.get("boolean") is not None:
        return {"status": "completed" if payload["boolean"] else "no_match",
                "rows": [], "row_count": 0,
                "sparql_result": {"type": "ask", "value": bool(payload["boolean"])},
                **provenance}
    bindings = payload.get("results", {}).get("bindings", [])
    if len(bindings) > max_rows:
        raise GeoSPARQLError(f"row limit exceeded ({max_rows})")
    rows = [{k: v.get("value") for k, v in b.items()} for b in bindings]
    return {"status": "completed" if rows else "no_match", "rows": rows,
            "row_count": len(rows), "sparql_result": {"type": "select"},
            **provenance}


# --------------------------------------------------------------------------
# Branch entry point
# --------------------------------------------------------------------------

_RADIUS = re.compile(r"(\d+(?:\.\d+)?)\s*(m|metre|meter|km)\b", re.IGNORECASE)


def run(task: str, llm: Any, manifest: Manifest) -> dict[str, Any]:
    """LLM -> query spec -> SPARQL -> rows, as one branch result."""
    import json as _json

    from . import prompts
    user = _json.dumps({
        "task": task,
        "predicate_schema": manifest.predicate_schema,
        "geometry_crs": manifest.geometry_crs,
        "limitations": manifest.limitations,
    }, ensure_ascii=False)
    raw = llm.chat(prompts.GEOSPARQL, user)
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        spec = _json.loads(text)
    except _json.JSONDecodeError as exc:
        return {"tool_used": "geosparql", "status": "no_match",
                "summary": f"geosparql: query spec is not JSON: {exc}",
                "conclusion": None, "data": {},
                "evidence_gaps": [str(exc)], "pointers": []}
    if spec.get("operation") == "distance":
        match = _RADIUS.search(task)
        if match and not spec.get("radius_metres"):
            scale = 1000.0 if match.group(2).lower() == "km" else 1.0
            spec["radius_metres"] = float(match.group(1)) * scale
    try:
        sparql = compile_spec(spec, manifest)
        outcome = execute(sparql, manifest)
    except GeoSPARQLError as exc:
        return {"tool_used": "geosparql", "status": "no_match",
                "summary": f"geosparql: {exc}",
                "conclusion": None, "data": {"query_spec": spec},
                "evidence_gaps": [str(exc)], "pointers": []}
    conclusion = None
    if outcome["status"] == "completed" and outcome["rows"]:
        first = outcome["rows"][0]
        conclusion = "; ".join(f"{k}={v}" for k, v in list(first.items())[:4])
    return {
        "tool_used": "geosparql",
        "status": outcome["status"],
        "summary": (f"{outcome['row_count']} rows via {outcome['engine']}"
                    if outcome["status"] == "completed" else "no matching triples"),
        "conclusion": conclusion,
        "data": {"query_spec": spec, **outcome},
        "evidence_gaps": [], "pointers": [],
    }
