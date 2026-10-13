"""Pruebas sintéticas del consolidador y análisis offline Overpass."""

import json

from src.tsp.etl.toll_infrastructure import (
    TollInfrastructure,
    match_infrastructure_to_route,
)
from src.tsp.etl.toll_pilot_analysis import (
    _render_markdown,
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


def test_rendered_report_uses_current_query_counts_and_route_coverage():
    state = {
        "planned": 35, "acquired": 2, "failed": 1, "pending": 32,
        "http_requests_last_execution": 2, "http_504_count": 1, "http_429_count": 0,
    }
    summary = {
        "query_state": state, "raw_response_files": 2, "raw_elements_total": 171,
        "normalized_observations": 171, "unique_infrastructure": 168,
        "duplicates_removed": 3, "snapshot_conflicts": 0, "types": {},
        "operators": {}, "roads": {}, "route_alternatives": 12,
        "radius_m": 35, "route_matches": 0, "route_matches_by_level": {},
        "ors_routes_with_extra_info": 0,
    }
    routes = [{
        "route_id": "fast-bz",
        "origin_id": "bizkaia", "destination_id": "zaragoza",
        "origin_name": "Bilbao", "destination_name": "Zaragoza",
        "strategy": "fastest", "acquired_regions_for_route": 2,
        "planned_regions_for_route": 8, "ap68_reference_match": True,
        "infrastructure_id": "osm:relation/90", "road_reference": "AP-68", "minimum_distance_m": 0,
        "aligned_route_length_m": 290_900, "evidence_level": "coincidencia_vial_probable",
    }]
    report = _render_markdown(summary, routes)
    assert "2 regiones completadas, 1 fallidas y 32 pendientes" in report
    assert "Se encontraron 2 respuestas crudas locales" in report
    assert "Bilbao → Zaragoza: 2/8 celdas" in report
    assert "Quedan 33 regiones no completadas (1 fallida(s) y 32 pendiente(s))" in report


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
