"""Dataset builder: CSV files -> SQLite database + table profiles + source index.

`jevrag index data/*.csv --out .runtime/demo` produces three artifacts:
`<name>.db`, `<name>.tables.json` and `<name>.index.json`. GeoJSON files are
flattened to feature tables with `lon`/`lat` columns when coordinates exist.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .retrieval import Doc, SourceIndex, index_from_tables

_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def _infer_type(values: list[str]) -> str:
    nonempty = [v for v in values if v != ""]
    if not nonempty:
        return "text"
    if all(_NUMERIC.match(v) for v in nonempty):
        return "real" if any("." in v for v in nonempty) else "integer"
    return "text"


def _load_csv(path: Path) -> tuple[str, list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name}: empty CSV")
    header = [h.strip() or f"col{i}" for i, h in enumerate(rows[0])]
    return path.stem, header, rows[1:]


def _load_geojson(path: Path) -> tuple[str, list[str], list[list[Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", []) if payload.get("type") == "FeatureCollection" \
        else [payload]
    props: dict[str, list[Any]] = {}
    lons: list[Any] = []
    lats: list[Any] = []
    for feat in features:
        p = dict(feat.get("properties") or {})
        for key in p:
            props.setdefault(key, [])
        for key in props:
            props[key].append(p.get(key))
        geometry = feat.get("geometry") or {}
        coords = geometry.get("coordinates")
        lon = lat = None
        if geometry.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
        lons.append(lon)
        lats.append(lat)
    columns = list(props.keys())
    has_point = any(v is not None for v in lons)
    if has_point:
        columns += ["lon", "lat"]
        props["lon"] = lons
        props["lat"] = lats
    rows = [[props[c][i] for c in columns] for i in range(len(features))]
    return path.stem, columns, rows


def _profile(name: str, header: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for idx, col in enumerate(header):
        values = ["" if r[idx] is None else str(r[idx]) for r in rows[:2000]
                  if idx < len(r)]
        col_info: dict[str, Any] = {
            "name": col,
            "type": _infer_type(values),
            "description": "",
        }
        distinct = sorted({v for v in values if v != ""})
        if 0 < len(distinct) <= 30 and col_info["type"] == "text":
            col_info["values"] = distinct[:30]
        if col_info["type"] in {"integer", "real"} and distinct:
            numeric = [float(v) for v in distinct]
            col_info["min"] = min(numeric)
            col_info["max"] = max(numeric)
        columns.append(col_info)
    sample = [dict(zip(header, ("" if v is None else v for v in row)))
              for row in rows[:3]]
    return {"name": name, "columns": columns, "sample": sample,
            "row_count": len(rows),
            "description": f"Table {name} with {len(rows)} rows."}


def build_dataset(paths: list[Path], out_dir: Path, dataset_id: str) -> dict[str, Any]:
    """Build db + tables + index for a set of CSV/GeoJSON files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{dataset_id}.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    tables: list[dict[str, Any]] = []
    try:
        for path in sorted(paths):
            if path.suffix.lower() == ".csv":
                name, header, rows = _load_csv(path)
            elif path.suffix.lower() in {".geojson", ".json"}:
                name, header, rows = _load_geojson(path)
            else:
                continue
            name = re.sub(r"[^A-Za-z0-9_]", "_", name)
            profile = _profile(name, header, rows)
            conn.execute(
                f'CREATE TABLE "{name}" ('
                + ", ".join(f'"{c["name"]}" {c["type"]}' for c in profile["columns"])
                + ")"
            )
            placeholders = ", ".join("?" for _ in header)
            typed_rows = []
            for row in rows:
                out = []
                for idx, value in enumerate(row):
                    if idx >= len(header):
                        break
                    if profile["columns"][idx]["type"] in {"integer", "real"} \
                            and value not in (None, ""):
                        try:
                            value = float(value) if profile["columns"][idx]["type"] == "real" \
                                else int(float(value))
                        except (TypeError, ValueError):
                            value = None
                    out.append(value)
                typed_rows.append(out)
            conn.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})', typed_rows)
            tables.append(profile)
        conn.commit()
    finally:
        conn.close()

    tables_path = out_dir / f"{dataset_id}.tables.json"
    tables_path.write_text(json.dumps(tables, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    index = index_from_tables(tables)
    index_path = out_dir / f"{dataset_id}.index.json"
    index.save(index_path)
    return {"db": str(db_path), "tables": str(tables_path),
            "index": str(index_path), "table_count": len(tables),
            "doc_count": index.size}
