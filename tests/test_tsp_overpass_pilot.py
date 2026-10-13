"""Pruebas sintéticas del planificador Overpass; no consultan servicios externos."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl.overpass_pilot import execute_plan, plan_overpass_regions
from src.tsp.etl.toll_infrastructure import BoundingBox, OverpassError


def _route(origin, destination, alt_id, points):
    return RouteAlternative(
        origin, destination, alt_id, alt_id, 10, 1, TollStatus.UNKNOWN, None,
        "synthetic", "fixture", "driving-car", "synthetic://route", "2026-10-12",
        geometry_lon_lat=tuple(points),
    )


def test_plan_covers_routes_with_small_bounding_boxes_and_deduplicates_cells():
    routes = [
        _route("bizkaia", "zaragoza", "forward", [(-2.0, 43.0), (-1.0, 42.5), (0.0, 42.0)]),
        _route("zaragoza", "bizkaia", "reverse", [(0.0, 42.0), (-1.0, 42.5), (-2.0, 43.0)]),
        _route("a", "b", "nearby", [(-1.9, 43.0), (-1.0, 42.5)]),
    ]
    plan = plan_overpass_regions(routes, cell_degrees=0.25, margin_m=1_000)
    assert plan.route_pair_count == 3
    assert plan.route_ids == ("forward", "nearby", "reverse")
    assert plan.geometry_point_count == 8
    assert plan.segment_count == 5
    assert plan.coverage_sample_count == 13
    assert plan.planned_requests == len({
        (int(region.bbox.west / 0.25), int(region.bbox.south / 0.25))
        for region in plan.regions
    })
    assert all((region.bbox.north - region.bbox.south) *
               (region.bbox.east - region.bbox.west) <= 0.0625 + 1e-12
               for region in plan.regions)
    assert {rid for region in plan.regions for rid in region.route_ids} == set(plan.route_ids)
    assert [region.priority for region in plan.regions] == sorted(region.priority for region in plan.regions)


def test_plan_rejects_missing_geometry_and_duplicate_ids():
    no_geometry = _route("a", "b", "empty", [(-3.0, 40.0), (-2.9, 40.0)])
    object.__setattr__(no_geometry, "geometry_lon_lat", None)
    with pytest.raises(ValueError, match="geometría lineal"):
        plan_overpass_regions([no_geometry])
    route = _route("a", "b", "same", [(-3.0, 40.0), (-2.9, 40.0)])
    with pytest.raises(ValueError, match="duplicados"):
        plan_overpass_regions([route, route])


def test_plan_fingerprint_tracks_local_geometry_and_parameters():
    first = _route("a", "b", "route", [(-3.0, 40.0), (-2.9, 40.0)])
    shifted = _route("a", "b", "route", [(-3.0, 40.0), (-2.8, 40.0)])
    assert plan_overpass_regions([first]).fingerprint == plan_overpass_regions([first]).fingerprint
    assert plan_overpass_regions([first]).fingerprint != plan_overpass_regions([shifted]).fingerprint
    assert plan_overpass_regions([first]).fingerprint != plan_overpass_regions([first], margin_m=2_500).fingerprint


def test_execute_checks_budget_before_any_request_and_persists_success_for_resume(tmp_path):
    plan = plan_overpass_regions([_route("a", "b", "route", [(-3.0, 40.0), (-2.9, 40.0)])])

    class FakeStore:
        raw_dir = tmp_path / "raw"
        processed_dir = tmp_path / "processed"

        def __init__(self):
            self.calls = 0

        def get_or_fetch(self, client, bbox):
            self.calls += 1
            return (), True

    store = FakeStore()
    state_path = tmp_path / "state.json"
    with pytest.raises(ValueError, match="presupuesto"):
        execute_plan(plan, max_requests=plan.planned_requests - 1,
                     store=store, state_path=state_path, sleep=lambda _: None)
    assert store.calls == 0

    result = execute_plan(plan, max_requests=plan.planned_requests,
                          store=store, state_path=state_path, sleep=lambda _: None)
    assert result["http_requests"] == plan.planned_requests
    assert result["failed"] == 0
    resumed = execute_plan(plan, max_requests=plan.planned_requests,
                           store=store, state_path=state_path, sleep=lambda _: None)
    assert resumed["http_requests"] == 0
    assert resumed["skipped_cached"] == plan.planned_requests
    assert store.calls == plan.planned_requests
    assert json.loads(state_path.read_text(encoding="utf-8"))["regions"]


def test_execute_stops_and_saves_state_on_http_429(tmp_path):
    plan = plan_overpass_regions([_route("a", "b", "route", [(-3.0, 40.0), (-2.9, 40.0)])])

    class BusyStore:
        raw_dir = tmp_path / "raw"
        processed_dir = tmp_path / "processed"

        def __init__(self):
            self.calls = 0

        def get_or_fetch(self, client, bbox):
            self.calls += 1
            raise OverpassError("Overpass respondió HTTP 429", status_code=429)

    store = BusyStore()
    state_path = tmp_path / "state.json"
    result = execute_plan(plan, max_requests=plan.planned_requests,
                          store=store, state_path=state_path, sleep=lambda _: None)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["failed"] == 1
    assert result["http_requests"] == 1
    assert store.calls == 1
    assert state["stop_reason"].startswith("HTTP 429")
    assert next(iter(state["regions"].values()))["http_status"] == 429
    with pytest.raises(ValueError, match="reanude después de"):
        execute_plan(plan, max_requests=plan.planned_requests,
                     store=store, state_path=state_path, sleep=lambda _: None)
    assert store.calls == 1


def test_execute_refuses_a_plan_with_another_local_route_set(tmp_path):
    plan = plan_overpass_regions([_route("a", "b", "route", [(-3.0, 40.0), (-2.9, 40.0)])])
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "plan_route_ids": ["different"], "regions": {},
        "cooldown_until_utc": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="otro plan"):
        execute_plan(plan, max_requests=plan.planned_requests, state_path=state_path)


def test_half_degree_bbox_is_within_the_small_query_area():
    box = BoundingBox(41.0, -2.0, 41.5, -1.5)
    assert (box.north - box.south) * (box.east - box.west) == pytest.approx(0.25)
    assert "[out:json]" in box.overpass_query()
