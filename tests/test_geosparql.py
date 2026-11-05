"""GeoSPARQL layer: materialization, spec compilation, GEOF execution."""
from __future__ import annotations

import json

import pytest

from jevrag.geosparql import (
    GeoSPARQLError,
    compile_spec,
    execute,
    guard_query,
    load_manifest,
    materialize,
)
from tests.test_ontology import demo_mapping, profile_of


@pytest.fixture()
def graph_env(demo_dataset, tmp_path):
    """Materialize the demo dataset under the demo ontology mapping."""
    mapping = demo_mapping()
    conn = demo_dataset.connect()
    rows = [tuple(r) for r in conn.execute("SELECT * FROM city_poi")]
    columns = [c["name"] for c in demo_dataset.tables[0]["columns"]]
    rows_by_table = {"city_poi": rows}
    tables = [{"name": "city_poi", "columns": [{"name": c} for c in columns]}]
    manifest = materialize(tables, rows_by_table, mapping, tmp_path / "graph",
                           "urn:ioc:graph:demo")
    return manifest, mapping, columns


class TestMaterialize:
    def test_manifest_reports_provenance(self, graph_env):
        manifest, _, _ = graph_env
        assert manifest.status == "loaded"
        assert manifest.geometry_crs == "CRS84"
        assert "rdfs:label" in manifest.predicate_schema
        assert manifest.graph_file and manifest.sources

    def test_rows_carry_labels_and_provenance(self, graph_env):
        from rdflib import Graph
        manifest, _, _ = graph_env
        graph = Graph().parse(manifest.graph_file, format="turtle")
        subjects = {s for s in graph.subjects()}
        assert any("urn:ioc:row:city_poi:" in str(s) for s in subjects)
        labels = [str(o) for o in graph.objects()
                  if "label" in str(o) and str(o) != "label"]
        texts = [str(o) for o in graph.objects()]
        assert "Cedar Park" in texts
        assert any(t.startswith("POINT(") for t in texts)

    def test_category_value_maps_to_ontology_class(self, graph_env):
        from rdflib import Graph, URIRef
        from rdflib.namespace import RDF
        manifest, _, _ = graph_env
        graph = Graph().parse(manifest.graph_file, format="turtle")
        types = [str(o) for s, o in graph.subject_objects(RDF.type)]
        assert any(":class/c2" in t for t in types)


class TestCompileSpec:
    def test_select_compiles(self, graph_env):
        manifest, _, _ = graph_env
        sparql = compile_spec(
            {"operation": "select", "select_predicates": ["rdfs:label"]},
            manifest)
        assert sparql.strip().startswith("PREFIX")
        assert "SELECT ?s ?p ?o" in sparql

    def test_unknown_predicate_rejected(self, graph_env):
        manifest, _, _ = graph_env
        with pytest.raises(GeoSPARQLError, match="not observed"):
            compile_spec({"operation": "select",
                          "filters": [{"predicate": "ex:p", "value": "x"}]},
                         manifest)

    def test_spatial_requires_verified_crs(self, tmp_path):
        from jevrag.geosparql import Manifest
        manifest = Manifest(graph_iri="urn:x", geometry_crs=None,
                            predicate_schema={"rdfs:label": "http://l"})
        with pytest.raises(GeoSPARQLError, match="geometry_crs"):
            compile_spec({"operation": "within"}, manifest)

    def test_distance_requires_radius(self, graph_env):
        manifest, _, _ = graph_env
        with pytest.raises(GeoSPARQLError, match="radius"):
            compile_spec({"operation": "distance", "radius_metres": 0}, manifest)

    def test_unsupported_with_reason(self, graph_env):
        manifest, _, _ = graph_env
        with pytest.raises(GeoSPARQLError, match="inexpressible"):
            compile_spec({"operation": "unsupported",
                          "reason": "inexpressible"}, manifest)


class TestGuard:
    def test_update_statements_rejected(self):
        with pytest.raises(GeoSPARQLError):
            guard_query("INSERT DATA { <a> <b> <c> }")

    def test_graph_and_service_rejected(self):
        with pytest.raises(GeoSPARQLError):
            guard_query("SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } }")
        with pytest.raises(GeoSPARQLError):
            guard_query("SELECT ?s WHERE { SERVICE ?e { ?s ?p ?o } }")

    def test_extension_function_rejected(self):
        with pytest.raises(GeoSPARQLError, match="not allowed"):
            guard_query("SELECT ?r WHERE { BIND(<http://evil.org/fn>(1) AS ?r) }")

    def test_unknown_geof_function_rejected(self):
        with pytest.raises(GeoSPARQLError, match="not allowed"):
            guard_query(
                "SELECT ?r WHERE { BIND(<http://www.opengis.net/def/"
                "function/geosparql/evil>(1) AS ?r) }")

    def test_select_with_allowlisted_geof_passes(self):
        guard_query(
            "SELECT ?d WHERE { ?s <http://www.opengis.net/ont/geosparql#asWKT> ?g ."
            " BIND(<http://www.opengis.net/def/function/geosparql/distance>"
            "(?g, ?g) AS ?d) }")


class TestExecute:
    def test_select_returns_rows(self, graph_env):
        manifest, _, _ = graph_env
        sparql = compile_spec(
            {"operation": "select", "select_predicates": ["rdfs:label"]},
            manifest)
        outcome = execute(sparql, manifest)
        assert outcome["status"] == "completed"
        assert outcome["row_count"] > 0
        assert outcome["graph_iri"] == "urn:ioc:graph:demo"

    def test_ask_empty_is_no_match(self, graph_env):
        manifest, _, _ = graph_env
        sparql = compile_spec(
            {"operation": "ask",
             "filters": [{"predicate": "rdfs:label", "value": "Nowhere"}]},
            manifest)
        outcome = execute(sparql, manifest)
        assert outcome["status"] == "no_match"

    def test_distance_finds_neighbours(self, graph_env):
        manifest, _, _ = graph_env
        sparql = compile_spec(
            {"operation": "distance", "radius_metres": 2000,
             "exclude_reference": True,
             "reference_filters": [{"predicate": "rdfs:label",
                                    "value": "Cedar Park"}]},
            manifest)
        outcome = execute(sparql, manifest)
        assert outcome["status"] == "completed"
        assert outcome["row_count"] >= 2
        assert all("d" in row for row in outcome["rows"])

    def test_intersects_same_point_is_true(self, graph_env):
        manifest, _, _ = graph_env
        sparql = compile_spec(
            {"operation": "intersects",
             "reference_filters": [{"predicate": "rdfs:label",
                                    "value": "Cedar Park"}]},
            manifest)
        outcome = execute(sparql, manifest)
        assert outcome["status"] == "completed"
        assert outcome["row_count"] >= 1


class TestManifest:
    def test_source_drift_rejected(self, graph_env):
        manifest, _, _ = graph_env
        data = manifest.to_dict()
        data["sources"][0]["sha256"] = "0" * 64
        path = manifest.graph_file.replace("graph.ttl", "manifest.json")
        # rewrite manifest with the broken hash
        from pathlib import Path
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(GeoSPARQLError, match="drift"):
            load_manifest(Path(path))

    def test_status_must_be_loaded(self, graph_env, tmp_path):
        from pathlib import Path
        from jevrag.geosparql import Manifest
        manifest, _, _ = graph_env
        data = manifest.to_dict()
        data["status"] = "prepared"
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(GeoSPARQLError, match="not 'loaded'"):
            load_manifest(bad)


class TestRun:
    def test_end_to_end_with_scripted_spec(self, graph_env):
        from jevrag.geosparql import run

        class SpecLLM:
            model = "spec"

            def chat(self, system, user, **kwargs):
                return json.dumps({
                    "operation": "select",
                    "select_predicates": ["rdfs:label"],
                    "filters": [], "reference_filters": [],
                    "radius_metres": 0, "exclude_reference": True})

        manifest, _, _ = graph_env
        outcome = run("list all labels", SpecLLM(), manifest)
        assert outcome["tool_used"] == "geosparql"
        assert outcome["status"] == "completed"
        assert outcome["data"]["row_count"] > 0

    def test_radius_regex_fills_spec(self, graph_env):
        from jevrag.geosparql import run

        class RadiusLLM:
            model = "radius"

            def chat(self, system, user, **kwargs):
                return json.dumps({
                    "operation": "distance", "select_predicates": [],
                    "filters": [],
                    "reference_filters": [{"predicate": "rdfs:label",
                                           "value": "Cedar Park"}],
                    "radius_metres": 0, "exclude_reference": True})

        manifest, _, _ = graph_env
        outcome = run("what is within 2 km of Cedar Park", RadiusLLM(), manifest)
        assert outcome["status"] == "completed"
        assert outcome["data"]["query_spec"]["radius_metres"] == 2000.0

    def test_bad_spec_becomes_evidence_gap(self, graph_env):
        from jevrag.geosparql import run

        class Garbage:
            model = "garbage"

            def chat(self, system, user, **kwargs):
                return "not json at all"

        manifest, _, _ = graph_env
        outcome = run("doomed", Garbage(), manifest)
        assert outcome["status"] == "no_match"
        assert outcome["evidence_gaps"]
