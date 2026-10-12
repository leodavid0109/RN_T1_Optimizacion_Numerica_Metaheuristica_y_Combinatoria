"""Tests for the offline TSP pilot request planner (no route data fixtures)."""

from dataclasses import replace

import pytest

from experiments.prepare_tsp_pilot import PILOT_CITY_IDS, build_pilot_manifest
from src.tsp.cities import load_city_catalog


def test_pilot_manifest_lists_exactly_the_four_canonical_cities_and_12_arcs():
    manifest = build_pilot_manifest(load_city_catalog())

    assert manifest["network_access_performed"] is False
    assert manifest["city_order"] == list(PILOT_CITY_IDS)
    assert manifest["directed_arc_count"] == 4 * 3
    assert len(manifest["directed_arcs"]) == 12
    assert all(arc["origin_id"] != arc["destination_id"] for arc in manifest["directed_arcs"])
    assert {(arc["origin_id"], arc["destination_id"]) for arc in manifest["directed_arcs"]} == {
        (origin, destination)
        for origin in PILOT_CITY_IDS for destination in PILOT_CITY_IDS
        if origin != destination
    }


def test_manifest_distinguishes_fastest_and_toll_excluded_request_templates():
    manifest = build_pilot_manifest(load_city_catalog())
    requests = {request["id"]: request for request in manifest["requests"]}

    assert requests["osrm_fastest_table"]["annotations"] == ["distance", "duration"]
    assert requests["osrm_fastest_route_geometry"]["parameters"]["overview"] == "full"
    assert requests["osrm_toll_excluded_candidates"]["parameters"]["exclude"] == ["toll"]
    assert "precondition" in requests["osrm_toll_excluded_candidates"]
    assert manifest["explicitly_not_provided"]


def test_manifest_rejects_unverified_pilot_coordinates():
    cities = list(load_city_catalog())
    target_index = next(index for index, city in enumerate(cities) if city.city_id == "madrid")
    cities[target_index] = replace(cities[target_index], coordinate_status="pendiente")

    with pytest.raises(ValueError, match="no está verificada"):
        build_pilot_manifest(cities)
