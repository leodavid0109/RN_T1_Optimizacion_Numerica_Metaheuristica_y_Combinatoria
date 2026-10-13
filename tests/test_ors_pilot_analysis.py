"""Pruebas sintéticas del análisis comparativo del piloto; no contienen rutas españolas reales."""

import json

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.cities import City
from src.tsp.etl import RouteStore
from src.tsp.etl.economics import FuelEconomics, apply_fuel_economics
from src.tsp.etl.pilot_analysis import analyze_ors_pilot, write_ors_pilot_report
from src.tsp.models import AlternativeTSPProblem, UnverifiableCostError


def _city(city_id: str, lat: float, lon: float) -> City:
    return City(city_id, city_id.title(), city_id, lat, lon, "synthetic://city", "2026-10-12",
                "verificada", "coordenada sintética de prueba")


def _route(origin: str, destination: str, alternative_id: str, fastest_id: str,
           distance: float, duration: float, geometry, *, toll_status=TollStatus.UNKNOWN,
           toll_cost=None) -> RouteAlternative:
    return RouteAlternative(
        origin, destination, alternative_id, fastest_id, distance, duration,
        toll_status, toll_cost, "openrouteservice", "synthetic-1", "driving-car",
        "https://fixture.invalid/directions", "2026-10-12",
        network_data_version="synthetic-graph", geometry_lon_lat=tuple(geometry),
        toll_source="synthetic://toll" if toll_status is not TollStatus.UNKNOWN else None,
        toll_checked_on="2026-10-12" if toll_status is not TollStatus.UNKNOWN else None,
    )


def _economics() -> FuelEconomics:
    return FuelEconomics(
        "synthetic-car", "gasoline_95", {"low": 5.3, "reference": 5.4, "high": 5.5},
        "supuesto sintético", "synthetic://consumption", 1.849098397,
        "synthetic://price", "2026-10-08", "2026-10-12", "2026-10-12",
        "synthetic_test",
    )


def _persist_observation(store, request_id, route, strategy, origin, destination):
    options = {"avoid_features": ["tollways"]} if strategy == "avoid_tolls" else None
    body = {"coordinates": [[origin.longitude, origin.latitude], [destination.longitude, destination.latitude]],
            "preference": "fastest"}
    if options:
        body["options"] = options
    safe_request = {
        "method": "POST", "url": "https://fixture.invalid/directions",
        "body": body,
        "acquisition": {"acquired_at": "2026-10-12T12:00:00+00:00", "http_requests": 1,
                        "http_status_codes": [200]},
    }
    feature = {
        "type": "Feature",
        "properties": {"summary": {"distance": route.distance_km * 1000,
                                     "duration": route.duration_hours * 3600}},
        "geometry": {"type": "LineString", "coordinates": [list(point) for point in route.geometry_lon_lat]},
    }
    response = {"type": "FeatureCollection", "features": [feature],
                "metadata": {"engine": {"version": "synthetic-1"}}}
    store.save_success(request_id, safe_request, response, [route])


def _fixture_store(tmp_path, *, same_geometry=False):
    origin, destination = _city("x", 1, 0), _city("y", 2, 1)
    fast_geometry = ((0.0, 1.0), (0.4, 1.5), (1.0, 2.0))
    avoid_geometry = fast_geometry if same_geometry else ((0.0, 1.0), (0.6, 1.5), (1.0, 2.0))
    fast_id = "fast-xy"
    fast = _route("x", "y", fast_id, fast_id, 10.0, 1.0, fast_geometry)
    avoid_distance, avoid_duration = (10.0, 1.0) if same_geometry else (12.0, 2.0)
    avoid = _route("x", "y", "avoid-xy", fast_id, avoid_distance, avoid_duration, avoid_geometry)
    store = RouteStore(tmp_path / "processed", raw_dir=tmp_path / "raw")
    _persist_observation(store, "synthetic:fast:x-y", fast, "fastest", origin, destination)
    _persist_observation(store, "synthetic:avoid:x-y", avoid, "avoid_tolls", origin, destination)
    return origin, destination, fast, avoid, store


def test_pilot_analysis_associates_strategies_and_calculates_deltas(tmp_path):
    origin, destination, fast, avoid, store = _fixture_store(tmp_path)
    rows = analyze_ors_pilot([origin, destination], store, _economics(), pairs=[("x", "y")])
    row = rows[0]
    fuel_delta = 12 / 100 * 5.4 * 1.849098397 - 10 / 100 * 5.4 * 1.849098397
    assert row["fastest_alternative_id"] == fast.alternative_id
    assert row["avoid_tolls_alternative_id"] == avoid.alternative_id
    assert row["distance_delta_km"] == pytest.approx(2)
    assert row["distance_delta_percent"] == pytest.approx(20)
    assert row["time_delta_minutes"] == pytest.approx(60)
    assert row["time_delta_percent"] == pytest.approx(100)
    assert row["fastest_fuel_eur"] == pytest.approx(10 / 100 * 5.4 * 1.849098397)
    assert row["fuel_delta_eur"] == pytest.approx(fuel_delta)
    assert row["geometries_equal"] is False
    assert row["fastest_toll_status"] == "desconocido"
    assert row["fastest_toll_eur"] is None
    assert row["avoid_tolls_toll_status"] == "desconocido"
    assert row["avoid_tolls_toll_eur"] is None
    for hour_value in (10, 25, 50):
        expected = hour_value * (2 - 1) + fuel_delta
        assert row[f"toll_saving_required_at_{hour_value}_eur"] == pytest.approx(expected)


def test_pilot_analysis_detects_equal_geometry_and_writes_local_report(tmp_path):
    origin, destination, _, _, store = _fixture_store(tmp_path, same_geometry=True)
    rows = analyze_ors_pilot([origin, destination], store, _economics(), pairs=[("x", "y")])
    assert rows[0]["geometries_equal"] is True
    csv_path, markdown_path = write_ors_pilot_report(rows, tmp_path / "report")
    assert csv_path.is_file() and markdown_path.is_file()
    assert "ahorro de peaje requerido" in markdown_path.read_text(encoding="utf-8")


def test_pilot_analysis_rejects_wrong_arc_association(tmp_path):
    origin, destination, _, _, store = _fixture_store(tmp_path)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    key = next(key for key in state["requests"] if "fast:x-y" in key)
    record = state["requests"][key]
    raw_path = record["raw_file"]
    raw = json.loads(open(raw_path, encoding="utf-8").read())
    raw["request"]["body"]["coordinates"][0] = [99.0, 99.0]
    open(raw_path, "w", encoding="utf-8").write(json.dumps(raw))
    with pytest.raises(ValueError, match="coordenadas de solicitud"):
        analyze_ors_pilot([origin, destination], store, _economics(), pairs=[("x", "y")])


def test_unknown_tolls_remain_unverifiable_in_existing_tsp_contract(tmp_path):
    origin, destination, fast, avoid, store = _fixture_store(tmp_path)
    records = store.load_alternatives()
    assert len(records) == 2
    assert {record.toll_status for record in records} == {TollStatus.UNKNOWN}
    assert all(record.toll_cost_eur is None for record in records)
    # El registro del piloto es parcial: la instancia nacional requiere los 2.162 arcos.
    # En una instancia sintética completa se demuestra que la API del contrato conserva ambas.
    synthetic_back_fast = _route("y", "x", "fast-yx", "fast-yx", 11, 1.2,
                                 ((1, 2), (0.5, 1.5), (0, 1)),
                                 toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll_cost=0)
    synthetic_back_avoid = _route("y", "x", "avoid-yx", "fast-yx", 12, 1.5,
                                  ((1, 2), (0.6, 1.5), (0, 1)),
                                  toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll_cost=0)
    unknown_back_fast = _route("y", "x", "unknown-fast-yx", "unknown-fast-yx", 11, 1.2,
                               ((1, 2), (0.5, 1.5), (0, 1)))
    unknown_back_avoid = _route("y", "x", "unknown-avoid-yx", "unknown-fast-yx", 12, 1.5,
                                ((1, 2), (0.6, 1.5), (0, 1)))
    # Solo el lado sintético usa tarifas verificadas para poder ejercitar ambos evaluadores.
    from dataclasses import replace
    known_forward = [replace(record, toll_status=TollStatus.VERIFIED_WITHOUT_TOLL,
                             toll_cost_eur=0, toll_source="synthetic://verified", toll_checked_on="2026-10-12")
                     for record in (fast, avoid)]
    known_complete = apply_fuel_economics([*known_forward, synthetic_back_fast, synthetic_back_avoid],
                                          _economics())
    problem_a = AlternativeTSPProblem([origin, destination], known_complete, 10, mode="fastest")
    result_a = problem_a.evaluate_route((0, 1))
    assert result_a.selected_alternative_ids == ("fast-xy", "fast-yx")
    problem_b = AlternativeTSPProblem([origin, destination], known_complete, 10, mode="economic")
    assert len(problem_b.alternatives_by_arc[("x", "y")]) == 2
    assert len(problem_b.selected_alternatives_for_route((0, 1))) == 2

    unknown_complete = apply_fuel_economics([*records, unknown_back_fast, unknown_back_avoid], _economics())
    problem_unknown = AlternativeTSPProblem([origin, destination], unknown_complete, 10, mode="fastest")
    with pytest.raises(UnverifiableCostError):
        problem_unknown.evaluate_route((0, 1))
