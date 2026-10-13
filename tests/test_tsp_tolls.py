"""Pruebas sintéticas del inventario y tarifas de peajes; no son datos reales."""

import csv
import json

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl import (
    BoundingBox, OverpassCatalogStore, OverpassClient, RouteTollSection, TollTariff, apply_toll_assessment,
    assess_route_tolls, import_official_tariffs_csv, load_infrastructure_catalog,
    match_infrastructure_to_route, match_route_alternatives_to_infrastructure,
    parse_overpass_response, save_infrastructure_catalog,
)
from src.tsp.etl.toll_tariffs import TARIFF_FIELDS


def _overpass_fixture():
    return {"elements": [
        {"type": "node", "id": 101, "lat": 40.0001, "lon": -3.995,
         "tags": {"barrier": "toll_booth", "name": "Estación sintética", "operator": "Prueba",
                  "ref": "A-TEST", "direction": "north"}},
        {"type": "way", "id": 202, "geometry": [{"lat": 40.0, "lon": -4.0},
                                                          {"lat": 40.0, "lon": -3.99}],
         "tags": {"toll": "yes", "ref": "AP-TEST", "oneway": "yes"}},
        {"type": "node", "id": 303, "lat": 41.0, "lon": -4.0,
         "tags": {"amenity": "fuel"}},
    ]}


def _tariff(**changes):
    fields = dict(
        tariff_id="fixture-1", operator="Operador sintético", road="AP-TEST",
        entry_station="Entrada A", exit_station="Salida B", direction="A-B",
        vehicle_category="ligero", amount_eur=3.25, valid_from="2026-01-01",
        valid_through="2026-12-31", source_url="https://fixture.invalid/tariffs.pdf",
        published_on="2025-12-20", acquired_on="2026-10-12", payment_conditions="tarifa general",
        verification_status="verificado_con_peaje", notes="fixture de prueba",
    )
    fields.update(changes)
    return TollTariff(**fields)


def _route():
    return RouteAlternative(
        "x", "y", "route-xy", "route-xy", 10, 1,
        TollStatus.UNKNOWN, None, "synthetic", "1", "car", "fixture", "2026-10-12",
    )


def _section(entry="Entrada A", exit="Salida B", *, verified=True):
    return RouteTollSection("section-1", "Operador sintético", "AP-TEST", entry, exit, "A-B", verified,
                            ("station-pair-checked",))


def test_bounding_box_limited_and_query_selects_toll_tags():
    query = BoundingBox(39.9, -4.1, 40.1, -3.9).overpass_query()
    assert 'nwr["barrier"="toll_booth"]' in query
    assert 'nwr["highway"="toll_gantry"]' in query
    assert 'nwr["toll"="yes"]' in query
    with pytest.raises(ValueError, match="demasiado amplio"):
        BoundingBox(30, -10, 31.1, -9)


def test_overpass_client_posts_one_bounded_query_with_fake_transport():
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(_overpass_fixture()).encode()

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response()

    records = OverpassClient(opener=opener).fetch_bbox(BoundingBox(39.9, -4.1, 40.1, -3.9))
    assert len(calls) == 1
    assert calls[0][0].method == "POST"
    assert {record.stable_id for record in records} == {"osm:node/101", "osm:way/202"}


def test_overpass_store_reuses_valid_cache_and_refreshes_only_explicitly(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def fetch_bbox_payload(self, bbox):
            self.calls += 1
            return _overpass_fixture()

    client = FakeClient()
    store = OverpassCatalogStore(tmp_path)
    bbox = BoundingBox(39.9, -4.1, 40.1, -3.9)
    initial, fetched = store.get_or_fetch(client, bbox)
    cached, fetched_again = store.get_or_fetch(client, bbox)
    assert fetched is True and fetched_again is False
    assert client.calls == 1
    assert initial == cached
    assert list((tmp_path / "raw" / "tolls").glob("overpass_*.json"))
    assert list((tmp_path / "processed" / "tolls").glob("*.metadata.json"))
    refreshed, refreshed_flag = store.get_or_fetch(client, bbox, refresh=True)
    assert refreshed_flag is True and client.calls == 2
    assert [record.stable_id for record in refreshed] == [record.stable_id for record in initial]
    assert refreshed[0].acquired_at != initial[0].acquired_at


def test_parse_keeps_osm_identity_tags_coordinates_and_provenance():
    records = parse_overpass_response(_overpass_fixture(), acquired_at="2026-10-12T10:00:00+00:00")
    point, road = records
    assert point.infrastructure_type == "toll_booth"
    assert (point.geometry_lon_lat, point.name, point.operator, point.road_reference, point.direction) == (
        ((-3.995, 40.0001),), "Estación sintética", "Prueba", "A-TEST", "north"
    )
    assert dict(road.tags)["oneway"] == "yes"
    assert point.source == "OpenStreetMap/Overpass API"
    assert point.acquired_at == "2026-10-12T10:00:00+00:00"


def test_geojson_inventory_roundtrip_shape_and_duplicate_guard(tmp_path):
    records = parse_overpass_response(_overpass_fixture(), acquired_at="2026-10-12T10:00:00+00:00")
    path = tmp_path / "inventory.geojson"
    save_infrastructure_catalog(path, records)
    geojson = json.loads(path.read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"][0]["id"] == "osm:node/101"
    assert load_infrastructure_catalog(path) == records
    with pytest.raises(ValueError, match="duplicada"):
        save_infrastructure_catalog(path, [records[0], records[0]])


def test_route_matching_is_only_candidate_and_preserves_route_order():
    features = parse_overpass_response(_overpass_fixture(), acquired_at="2026-10-12T10:00:00+00:00")
    route = ((-4.0, 40.0), (-3.99, 40.0))
    matches = match_infrastructure_to_route("route-xy", route, features, radius_m=30)
    assert {match.infrastructure_id for match in matches} == {"osm:node/101", "osm:way/202"}
    assert all(match.confidence == "candidato_proximidad" for match in matches)
    assert matches[0].route_fraction <= matches[1].route_fraction
    assert "no prueba el sentido de cobro" in matches[0].direction_evidence


def test_route_match_checks_polyline_crossing_not_only_feature_vertices():
    crossing_way = parse_overpass_response({"elements": [{
        "type": "way", "id": 909,
        "geometry": [{"lat": 39.99, "lon": -3.995}, {"lat": 40.01, "lon": -3.995}],
        "tags": {"toll": "yes", "ref": "AP-TEST"},
    }]}, acquired_at="2026-10-12T10:00:00+00:00")
    matches = match_infrastructure_to_route("route", ((-4.0, 40.0), (-3.99, 40.0)), crossing_way, radius_m=5)
    assert len(matches) == 1
    assert matches[0].minimum_distance_m == pytest.approx(0)


def test_offline_join_accepts_local_route_alternatives_and_requires_geometries():
    feature = parse_overpass_response(_overpass_fixture(), acquired_at="2026-10-12T10:00:00+00:00")
    route = RouteAlternative(
        "x", "y", "route-xy", "route-xy", 10, 1, TollStatus.UNKNOWN, None,
        "synthetic", "1", "car", "fixture", "2026-10-12",
        geometry_lon_lat=((-4.0, 40.0), (-3.99, 40.0)),
    )
    matches = match_route_alternatives_to_infrastructure([route], feature, radius_m=30)
    assert matches
    assert {match.route_id for match in matches} == {"route-xy"}
    route_without_geometry = RouteAlternative(
        "x", "y", "route-no-geometry", "route-no-geometry", 10, 1, TollStatus.UNKNOWN, None,
        "synthetic", "1", "car", "fixture", "2026-10-12",
    )
    with pytest.raises(ValueError, match="faltan geometrías"):
        match_route_alternatives_to_infrastructure([route_without_geometry], feature)


def test_match_rejects_bad_route_and_invalid_feature_distance():
    with pytest.raises(ValueError, match="al menos dos"):
        match_infrastructure_to_route("r", [(-4, 40)], [], radius_m=20)
    with pytest.raises(ValueError, match="route_id"):
        match_infrastructure_to_route("", [(-4, 40), (-3, 40)], [])


def test_tariff_csv_import_validates_schema_and_normalizes_decimal_comma(tmp_path):
    path = tmp_path / "tarifas.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TARIFF_FIELDS)
        writer.writeheader()
        row = {field: getattr(_tariff(), field) for field in TARIFF_FIELDS}
        row["amount_eur"] = "3,25"
        writer.writerow(row)
    records = import_official_tariffs_csv(path)
    assert records[0].amount_eur == 3.25
    assert records[0].applies_on("2026-10-12")
    assert not records[0].applies_on("2027-01-01")


def test_assessment_matches_entry_exit_direction_vehicle_and_validity():
    section = _section()
    result = assess_route_tolls("route-xy", [section], [_tariff()], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True,
                                inventory_source="synthetic://route-coverage")
    assert result.status is TollStatus.VERIFIED_WITH_TOLL
    assert result.amount_eur == 3.25
    assert result.tariff_ids == ("fixture-1",)
    assert result.unresolved_sections == ()


def test_tariff_mismatch_or_expired_record_remains_unknown():
    section = _section(exit="Salida C")
    result = assess_route_tolls("route-xy", [section], [_tariff()], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True,
                                inventory_source="synthetic://route-coverage")
    assert result.status is TollStatus.UNKNOWN
    assert result.amount_eur is None
    reversed_section = _section(entry="Salida B", exit="Entrada A")
    reversed_result = assess_route_tolls("route-xy", [reversed_section], [_tariff()],
                                        vehicle_category="ligero", as_of="2026-10-12", inventory_complete=True,
                                        inventory_source="synthetic://route-coverage")
    assert reversed_result.amount_eur is None
    expired = _tariff(valid_through="2026-10-11")
    result = assess_route_tolls("route-xy", [_section()], [expired], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True,
                                inventory_source="synthetic://route-coverage")
    assert result.amount_eur is None


def test_unverified_route_section_never_gets_a_tariff():
    section = _section(verified=False)
    result = assess_route_tolls("route-xy", [section], [_tariff()], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True,
                                inventory_source="synthetic://route-coverage")
    assert result.status is TollStatus.UNKNOWN
    assert result.amount_eur is None
    assert result.unresolved_sections == ("section-1",)


def test_free_toll_requires_complete_inventory_and_explicit_source():
    result = assess_route_tolls("route-xy", [], [], vehicle_category="ligero", as_of="2026-10-12")
    assert result.status is TollStatus.UNKNOWN and result.amount_eur is None
    verified = assess_route_tolls("route-xy", [], [], vehicle_category="ligero", as_of="2026-10-12",
                                  inventory_complete=True, no_toll_source="https://official.invalid/network")
    assert verified.status is TollStatus.VERIFIED_WITHOUT_TOLL
    assert verified.amount_eur == 0


def test_explicit_zero_tariff_is_verified_free_for_its_exact_station_pair():
    free = _tariff(amount_eur=0, verification_status="verificado_sin_peaje")
    section = _section()
    result = assess_route_tolls("route-xy", [section], [free], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True,
                                inventory_source="synthetic://route-coverage")
    assert result.status is TollStatus.VERIFIED_WITHOUT_TOLL
    assert result.amount_eur == 0


def test_duplicate_sections_are_rejected_to_prevent_double_charge():
    section = _section()
    with pytest.raises(ValueError, match="duplicadas"):
        assess_route_tolls("route-xy", [section, section], [_tariff()], vehicle_category="ligero",
                           as_of="2026-10-12")


def test_known_tariff_does_not_become_route_total_without_complete_coverage():
    result = assess_route_tolls("route-xy", [_section()], [_tariff()], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=False)
    assert result.status is TollStatus.UNKNOWN
    assert result.amount_eur is None


def test_complete_route_coverage_requires_a_source():
    result = assess_route_tolls("route-xy", [_section()], [_tariff()], vehicle_category="ligero",
                                as_of="2026-10-12", inventory_complete=True)
    assert result.status is TollStatus.UNKNOWN
    assert result.amount_eur is None


def test_verified_route_section_requires_auditable_evidence():
    with pytest.raises(ValueError, match="evidencia registrada"):
        RouteTollSection("section-1", "Operador sintético", "AP-TEST", "Entrada A", "Salida B",
                         "A-B", True, ())


def test_route_projection_is_immutable_and_keeps_unknown_when_unresolved():
    route = _route()
    unknown = assess_route_tolls("route-xy", [], [], vehicle_category="ligero", as_of="2026-10-12")
    assert apply_toll_assessment(route, unknown) is route
    section = _section()
    verified = assess_route_tolls("route-xy", [section], [_tariff()], vehicle_category="ligero",
                                  as_of="2026-10-12", inventory_complete=True,
                                  inventory_source="synthetic://route-coverage")
    updated = apply_toll_assessment(route, verified)
    assert route.toll_status is TollStatus.UNKNOWN
    assert updated.toll_status is TollStatus.VERIFIED_WITH_TOLL
    assert updated.toll_cost_eur == 3.25
    assert updated.toll_valid_from == updated.toll_valid_through == "2026-10-12"


def test_tariff_rejects_zero_as_paid_and_invalid_dates():
    with pytest.raises(ValueError, match="importe cero"):
        _tariff(amount_eur=0)
    with pytest.raises(ValueError):
        _tariff(valid_from="2026-12-31", valid_through="2026-01-01")
