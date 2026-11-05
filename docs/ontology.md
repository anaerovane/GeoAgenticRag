# The Ontology Framework

Ontology is the semantic backbone of GeoAgenticRag — it sits between raw
tables and the query tree and drives the whole retrieval pipeline:

```
tables -> record alignment -> domain model -> RDF graph -> GeoSPARQL tool -> JEV tree
```

## Two layers, strictly separated

- **proposed** — OWL/RDFS axioms the model proposes: classes (`c1..cN`),
  subclass hierarchy, properties (`r1..rN`) with domain/range, aligned to
  OGC GeoSPARQL / SKOS / RDFS / WGS84 vocabularies. Never asserted as
  instance facts.
- **evidence** — grounding for every axiom: exact observed column values
  (whole cells only), real columns, real description-tree paths
  (`root`, `root.0`, ...). An axiom without evidence is rejected
  mechanically, so proposals never drift into hallucination.

Export is TriG with two named graphs (`urn:ioc:ontology:<hash>:proposed`
and `:evidence`).

## The domain model

| Part | Meaning |
|---|---|
| `concepts` | Classes: `source_record`, `domain_category`, `geometry`, `coverage`; alignment `geo:Feature` / `geo:Geometry` / `skos:Concept`; `observed_label` only for vocabulary-grounded category leaves under a proposed abstract parent |
| `hierarchy` | Proposed `rdfs:subClassOf` edges, acyclic |
| `relations` | Object/datatype properties; `geo:*` require `crs_confirmation` + `geometry_materialization` (+ `spatial_evaluation`); `wgs84:*` require `crs_confirmation` |
| `field_links` | Column -> concept + relation (drives RDF materialization) |
| `description_bindings` | Tree path -> concepts/relations/columns (binds the query tree to the model) |

The record-alignment layer (`record_kind`, `field_mappings`,
`category_binding`, `limitations`) maps every column exactly once to a
standard term (`rdfs:label`, `wgs84:lat`, `rdf:type`, ...).

## From ontology to GeoSPARQL

`materialize()` walks the tables under the field mappings and asserts each
row into one RDF graph: standard terms plus `urn:ioc:column:*` provenance,
category values typed to grounded ontology class IRIs, and `geo:asWKT`
points when coordinates carry confirmed CRS. The manifest records the
predicate schema, source hashes and `geometry_crs` honesty.

At query time a branch with tool `geosparql` binds exactly one verified
graph, the model emits a JSON **query spec** (never raw SPARQL), and the
compiler produces allowlisted GEOF SELECT/ASK executed by rdflib + shapely
in-process (or a Jena GeoSPARQL Fuseki endpoint when the manifest says so).

## Where it lives

- `jevrag/ontology.py` — model, validation, TriG export, `generate()`
- `jevrag/geosparql.py` — manifest, materialization, spec -> SPARQL, engines
- `prompts.ONTOLOGY` / `prompts.GEOSPARQL` — the two generation prompts
- `tests/test_ontology.py`, `tests/test_geosparql.py` — grounding and
  execution guarantees
