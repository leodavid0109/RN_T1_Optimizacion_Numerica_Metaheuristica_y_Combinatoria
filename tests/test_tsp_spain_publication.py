"""Pruebas offline del empaquetado público de rutas y baselines."""

import gzip
import hashlib
import json

import numpy as np
import pytest

from experiments.export_tsp_spain_publication import (
    _extract_record,
    _file_hash,
    _geometry_digest,
    _response_digest,
    _write_gzip_jsonl,
    baseline_cost_matrix,
    verify_publication_bundle,
    validate_pair_universe,
)


def test_baseline_costs_exclude_tolls_and_keep_direction():
    duration = np.array([[0.0, 1.0], [2.0, 0.0]])
    fuel = np.array([[0.0, 3.0], [4.0, 0.0]])
    result = baseline_cost_matrix(duration, fuel, 10)
    assert result.tolist() == [[0.0, 13.0], [24.0, 0.0]]
    assert result[0, 1] != result[1, 0]
    with pytest.raises(ValueError, match="no finitos"):
        baseline_cost_matrix([[0, float("nan")], [1, 0]], fuel, 10)


def test_pair_universe_requires_all_unique_directed_arcs():
    ids = [f"c{i}" for i in range(47)]
    pairs = [(o, d) for o in ids for d in ids if o != d]
    assert len(validate_pair_universe(ids, pairs)) == 2162
    with pytest.raises(ValueError, match="duplicados"):
        validate_pair_universe(ids, [*pairs, pairs[0]])
    with pytest.raises(ValueError, match="faltan 1"):
        validate_pair_universe(ids, pairs[1:])


def test_route_record_accepts_two_supported_extras_without_osmid(tmp_path):
    coords = [[-3.7, 40.4], [-3.6, 40.5]]
    response = {
        "metadata": {"engine": {"version": "test"}},
        "features": [{
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"summary": {"distance": 1200, "duration": 600}, "extras": {
                "tollways": {"values": [[0, 1, 0]]},
                "waycategory": {"values": [[0, 1, 1]]},
            }},
        }],
    }
    response_hash = _response_digest(response)
    raw_path = tmp_path / f"snapshot_{response_hash[:16]}.json"
    raw = {
        "request_id": "request-1",
        "request": {
            "url": "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson",
            "body": {"preference": "fastest", "extra_info": ["tollways", "waycategory"]},
            "acquisition": {"profile": "driving-car", "origin_id": "a", "destination_id": "b",
                            "acquired_at": "2026-10-13T00:00:00+00:00"},
        },
        "response": response,
        "response_sha256": response_hash[:16],
    }
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    analyzed = {
        "request_id": "request-1", "route_id": "route-1", "origin_id": "a", "destination_id": "b",
        "coverage": "complete_cartographic", "response_hash_verified": True,
        "extra_info_status": {"tollways": "solicitado_y_presente", "waycategory": "solicitado_y_presente"},
        "geometry_sha256": hashlib.sha256(json.dumps(coords, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "distance_km": 1.2, "duration_hours": 1/6, "provider_warnings": [],
    }
    record = _extract_record(raw_path, raw, analyzed)
    assert record["extras"]["tollways"]["values"] == [[0, 1, 0]]
    assert "osmId" not in record["extras"]
    assert record["geometry"]["coordinates"] == coords


def test_route_record_rejects_missing_extras_and_incomplete_coverage(tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="identidad"):
        _extract_record(raw_path, {}, {"request_id": "bad"})


def test_gzip_jsonl_output_is_deterministic(tmp_path):
    records = [{"id": "b", "v": 2}, {"id": "a", "v": 1}]
    first, second = tmp_path / "one.gz", tmp_path / "two.gz"
    _write_gzip_jsonl(first, records)
    _write_gzip_jsonl(second, records)
    assert first.read_bytes() == second.read_bytes()
    assert list(map(json.loads, gzip.open(first, "rt", encoding="utf-8"))) == records


def test_bundle_verifier_accepts_complete_directed_catalog(tmp_path):
    ids = [f"c{i:02d}" for i in range(47)]
    coords = [[-3.0, 40.0], [-2.9, 40.1]]
    gh = _geometry_digest(coords)
    records = []
    for origin in ids:
        for destination in ids:
            if origin == destination:
                continue
            records.append({
                "schema_version": 1,
                "route_id": f"route-{origin}-{destination}",
                "request_id": f"request-{origin}-{destination}",
                "origin_id": origin,
                "destination_id": destination,
                "geometry": {"type": "LineString", "coordinates": coords},
                "geometry_sha256": gh,
                "extras": {name: {"values": [[0, 1, 0]]} for name in ("tollways", "waycategory")},
            })
    shards = []
    for offset in range(0, len(records), 200):
        name = f"routes/ors_enriched/routes-{offset // 200 + 1:04d}.jsonl.gz"
        path = tmp_path / name
        chunk = records[offset:offset + 200]
        _write_gzip_jsonl(path, chunk)
        shards.append({"path": name, "records": len(chunk), "size_bytes": path.stat().st_size,
                       "sha256": _file_hash(path)})
    manifest = {"route_count": 2162, "shards": shards}
    manifest_path = tmp_path / "routes/ors_enriched/manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    metadata = {
        "city_order": ids,
        "files_sha256": {"routes/ors_enriched/manifest.json": _file_hash(manifest_path),
                         **{s["path"]: s["sha256"] for s in shards}},
        "enriched_route_bundle": {"route_count": 2162, "manifest": "routes/ors_enriched/manifest.json"},
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = verify_publication_bundle(tmp_path)
    assert result["routes"] == result["directed_arcs"] == 2162
    assert result["shards"] == len(shards)
