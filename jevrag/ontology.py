"""Ontology framework: record alignment -> domain model -> evidence-grounded
TBox -> TriG export.

Two strictly separated layers:

- proposed  — OWL/RDFS axioms the model *proposes* (classes, hierarchy,
  properties). Never asserted as instance facts.
- evidence  — grounding that justifies each axiom (observed column values,
  description-tree paths, field links).

The domain model is the centerpiece: concepts, hierarchy, relations,
field_links and description_bindings, aligned to OGC GeoSPARQL / SKOS /
RDFS / WGS84 vocabularies. Validation enforces grounding mechanically
(an axiom without observed evidence is rejected), so "proposed" never
drifts into hallucination.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Vocabularies (alignment targets)
# --------------------------------------------------------------------------

STANDARD: dict[str, str | None] = {
    "geo:Feature": "http://www.opengis.net/ont/geosparql#Feature",
    "geo:Geometry": "http://www.opengis.net/ont/geosparql#Geometry",
    "skos:Concept": "http://www.w3.org/2004/02/skos/core#Concept",
    "xsd:string": "http://www.w3.org/2001/XMLSchema#string",
    "xsd:double": "http://www.w3.org/2001/XMLSchema#double",
    "rdfs:Literal": "http://www.w3.org/2000/01/rdf-schema#Literal",
}
STANDARD.update({iri: iri for iri in list(STANDARD.values()) if iri})

PROPERTIES: dict[str, str | None] = {
    "geo:hasGeometry": "http://www.opengis.net/ont/geosparql#hasGeometry",
    "geo:sfWithin": "http://www.opengis.net/ont/geosparql#sfWithin",
    "geo:sfContains": "http://www.opengis.net/ont/geosparql#sfContains",
    "geo:sfIntersects": "http://www.opengis.net/ont/geosparql#sfIntersects",
    "rdfs:label": "http://www.w3.org/2000/01/rdf-schema#label",
    "rdf:type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "wgs84:lat": "http://www.w3.org/2003/01/geo/wgs84_pos#lat",
    "wgs84:long": "http://www.w3.org/2003/01/geo/wgs84_pos#long",
    "none": None,
}

LITERAL_RANGES = {"xsd:string", "xsd:double", "rdfs:Literal"}
CONCEPT_ID = re.compile(r"^c[1-9][0-9]*$")
RELATION_ID = re.compile(r"^r[1-9][0-9]*$")
TREE_PATH = re.compile(r"^root(?:\.[0-9]+)*$")

CONCEPT_KINDS = {"source_record", "domain_category", "geometry", "coverage"}
ALIGNMENTS = {"none", "geo:Feature", "geo:Geometry", "skos:Concept"}
AXIOM_STATUS = {"proposed", "observed_label"}
REQUIREMENTS = {
    "crs_confirmation", "geometry_materialization", "spatial_evaluation",
    "category_evidence", "category_value_to_class_mapping",
    "identity_verification",
}

# Field roles -> allowed standard terms (source alignment layer).
ROLE_TERMS: dict[str, set[str]] = {
    "label": {"rdfs:label", "skos:prefLabel"},
    "latitude": {"wgs84:lat"},
    "longitude": {"wgs84:long"},
    "category": {"rdf:type"},
    "identifier": {"dcterms:identifier"},
    "other": {"none"},
}
RECORD_KINDS = {"spatial_feature", "concept_vocabulary", "records", "unknown"}
CLASS_ALIGNMENTS = {"geo:Feature", "skos:Concept", "none"}
CATEGORY_BINDINGS = {"observed_column", "vocabulary_only", "unavailable"}
ENTITY_NAME_COLUMNS = {"name", "business_name", "candidate_name",
                       "place_name", "label"}


class OntologyError(ValueError):
    """An ontology axiom or mapping is ungrounded or inconsistent."""


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Evidence:
    basis: str
    columns: list[str]
    values: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"basis": self.basis, "columns": self.columns,
                "values": self.values}


@dataclass
class Concept:
    id: str
    label: str
    definition: str
    kind: str
    alignment: str
    status: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label,
                "definition": self.definition, "kind": self.kind,
                "alignment": self.alignment, "status": self.status,
                "evidence": self.evidence.to_dict()}


@dataclass
class HierarchyEdge:
    child: str
    parent: str
    status: str = "proposed"
    evidence: Evidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"child": self.child, "parent": self.parent,
                "status": self.status,
                "evidence": self.evidence.to_dict() if self.evidence else None}


@dataclass
class Relation:
    id: str
    label: str
    definition: str
    domain: str
    range: str
    property_kind: str          # object | datatype
    standard_term: str
    status: str = "proposed"
    requires: list[str] = field(default_factory=list)
    evidence: Evidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label,
                "definition": self.definition, "domain": self.domain,
                "range": self.range, "property_kind": self.property_kind,
                "standard_term": self.standard_term, "status": self.status,
                "requires": self.requires,
                "evidence": self.evidence.to_dict() if self.evidence else None}


@dataclass
class FieldLink:
    column: str
    concept_id: str
    relation_id: str

    def to_dict(self) -> dict[str, str]:
        return {"column": self.column, "concept_id": self.concept_id,
                "relation_id": self.relation_id}


@dataclass
class DescriptionBinding:
    tree_path: str
    concept_ids: list[str]
    relation_ids: list[str]
    columns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"tree_path": self.tree_path, "concept_ids": self.concept_ids,
                "relation_ids": self.relation_ids, "columns": self.columns}


@dataclass
class DomainModel:
    concepts: list[Concept]
    hierarchy: list[HierarchyEdge]
    relations: list[Relation]
    field_links: list[FieldLink]
    description_bindings: list[DescriptionBinding]
    coverage: str = "partial_proposed_domain_model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage,
            "concepts": [c.to_dict() for c in self.concepts],
            "hierarchy": [h.to_dict() for h in self.hierarchy],
            "relations": [r.to_dict() for r in self.relations],
            "field_links": [f.to_dict() for f in self.field_links],
            "description_bindings": [b.to_dict()
                                     for b in self.description_bindings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DomainModel":
        def ev(raw: Any) -> Evidence | None:
            if not raw:
                return None
            return Evidence(basis=str(raw.get("basis", "")),
                            columns=list(raw.get("columns", [])),
                            values=list(raw.get("values", [])))

        return cls(
            coverage=str(data.get("coverage", "partial_proposed_domain_model")),
            concepts=[Concept(
                id=str(c["id"]), label=str(c.get("label", "")),
                definition=str(c.get("definition", "")),
                kind=str(c.get("kind", "")),
                alignment=str(c.get("alignment", "none")),
                status=str(c.get("status", "")),
                evidence=ev(c.get("evidence")) or Evidence("", []),
            ) for c in data.get("concepts", [])],
            hierarchy=[HierarchyEdge(
                child=str(h["child"]), parent=str(h["parent"]),
                status=str(h.get("status", "proposed")),
                evidence=ev(h.get("evidence"))) for h in data.get("hierarchy", [])],
            relations=[Relation(
                id=str(r["id"]), label=str(r.get("label", "")),
                definition=str(r.get("definition", "")),
                domain=str(r.get("domain", "")), range=str(r.get("range", "")),
                property_kind=str(r.get("property_kind", "")),
                standard_term=str(r.get("standard_term", "none")),
                status=str(r.get("status", "proposed")),
                requires=list(r.get("requires", [])),
                evidence=ev(r.get("evidence"))) for r in data.get("relations", [])],
            field_links=[FieldLink(
                column=str(f["column"]), concept_id=str(f["concept_id"]),
                relation_id=str(f["relation_id"]))
                for f in data.get("field_links", [])],
            description_bindings=[DescriptionBinding(
                tree_path=str(b["tree_path"]),
                concept_ids=list(b.get("concept_ids", [])),
                relation_ids=list(b.get("relation_ids", [])),
                columns=list(b.get("columns", [])))
                for b in data.get("description_bindings", [])],
        )


@dataclass
class FieldMapping:
    column: str
    role: str
    term: str
    basis: str
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "role": self.role, "term": self.term,
                "basis": self.basis, "requires": self.requires}


@dataclass
class SourceMapping:
    """Per-dataset record alignment layer that carries the domain model."""
    record_kind: str
    class_alignment: str
    field_mappings: list[FieldMapping]
    category_binding: str
    category_column: str | None
    limitations: list[str]
    domain: DomainModel

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_kind": self.record_kind,
            "class_alignment": self.class_alignment,
            "field_mappings": [f.to_dict() for f in self.field_mappings],
            "category_binding": self.category_binding,
            "category_column": self.category_column,
            "limitations": self.limitations,
            "domain_ontology": self.domain.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceMapping":
        return cls(
            record_kind=str(data.get("record_kind", "")),
            class_alignment=str(data.get("class_alignment", "none")),
            field_mappings=[FieldMapping(
                column=str(f["column"]), role=str(f.get("role", "other")),
                term=str(f.get("term", "none")),
                basis=str(f.get("basis", "")),
                requires=list(f.get("requires", [])))
                for f in data.get("field_mappings", [])],
            category_binding=str(data.get("category_binding", "")),
            category_column=data.get("category_column"),
            limitations=list(data.get("limitations", [])),
            domain=DomainModel.from_dict(data.get("domain_ontology", {})),
        )


# --------------------------------------------------------------------------
# Grounding: observed values from a dataset profile
# --------------------------------------------------------------------------

def observed_values(profile: dict[str, Any]) -> dict[str, set[str]]:
    """Exact observed values per column (never substrings)."""
    observed: dict[str, set[str]] = {}
    for col in profile.get("columns", []):
        name = col["name"] if isinstance(col, dict) else str(col)
        bucket = observed.setdefault(name, set())
        if isinstance(col, dict):
            for key in ("values", "examples"):
                for value in col.get(key, []) or []:
                    if value is not None:
                        bucket.add(str(value))
    for row in profile.get("sample", profile.get("sample_data", [])) or []:
        for name, value in row.items():
            if name in observed and value is not None:
                observed[name].add(str(value))
    return observed


def source_hash_for(profile: dict[str, Any]) -> str:
    key = str(profile.get("name") or profile.get("file") or "dataset")
    return hashlib.sha256(key.casefold().encode("utf-8")).hexdigest()[:8]


# --------------------------------------------------------------------------
# Validation — grounding is mechanical, not advisory
# --------------------------------------------------------------------------

def _check_evidence(evidence: Evidence, columns: dict[str, set[str]],
                    what: str) -> bool:
    """Returns True if evidence cites a category-class value."""
    for col in evidence.columns:
        if col not in columns:
            raise OntologyError(f"{what}: evidence references unknown column {col!r}")
    for item in evidence.values:
        col, value = str(item.get("column", "")), str(item.get("value", ""))
        if col not in columns:
            raise OntologyError(f"{what}: evidence value cites unknown column {col!r}")
        if value not in columns[col]:
            raise OntologyError(
                f"{what}: evidence value not observed in the profile: "
                f"column={col!r}, value={value!r}. Cite the entire cell verbatim.")
    return bool(evidence.values)


def _class_ref_ok(ref: str, concepts: dict[str, Concept]) -> bool:
    return bool(CONCEPT_ID.match(ref)) and ref in concepts \
        or ref in {"geo:Feature", "geo:Geometry", "skos:Concept"}


def validate_domain(domain: DomainModel, profile: dict[str, Any],
                    category_columns: set[str],
                    tree_paths: set[str] | None = None) -> None:
    """Validate the domain model against the observed profile."""
    if domain.coverage != "partial_proposed_domain_model":
        raise OntologyError("coverage must stay 'partial_proposed_domain_model'")
    columns = observed_values(profile)
    concepts = {c.id: c for c in domain.concepts}
    relations = {r.id: r for r in domain.relations}
    if not concepts or not relations:
        raise OntologyError("domain model needs at least one concept and one relation")
    if len(concepts) != len(domain.concepts) or len(relations) != len(domain.relations):
        raise OntologyError("concept and relation ids must be unique")

    parents: set[str] = set()
    for concept in concepts.values():
        if not (CONCEPT_ID.match(concept.id) and concept.label
                and concept.definition):
            raise OntologyError(f"concept {concept.id!r} is incomplete")
        if concept.kind not in CONCEPT_KINDS:
            raise OntologyError(f"concept {concept.id!r}: bad kind {concept.kind!r}")
        if concept.alignment not in ALIGNMENTS:
            raise OntologyError(f"concept {concept.id!r}: bad alignment")
        if concept.status not in AXIOM_STATUS:
            raise OntologyError(f"concept {concept.id!r}: bad status")
        _check_evidence(concept.evidence, columns, f"concept {concept.id}")
        grounded_category = any(
            v.get("column") in category_columns
            for v in concept.evidence.values)
        if concept.status == "observed_label" and (
                concept.kind != "domain_category" or not grounded_category):
            raise OntologyError(
                f"concept {concept.id}: observed_label requires a "
                "domain_category grounded in an observed category value")
        if concept.kind != "domain_category" and concept.status != "proposed":
            raise OntologyError(f"concept {concept.id}: only domain_category "
                                "may use observed_label")
    for edge in domain.hierarchy:
        if edge.evidence:
            _check_evidence(edge.evidence, columns, f"hierarchy {edge.child}")
        if edge.status != "proposed":
            raise OntologyError(f"hierarchy {edge.child}: status must be proposed")
        if edge.child not in concepts:
            raise OntologyError(f"hierarchy references unknown child {edge.child!r}")
        if not _class_ref_ok(edge.parent, concepts):
            raise OntologyError(f"hierarchy references unknown parent {edge.parent!r}")
        parents.add(edge.child)
        parents.add(edge.parent)
    for concept in domain.concepts:
        if (concept.kind == "domain_category" and concept.status == "observed_label"
                and concept.id not in parents):
            raise OntologyError(
                f"concept {concept.id}: a vocabulary-grounded leaf must join "
                "the hierarchy under a proposed abstract parent")
    _check_acyclic(concepts, domain.hierarchy)
    grounded_leaf = any(
        c.kind == "domain_category" and c.id in parents
        and any(v.get("column") in category_columns for v in c.evidence.values)
        for c in concepts.values())
    if category_columns and not grounded_leaf:
        raise OntologyError(
            "observed category vocabulary requires a grounded domain_category "
            "leaf with a proposed subclass edge")

    for rel in domain.relations:
        if not (RELATION_ID.match(rel.id) and rel.label and rel.definition):
            raise OntologyError(f"relation {rel.id!r} is incomplete")
        if rel.status != "proposed":
            raise OntologyError(f"relation {rel.id}: status must be proposed")
        if rel.property_kind not in {"object", "datatype"}:
            raise OntologyError(f"relation {rel.id}: bad property_kind")
        if rel.standard_term not in PROPERTIES:
            raise OntologyError(f"relation {rel.id}: unknown standard_term")
        if set(rel.requires) - REQUIREMENTS:
            raise OntologyError(f"relation {rel.id}: unknown requirement")
        if rel.evidence:
            _check_evidence(rel.evidence, columns, f"relation {rel.id}")
        if not _class_ref_ok(rel.domain, concepts):
            raise OntologyError(f"relation {rel.id}: unknown domain {rel.domain!r}")
        if rel.range in concepts:
            range_ok = rel.property_kind == "object"
        elif rel.range in LITERAL_RANGES:
            range_ok = rel.property_kind == "datatype"
        elif rel.range in {"geo:Feature", "geo:Geometry", "skos:Concept"}:
            range_ok = rel.property_kind == "object"
        else:
            range_ok = False
        if not range_ok:
            raise OntologyError(
                f"relation {rel.id}: range {rel.range!r} disagrees with "
                f"property_kind {rel.property_kind!r}")
        if rel.standard_term in {"rdfs:label", "wgs84:lat", "wgs84:long"} and (
                rel.property_kind != "datatype" or rel.range not in LITERAL_RANGES):
            raise OntologyError(
                f"relation {rel.id}: {rel.standard_term} must be a datatype "
                "property with a literal range")
        if rel.standard_term.startswith("wgs84:") \
                and "crs_confirmation" not in rel.requires:
            raise OntologyError(f"relation {rel.id}: wgs84 terms require "
                                "crs_confirmation")
        if rel.standard_term.startswith("geo:"):
            gates = {"crs_confirmation", "geometry_materialization"}
            if rel.standard_term != "geo:hasGeometry":
                gates.add("spatial_evaluation")
            if not gates <= set(rel.requires):
                raise OntologyError(
                    f"relation {rel.id}: {rel.standard_term} requires {sorted(gates)}")

    for link in domain.field_links:
        if link.column not in columns:
            raise OntologyError(f"field_link references unknown column {link.column!r}")
        if link.concept_id not in concepts:
            raise OntologyError(f"field_link references unknown concept {link.concept_id!r}")
        if link.relation_id not in relations:
            raise OntologyError(f"field_link references unknown relation {link.relation_id!r}")

    seen_paths: set[str] = set()
    for binding in domain.description_bindings:
        if not TREE_PATH.match(binding.tree_path):
            raise OntologyError(f"bad description tree path {binding.tree_path!r}")
        if binding.tree_path in seen_paths:
            raise OntologyError(f"duplicate description binding {binding.tree_path!r}")
        seen_paths.add(binding.tree_path)
        if not set(binding.concept_ids) <= set(concepts):
            raise OntologyError(f"binding {binding.tree_path}: unknown concept id")
        if not set(binding.relation_ids) <= set(relations):
            raise OntologyError(f"binding {binding.tree_path}: unknown relation id")
        if not set(binding.columns) <= set(columns):
            raise OntologyError(f"binding {binding.tree_path}: unknown column")
        if tree_paths is not None and binding.tree_path not in tree_paths:
            raise OntologyError(
                f"binding references nonexistent tree path {binding.tree_path!r}")
    if "root" not in seen_paths:
        raise OntologyError("description bindings must include 'root'")


def _check_acyclic(concepts: dict[str, Concept],
                   hierarchy: list[HierarchyEdge]) -> None:
    adjacency: dict[str, list[str]] = {cid: [] for cid in concepts}
    for edge in hierarchy:
        if edge.parent in concepts:
            adjacency[edge.child].append(edge.parent)
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise OntologyError("domain hierarchy contains a cycle")
        if key in done:
            return
        visiting.add(key)
        for parent in adjacency.get(key, []):
            visit(parent)
        visiting.remove(key)
        done.add(key)

    for key in concepts:
        visit(key)


def validate_source(mapping: SourceMapping, profile: dict[str, Any],
                    tree_paths: set[str] | None = None) -> None:
    """Validate the record-alignment layer, then the embedded domain model."""
    if mapping.record_kind not in RECORD_KINDS:
        raise OntologyError(f"bad record_kind {mapping.record_kind!r}")
    if mapping.class_alignment not in CLASS_ALIGNMENTS:
        raise OntologyError(f"bad class_alignment {mapping.class_alignment!r}")
    if mapping.category_binding not in CATEGORY_BINDINGS:
        raise OntologyError(f"bad category_binding {mapping.category_binding!r}")
    columns = observed_values(profile)
    if set(columns) != {f.column for f in mapping.field_mappings}:
        raise OntologyError("every column must be mapped exactly once")
    seen: set[str] = set()
    for fm in mapping.field_mappings:
        if fm.column in seen:
            raise OntologyError(f"column {fm.column!r} mapped twice")
        seen.add(fm.column)
        if fm.role not in ROLE_TERMS:
            raise OntologyError(f"column {fm.column!r}: bad role {fm.role!r}")
        if fm.term not in ROLE_TERMS[fm.role]:
            raise OntologyError(
                f"column {fm.column!r}: term {fm.term!r} is not allowed for role {fm.role!r}")
        if set(fm.requires) - REQUIREMENTS:
            raise OntologyError(f"column {fm.column!r}: unknown requirement")
        if fm.role == "latitude":
            if "crs_confirmation" not in fm.requires:
                raise OntologyError(f"column {fm.column!r}: latitude requires crs_confirmation")
            partners = [f for f in mapping.field_mappings if f.role == "longitude"]
            if not partners:
                raise OntologyError("latitude requires a paired longitude column")
        if fm.role == "longitude":
            partners = [f for f in mapping.field_mappings if f.role == "latitude"]
            if not partners:
                raise OntologyError("longitude requires a paired latitude column")
        if fm.role == "identifier" and "identity_verification" not in fm.requires:
            raise OntologyError(f"column {fm.column!r}: identifier requires "
                                "identity_verification")
    if mapping.record_kind == "spatial_feature" \
            and mapping.class_alignment != "geo:Feature":
        raise OntologyError("spatial_feature records must align to geo:Feature")
    if mapping.record_kind == "concept_vocabulary" \
            and mapping.class_alignment != "skos:Concept":
        raise OntologyError("concept_vocabulary records must align to skos:Concept")
    if mapping.record_kind == "concept_vocabulary" \
            and mapping.category_binding != "vocabulary_only":
        raise OntologyError("concept_vocabulary records must use vocabulary_only")
    if mapping.category_binding == "observed_column":
        if not mapping.category_column:
            raise OntologyError("observed_column binding needs category_column")
        if mapping.category_column in ENTITY_NAME_COLUMNS:
            raise OntologyError("an entity-name column cannot be the category column")
        categories = {f.column for f in mapping.field_mappings if f.role == "category"}
        if mapping.category_column not in categories:
            raise OntologyError("category_column must carry the category role")
    else:
        if mapping.category_column:
            raise OntologyError("category_column must be empty unless "
                                "binding is observed_column")
        stray = [f.column for f in mapping.field_mappings if f.role == "category"]
        if stray and mapping.category_binding == "unavailable":
            raise OntologyError("category fields present but binding is unavailable")
    if mapping.category_binding == "unavailable" and any(
            c.kind == "domain_category" or c.status == "observed_label"
            for c in mapping.domain.concepts):
        raise OntologyError("unavailable category binding forbids "
                            "domain_category concepts")
    if mapping.category_binding == "vocabulary_only" and any(
            f.role not in {"label", "identifier", "other"}
            for f in mapping.field_mappings):
        raise OntologyError("vocabulary_only binding allows only "
                            "label/identifier/other roles")
    if not mapping.limitations:
        raise OntologyError("declare limitations (e.g. unverified CRS)")
    category_columns = ({mapping.category_column}
                        if mapping.category_binding == "observed_column"
                        else {f.column for f in mapping.field_mappings
                              if f.role == "label"}
                        if mapping.category_binding == "vocabulary_only" else set())
    validate_domain(mapping.domain, profile, category_columns, tree_paths)


# --------------------------------------------------------------------------
# Export: TriG with two named graphs (proposed axioms vs evidence)
# --------------------------------------------------------------------------

def serialize_trig(mapping: SourceMapping, source_hash: str) -> str:
    """Export proposed OWL axioms and their evidence as distinct named graphs."""
    from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
    from rdflib.namespace import OWL, RDF, RDFS

    ns = Namespace(f"urn:ioc:ontology:{source_hash}:")
    dataset = Dataset()
    proposed = dataset.graph(ns["proposed"])
    evidence_g = dataset.graph(ns["evidence"])
    domain = mapping.domain

    proposed.add((ns["model"], RDF.type, OWL.Ontology))
    evidence_g.add((ns["model"], ns["coverage"], Literal(domain.coverage)))
    evidence_g.add((ns["model"], ns["source"], URIRef("urn:sha256:" + source_hash)))

    def resolve(key: str):
        if key in STANDARD and STANDARD[key]:
            return URIRef(str(STANDARD[key]))
        return ns[f"class/{key}"]

    def annotate(subject, item, ev) -> None:
        evidence_g.add((subject, ns["status"], Literal(item.status)))
        if ev is not None:
            evidence_g.add((subject, ns["evidence"],
                            Literal(json.dumps(ev.to_dict(), ensure_ascii=False))))
        evidence_g.add((subject, ns["source"], URIRef("urn:sha256:" + source_hash)))

    for concept in domain.concepts:
        subject = ns[f"class/{concept.id}"]
        proposed.add((subject, RDF.type, OWL.Class))
        proposed.add((subject, RDFS.label, Literal(concept.label)))
        proposed.add((subject, RDFS.comment, Literal(concept.definition)))
        if concept.alignment != "none":
            evidence_g.add((subject, ns["proposedAlignment"],
                            URIRef(str(STANDARD[concept.alignment]))))
        annotate(subject, concept, concept.evidence)

    for i, edge in enumerate(domain.hierarchy):
        child = resolve(edge.child if not CONCEPT_ID.match(edge.child)
                        else edge.child)
        child = ns[f"class/{edge.child}"] if CONCEPT_ID.match(edge.child) else child
        parent = resolve(edge.parent)
        proposed.add((child, RDFS.subClassOf, parent))
        stmt = BNode(f"hierarchy{i}")
        for predicate, value in ((RDF.type, RDF.Statement),
                                 (RDF.subject, child),
                                 (RDF.predicate, RDFS.subClassOf),
                                 (RDF.object, parent)):
            evidence_g.add((stmt, predicate, value))
        annotate(stmt, edge, edge.evidence)

    for rel in domain.relations:
        subject = ns[f"property/{rel.id}"]
        proposed.add((subject, RDF.type,
                      OWL.ObjectProperty if rel.property_kind == "object"
                      else OWL.DatatypeProperty))
        proposed.add((subject, RDFS.label, Literal(rel.label)))
        proposed.add((subject, RDFS.comment, Literal(rel.definition)))
        proposed.add((subject, RDFS.domain, resolve(rel.domain)))
        proposed.add((subject, RDFS.range, resolve(rel.range)))
        if rel.standard_term != "none":
            evidence_g.add((subject, ns["proposedAlignment"],
                            URIRef(str(PROPERTIES[rel.standard_term]))))
        evidence_g.add((subject, ns["requires"],
                        Literal(json.dumps(rel.requires))))
        annotate(subject, rel, rel.evidence)

    for binding in domain.description_bindings:
        node = ns[f"description/{binding.tree_path}"]
        for cid in binding.concept_ids:
            evidence_g.add((node, ns["describesConcept"], ns[f"class/{cid}"]))
        for rid in binding.relation_ids:
            evidence_g.add((node, ns["describesRelation"], ns[f"property/{rid}"]))

    for i, link in enumerate(domain.field_links):
        node = ns[f"fieldLink/{i}"]
        evidence_g.add((node, ns["sourceColumn"], Literal(link.column)))
        evidence_g.add((node, ns["concept"], ns[f"class/{link.concept_id}"]))
        evidence_g.add((node, ns["property"], ns[f"property/{link.relation_id}"]))

    for i, fm in enumerate(mapping.field_mappings):
        node = ns[f"fieldMapping/{i}"]
        for predicate, value in (("sourceColumn", fm.column), ("role", fm.role),
                                 ("candidateTerm", fm.term), ("basis", fm.basis),
                                 ("requires", json.dumps(fm.requires))):
            evidence_g.add((node, ns[predicate], Literal(value)))

    return dataset.serialize(format="trig")


def tree_paths_of(root: dict[str, Any]) -> set[str]:
    """Zero-based tree paths of a description/query tree: root, root.0, ..."""
    paths: set[str] = set()

    def walk(node: dict[str, Any], path: str) -> None:
        paths.add(path)
        for i, child in enumerate(node.get("children", [])):
            walk(child, f"{path}.{i}")

    walk(root, "root")
    return paths


# --------------------------------------------------------------------------
# Generation rules (the ONTOLOGY prompt body)
# --------------------------------------------------------------------------


def generate(llm: Any, profile: dict[str, Any],
             tree_paths: set[str] | None = None) -> SourceMapping:
    """One LLM call -> validated source mapping. Grounding is enforced here."""
    from . import prompts
    raw = llm.chat(
        prompts.ONTOLOGY.format(
            profile=json.dumps(profile, ensure_ascii=False),
            tree_paths=json.dumps(sorted(tree_paths or ["root"]))),
        "Produce the ontology for this profile.")
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OntologyError(f"ontology response is not JSON: {exc}") from exc
    mapping = SourceMapping.from_dict(data)
    validate_source(mapping, profile, tree_paths)
    return mapping
