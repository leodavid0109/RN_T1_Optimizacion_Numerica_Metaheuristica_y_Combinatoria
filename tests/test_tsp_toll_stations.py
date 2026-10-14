"""Pruebas sintéticas para extracción y cruce de nodos de peaje OSM."""

import json

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl.toll_stations import load_station_records, match_stations_to_routes


def _feature(osm_id, lon=-1.0, lat=41.0, tags=None):
    tags = tags or {"barrier": "toll_booth"}
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"osm_type": "node", "osm_id": osm_id, "infrastructure_type": "toll_booth",
                "name": tags.get("name"), "operator": tags.get("operator"),
                "road_reference": tags.get("ref"), "direction": tags.get("direction"),
                "tags": tags, "source": "synthetic-test", "license": "test",
                "observed_in": ["synthetic"], "acquired_at_values": ["2026-10-13T00:00:00Z"]}}


def _route(reverse=False):
    geometry = ((-1.01, 41.0), (-0.99, 41.0))
    if reverse:
        geometry = tuple(reversed(geometry))
    return RouteAlternative("a", "b", "route-ab" if not reverse else "route-ba", "fast-ab",
        10, 0.2, TollStatus.UNKNOWN, None, "ors", "test", "driving-car", "synthetic-test",
        "2026-10-13", road_references=("AP-68",), geometry_lon_lat=geometry)


def test_extracts_node_tags_coordinates_and_optional_address(tmp_path):
    path = tmp_path / "inventory.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        _feature(10, tags={"barrier": "toll_booth", "name": "Estación prueba", "operator": "Operador",
                           "ref": "AP-68", "oneway": "yes", "addr:street": "Vía"}),
        _feature(11),
    ]}), encoding="utf-8")
    rows = load_station_records(path)
    assert len(rows) == 2
    station = rows[0]
    assert (station["osm_type"], station["osm_id"]) == ("node", 10)
    assert (station["longitude"], station["latitude"]) == (-1, 41)
    assert station["name"] == "Estación prueba" and station["operator"] == "Operador"
    assert station["ref"] == "AP-68" and station["direction"] == "yes"
    assert station["address_tags"] == {"addr:street": "Vía"}
    assert station["osm_url"].endswith("/node/10")
    assert rows[1]["name"] is None and rows[1]["address_tags"] == {}


@pytest.mark.parametrize("lon,lat", [(181, 0), (0, -91), (float("nan"), 10)])
def test_rejects_invalid_station_coordinates(tmp_path, lon, lat):
    path = tmp_path / "invalid.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [_feature(1, lon, lat)]}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="coordenada puntual"):
        load_station_records(path)


def test_station_match_is_candidate_and_never_assigns_toll_amount(tmp_path):
    path = tmp_path / "inventory.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        _feature(20, tags={"barrier": "toll_booth", "name": "Gate", "ref": "AP-68"}),
        _feature(21, lon=-1.0, lat=41.001),
    ]}), encoding="utf-8")
    stations = load_station_records(path)
    matches = match_stations_to_routes(stations, (_route(), _route(reverse=True)), candidate_radius_m=150)
    assert len(matches) == 4
    assert {match["state"] for match in matches} == {"MATCHED_ROAD", "CANDIDATE_NEAR_ROUTE"}
    assert all(match["toll_amount_eur"] is None and match["toll_verification"] == "UNKNOWN"
               for match in matches)
    forward = next(match for match in matches if match["station_id"] == "osm:node/20"
                   and match["route_id"] == "route-ab")
    reverse = next(match for match in matches if match["station_id"] == "osm:node/20"
                   and match["route_id"] == "route-ba")
    assert forward["distance_to_route_m"] < 0.01
    assert forward["nearest_route_lon"] == pytest.approx(-1.0)
    assert forward["route_fraction"] == pytest.approx(0.5)
    assert reverse["route_fraction"] == pytest.approx(0.5)


def test_enriched_toll_section_scopes_station_candidates():
    route = _route()
    station = {"osm_type": "node", "osm_id": 30, "longitude": -0.991,
               "latitude": 41.0, "geometry_points": (), "ref": None}
    # Este nodo está sobre la geometría total, pero fuera del tramo tollways recibido.
    assert match_stations_to_routes((station,), (route,), candidate_radius_m=150)
    assert not match_stations_to_routes((station,), (route,), candidate_radius_m=150,
        toll_segments_by_route_id={route.alternative_id: (((-1.01, 41.0), (-1.005, 41.0)),)})
