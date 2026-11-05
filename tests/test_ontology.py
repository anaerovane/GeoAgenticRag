"""Ontology framework: grounding validation, source alignment, TriG export."""
from __future__ import annotations

import json

import pytest
from rdflib import Graph

from jevrag.ontology import (
    Concept,
    DescriptionBinding,
    DomainModel,
    Evidence,
    FieldLink,
    FieldMapping,
    HierarchyEdge,
    OntologyError,
    Relation,
    SourceMapping,
    generate,
    serialize_trig,
    source_hash_for,
    tree_paths_of,
    validate_source,
)


def demo_mapping() -> SourceMapping:
    """A fully grounded spatial mapping over the city_poi demo profile."""
    ev_cat = Evidence(basis="category vocabulary", columns=["category"],
                      values=[{"column": "category", "value": "park"}])
    ev_name = Evidence(basis="record label", columns=["name"], values=[])
    domain = DomainModel(
        concepts=[
            Concept(id="c1", label="Place", definition="A city point of interest.",
                    kind="source_record", alignment="geo:Feature",
                    status="proposed", evidence=ev_name),
            Concept(id="c2", label="Park",
                    definition="A park anchored in the observed vocabulary.",
                    kind="domain_category", alignment="skos:Concept",
                    status="observed_label", evidence=ev_cat),
            Concept(id="c3", label="Amenity",
                    definition="Proposed abstract parent of category leaves.",
                    kind="domain_category", alignment="skos:Concept",
                    status="proposed", evidence=ev_name),
        ],
        hierarchy=[HierarchyEdge(child="c2", parent="c3", evidence=ev_cat),
                   HierarchyEdge(child="c3", parent="c1", evidence=ev_name)],
        relations=[
            Relation(id="r1", label="type", definition="Category type of a place.",
                     domain="c1", range="c2", property_kind="object",
                     standard_term="rdf:type",
                     requires=["category_evidence",
                               "category_value_to_class_mapping"],
                     evidence=ev_cat),
            Relation(id="r2", label="lat", definition="WGS84 latitude.",
                     domain="c1", range="xsd:double", property_kind="datatype",
                     standard_term="wgs84:lat", requires=["crs_confirmation"],
                     evidence=ev_name),
            Relation(id="r3", label="long", definition="WGS84 longitude.",
                     domain="c1", range="xsd:double", property_kind="datatype",
                     standard_term="wgs84:long", requires=["crs_confirmation"],
                     evidence=ev_name),
            Relation(id="r4", label="label", definition="Human readable label.",
                     domain="c1", range="xsd:string", property_kind="datatype",
                     standard_term="rdfs:label", evidence=ev_name),
        ],
        field_links=[
            FieldLink("name", "c1", "r4"),
            FieldLink("category", "c2", "r1"),
            FieldLink("lat", "c1", "r2"),
            FieldLink("lon", "c1", "r3"),
        ],
        description_bindings=[DescriptionBinding(
            "root", ["c1", "c2", "c3"], ["r1", "r2", "r3", "r4"],
            ["name", "category", "lat", "lon"])],
    )
    return SourceMapping(
        record_kind="spatial_feature", class_alignment="geo:Feature",
        field_mappings=[
            FieldMapping("name", "label", "rdfs:label", "record label"),
            FieldMapping("category", "category", "rdf:type", "observed vocabulary",
                         ["category_value_to_class_mapping"]),
            FieldMapping("district", "other", "none", "district name"),
            FieldMapping("lat", "latitude", "wgs84:lat", "coordinate",
                         ["crs_confirmation"]),
            FieldMapping("lon", "longitude", "wgs84:long", "coordinate",
                         ["crs_confirmation"]),
            FieldMapping("rating", "other", "none", "score"),
        ],
        category_binding="observed_column", category_column="category",
        limitations=["geometry CRS confirmed as CRS84"],
        domain=domain,
    )


def profile_of(demo_dataset):
    return {"name": "city_poi", "columns": demo_dataset.tables[0]["columns"],
            "sample": demo_dataset.tables[0].get("sample", [])}


class TestSourceMapping:
    def test_roundtrip(self):
        mapping = demo_mapping()
        again = SourceMapping.from_dict(mapping.to_dict())
        assert again.to_dict() == mapping.to_dict()

    def test_valid_mapping_accepted(self, demo_dataset):
        validate_source(demo_mapping(), profile_of(demo_dataset))

    def test_tree_paths_checked(self, demo_dataset):
        mapping = demo_mapping()
        mapping.domain.description_bindings[0].tree_path = "root.1"
        with pytest.raises(OntologyError, match="nonexistent tree path"):
            validate_source(mapping, profile_of(demo_dataset),
                            tree_paths={"root", "root.0"})

    def test_tree_paths_helper(self):
        tree = {"children": [{"children": []}, {"children": []}]}
        assert tree_paths_of(tree) == {"root", "root.0", "root.1"}


class TestGrounding:
    def _broken(self):
        return demo_mapping()

    def test_unobserved_evidence_value_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.concepts[1].evidence.values = [
            {"column": "category", "value": "invented"}]
        with pytest.raises(OntologyError, match="not observed"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_evidence_substring_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.concepts[0].evidence.values = [
            {"column": "name", "value": "Cedar"}]
        with pytest.raises(OntologyError, match="not observed"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_unknown_column_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.concepts[0].evidence.columns = ["nope"]
        with pytest.raises(OntologyError, match="unknown column"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_column_mapped_twice_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.field_mappings.append(FieldMapping("name", "other", "none", "dup"))
        with pytest.raises(OntologyError, match="exactly once|mapped twice"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_missing_column_mapping_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.field_mappings = mapping.field_mappings[:-1]
        with pytest.raises(OntologyError, match="exactly once"):
            validate_source(mapping, profile_of(demo_dataset))


class TestAxiomRules:
    def _broken(self):
        return demo_mapping()

    def test_observed_label_needs_category_evidence(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.concepts[1].evidence.values = []
        with pytest.raises(OntologyError, match="observed_label requires"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_hierarchy_cycle_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.hierarchy.append(
            HierarchyEdge(child="c1", parent="c2", evidence=None))
        with pytest.raises(OntologyError, match="cycle"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_wgs84_needs_crs_confirmation(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.relations[1].requires = []
        with pytest.raises(OntologyError, match="crs_confirmation"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_geo_relation_needs_geometry_gates(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.relations[3] = Relation(
            id="r4", label="geom", definition="Geometry of a place.",
            domain="c1", range="geo:Geometry", property_kind="object",
            standard_term="geo:hasGeometry", requires=[], evidence=None)
        with pytest.raises(OntologyError, match="requires"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_datatype_range_mismatch_rejected(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.relations[3].range = "geo:Feature"
        with pytest.raises(OntologyError, match="disagrees"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_rdfs_label_must_be_datatype(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.relations[3].property_kind = "object"
        mapping.domain.relations[3].range = "c1"
        with pytest.raises(OntologyError, match="datatype"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_binding_requires_root(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.description_bindings[0].tree_path = "root.0"
        with pytest.raises(OntologyError, match="include 'root'"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_entity_name_cannot_be_category(self, demo_dataset):
        mapping = self._broken()
        mapping.category_column = "name"
        mapping.field_mappings[0] = FieldMapping("name", "category", "rdf:type",
                                                 "bad")
        with pytest.raises(OntologyError, match="entity-name"):
            validate_source(mapping, profile_of(demo_dataset))

    def test_coverage_literal_enforced(self, demo_dataset):
        mapping = self._broken()
        mapping.domain.coverage = "complete"
        with pytest.raises(OntologyError, match="coverage"):
            validate_source(mapping, profile_of(demo_dataset))


class TestExport:
    def test_trig_has_two_named_graphs(self, demo_dataset):
        mapping = demo_mapping()
        trig = serialize_trig(mapping, "abcd1234")
        from rdflib import Dataset
        dataset = Dataset()
        dataset.parse(data=trig, format="trig")
        assert len(dataset) > 0
        names = {str(g.identifier) for g in dataset.graphs()}
        assert "urn:ioc:ontology:abcd1234:proposed" in names
        assert "urn:ioc:ontology:abcd1234:evidence" in names
        assert "owl:Class" in trig or "OWL" in trig
        assert "subClassOf" in trig
        assert "proposedAlignment" in trig

    def test_source_hash_stable(self):
        a = source_hash_for({"name": "city_poi"})
        b = source_hash_for({"name": "CITY_POI"})
        assert a == b and len(a) == 8


class TestGenerate:
    def test_mock_llm_produces_valid_mapping(self, demo_dataset):
        from jevrag.llm import MockLLM
        mapping = generate(MockLLM(), profile_of(demo_dataset))
        assert {f.column for f in mapping.field_mappings} == \
            {c["name"] for c in demo_dataset.tables[0]["columns"]}
        assert mapping.domain.coverage == "partial_proposed_domain_model"

    def test_mock_llm_respects_tree_paths(self, demo_dataset):
        from jevrag.llm import MockLLM
        mapping = generate(MockLLM(), profile_of(demo_dataset), {"root", "root.0"})
        assert mapping.domain.description_bindings[0].tree_path == "root"
