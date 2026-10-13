"""Pruebas sintéticas del consolidador y análisis offline Overpass."""

import json

from src.tsp.etl.toll_infrastructure import (
    TollInfrastructure,
    match_infrastructure_to_route,
)
from src.tsp.etl.toll_pilot_analysis import (
    consolidate_overpass_snapshots,
    summarize_query_state,
)


def _payload(osm_id=77, *, toll="yes", offset=0.0):
    return {"osm3s": {"timestamp_osm_base": "2026-10-12T12:00:00Z"}, "elements": [{
        "type": "way", "id": osm_id,
        "geometry": [{"lon": -1.0 + offset, "lat": 42.0}, {"lon": -0.99 + offset, "lat": 42.0}],
        "tags": {"highway": "motorway", "toll": toll, "ref": "AP-68"},
    }]}


def test_consolidation_deduplicates_across_cells_and_keeps_provenance(tmp_path):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    for idx, acquired in ((1, "2026-10-12T12:00:00+00:00"), (2, "2026-10-12T13:00:00+00:00")):
        filename = f"overpass_cell{idx}_digest.json"
        (raw / filename).write_text(json.dumps(_payload()), encoding="utf-8")
        (processed / f"infrastructure_cell{idx}.metadata.json").write_text(json.dumps({
            "raw_file": filename, "acquired_at": acquired,
        }), encoding="utf-8")

    entries = consolidate_overpass_snapshots(raw, processed)
    assert len(entries) == 1
    assert entries[0].record.stable_id == "osm:way/77"
    assert len(entries[0].observed_in) == 2
    assert len(entries[0].acquired_at_values) == 2
    assert not entries[0].conflicting_snapshots


def test_consolidation_marks_discordant_snapshots_instead_of_hiding_them(tmp_path):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    for idx, payload in ((1, _payload()), (2, _payload(offset=0.001))):
        filename = f"overpass_cell{idx}_digest.json"
        (raw / filename).write_text(json.dumps(payload), encoding="utf-8")
        (processed / f"infrastructure_cell{idx}.metadata.json").write_text(json.dumps({
            "raw_file": filename, "acquired_at": f"2026-10-12T1{idx}:00:00+00:00",
        }), encoding="utf-8")
    entries = consolidate_overpass_snapshots(raw, processed)
    assert len(entries) == 1
    assert entries[0].conflicting_snapshots


def test_query_state_counts_pending_regions_and_http_failures(tmp_path):
    manifest = {"plan_sha256": "abc", "query_count": 5, "regions": []}
    state = {"plan_sha256": "abc", "regions": {
        "a": {"status": "adquirida"}, "b": {"status": "error", "http_status": 504},
    }, "last_execution": {"http_requests": 2}}
    manifest_path, state_path = tmp_path / "manifest.json", tmp_path / "state.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = summarize_query_state(manifest_path, state_path)
    assert (result["planned"], result["acquired"], result["failed"], result["pending"]) == (5, 1, 1, 3)
    assert result["http_requests_last_execution"] == 2
    assert result["http_504_count"] == 1


def _feature(osm_id, line):
    return TollInfrastructure(
        "way", osm_id, "toll_road", tuple(line), "Autopista", None, "AP-68", None,
        (("toll", "yes"),), "fixture", "2026-10-12T00:00:00Z",
    )


def test_match_separates_aligned_road_from_pointlike_crossing():
    route = [(-1.0, 42.0), (-0.995, 42.0), (-0.99, 42.0)]
    aligned = _feature(1, [(-1.0, 42.000005), (-0.99, 42.000005)])
    crossing = _feature(2, [(-0.995, 41.999), (-0.995, 42.001)])
    matches = match_infrastructure_to_route("route", route, [aligned, crossing], radius_m=35)
    by_id = {match.infrastructure_id: match for match in matches}
    assert by_id["osm:way/1"].confidence == "coincidencia_vial_probable"
    assert by_id["osm:way/1"].aligned_route_length_m > 250
    assert by_id["osm:way/2"].confidence == "candidato_proximidad"
    assert by_id["osm:way/2"].aligned_route_length_m < 250


def test_relation_members_are_saved_as_separate_lines_without_connector_artifacts(tmp_path):
    from src.tsp.etl.toll_infrastructure import load_infrastructure_catalog, save_infrastructure_catalog

    from src.tsp.etl.toll_infrastructure import parse_overpass_response
    records = parse_overpass_response({"elements": [{
        "type": "relation", "id": 90, "tags": {"toll": "yes", "ref": "AP-68"},
        "members": [
            {"type": "way", "ref": 1, "geometry": [{"lon": -1.0, "lat": 42.0}, {"lon": -0.99, "lat": 42.0}]},
            {"type": "way", "ref": 2, "geometry": [{"lon": -0.8, "lat": 42.1}, {"lon": -0.79, "lat": 42.1}]},
        ],
    }]}, acquired_at="2026-10-12T12:00:00+00:00")
    path = tmp_path / "catalog.geojson"
    save_infrastructure_catalog(path, records)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["features"][0]["geometry"]["type"] == "MultiLineString"
    loaded = load_infrastructure_catalog(path)
    assert len(loaded[0].geometry_parts_lon_lat) == 2
    assert loaded[0].geometry_lon_lat[0] == (-1.0, 42.0)
