"""Pruebas del ETL con objetos sintéticos; no son datos de carreteras españolas."""

import csv
import json
from pathlib import Path

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.cities import City, load_city_catalog
from src.tsp.models import AlternativeTSPProblem
from src.tsp.etl import (
    AcquisitionManager, AcquisitionRequest, OpenRouteServiceProvider, ProviderError,
    RouteStore, apply_fuel_economics, build_matrix_files, load_etl_config, load_fuel_economics,
    parse_ors_geojson, parse_ors_matrix,
)
from src.tsp.etl.matrices import load_complete_matrix


def _city(city_id: str, lat: float, lon: float) -> City:
    return City(city_id, city_id, city_id, lat, lon, "synthetic://test", "2026-10-12",
                "verificada", "coordenada sintética de prueba")


def _alternative(origin: str, destination: str, alt_id: str, *, duration=1.0,
                 toll_status=TollStatus.UNKNOWN, toll=None, fuel=None, fastest=None) -> RouteAlternative:
    return RouteAlternative(
        origin, destination, alt_id, fastest or alt_id, 10.0, duration, toll_status, toll,
        "test", "1", "synthetic", "synthetic://fixture", "2026-10-12",
        geometry_lon_lat=((0.0, 0.0), (1.0, 1.0)),
        fuel_consumption_l_per_100km=1.0 if fuel is not None else None,
        fuel_consumption_source="synthetic://fuel" if fuel is not None else None,
        fuel_price_eur_per_l=1.0 if fuel is not None else None,
        fuel_price_reference="synthetic test" if fuel is not None else None,
        vehicle_configuration="synthetic vehicle" if fuel is not None else None,
        toll_source="synthetic://toll" if toll_status is not TollStatus.UNKNOWN else None,
        toll_checked_on="2026-10-12" if toll_status is not TollStatus.UNKNOWN else None,
    )


def _ors_response():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"summary": {"distance": 10000, "duration": 3600}},
             "geometry": {"type": "LineString", "coordinates": [[-3.0, 40.0], [-4.0, 41.0]]}},
            {"type": "Feature", "properties": {"summary": {"distance": 12000, "duration": 1800}},
             "geometry": {"type": "LineString", "coordinates": [[-3.0, 40.0], [-5.0, 41.0]]}},
        ],
    }


def test_ors_geojson_parse_converts_units_and_keeps_toll_unknown():
    routes = parse_ors_geojson(_ors_response(), origin_id="x", destination_id="y", request_id="abc",
                               fastest_route_id="fastest-xy",
                               is_primary_fastest=True,
                               strategy="fastest",
                               profile="driving-car", source="https://fixture.invalid", acquired_on="2026-10-12")
    assert routes[0].distance_km == 10
    assert routes[0].duration_hours == 1
    assert routes[0].toll_status is TollStatus.UNKNOWN
    assert routes[0].toll_cost_eur is None
    assert routes[0].fastest_route_id == "fastest-xy"
    assert routes[1].alternative_id == "fastest-xy"
    assert routes[0].geometry_lon_lat[0] == (-3.0, 40.0)


def test_ors_parse_rejects_incomplete_response_and_unverified_coordinates():
    with pytest.raises(ProviderError, match="no contiene"):
        parse_ors_geojson({}, origin_id="x", destination_id="y", request_id="a",
                          fastest_route_id="fast-a", is_primary_fastest=True,
                          strategy="fastest",
                          profile="driving-car", source="fixture", acquired_on="2026-10-12")
    bad_city = City("z", "z", "z", None, None, "synthetic", "2026-10-12", "pendiente", "test")
    with pytest.raises(ValueError, match="coordenada no verificada"):
        AcquisitionRequest(_city("x", 1, 1), bad_city)


def test_ors_matrix_parser_converts_units_and_preserves_asymmetry():
    matrix = parse_ors_matrix({"distances": [[0, 1200], [1100, 0]],
                               "durations": [[0, 3600], [1800, 0]]}, 2)
    assert matrix["distance_km"] == [[0, 1.2], [1.1, 0]]
    assert matrix["time_hours"] == [[0, 1], [0.5, 0]]
    with pytest.raises(ProviderError, match="no cuadrada"):
        parse_ors_matrix({"distances": [[0, None], [1, 0]],
                          "durations": [[0, 1], [1, 0]]}, 2)


def test_matrix_snapshot_persists_raw_response_and_labeled_csv(tmp_path):
    store = RouteStore(tmp_path / "processed", raw_dir=tmp_path / "raw")
    normalized = {"distance_km": [[0, 1.2], [1.1, 0]],
                  "time_hours": [[0, 1], [0.5, 0]]}
    store.save_matrix_snapshot("ors:matrix:synthetic", {"url": "fixture"},
                               {"distances": [[0, 1200], [1100, 0]]}, normalized, ["x", "y"])
    assert len(list((tmp_path / "raw").glob("ors_matrix_synthetic_*.json"))) == 1
    matrix_path = next((tmp_path / "processed").glob("distance_km_ors_matrix_synthetic_*.csv"))
    with matrix_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["city_id", "x", "y"]
    assert rows[1] == ["x", "0", "1.2"]


def test_refresh_preserves_verified_costs_only_when_route_is_identical(tmp_path):
    store = RouteStore(tmp_path)
    verified = _alternative("x", "y", "stable", duration=1,
                            toll_status=TollStatus.VERIFIED_WITH_TOLL, toll=3, fuel=True)
    request = {"url": "fixture"}
    store.save_success("fake:request", request, {"generation": 1}, (verified,))
    incomplete_same_route = _alternative("x", "y", "stable", duration=1)
    store.save_success("fake:request", request, {"generation": 2}, (incomplete_same_route,))
    loaded = store.load_alternatives()[0]
    assert loaded.toll_status is TollStatus.VERIFIED_WITH_TOLL
    assert loaded.toll_cost_eur == 3
    assert loaded.fuel_cost_eur is not None
    assert len(list((tmp_path / "raw").glob("fake_request_*.json"))) == 2

    changed_geometry = RouteAlternative(
        "x", "y", "stable", "stable", 11, 1, TollStatus.UNKNOWN, None, "test", "1", "synthetic",
        "synthetic://fixture", "2026-10-12", geometry_lon_lat=((0.0, 0.0), (2.0, 2.0)),
    )
    store.save_success("fake:request", request, {"generation": 3}, (changed_geometry,))
    current = store.load_alternatives()[0]
    assert current.toll_status is TollStatus.UNKNOWN
    assert current.fuel_cost_eur is None
    assert len(list((tmp_path / "raw" / "catalog_history").glob("*.csv"))) == 1


def test_ors_matrix_provider_uses_mocked_http_and_retains_snapped_metadata():
    cities = (_city("x", 1, 1), _city("y", 2, 2))
    response = {"distances": [[0, 1000], [1200, 0]],
                "durations": [[0, 1800], [2400, 0]],
                "sources": [{"location": [1.1, 1.1]}, {"location": [2.1, 2.1]}]}
    calls = []

    def opener(request, timeout):
        calls.append(request)
        return _FakeHttpResponse(response)

    provider = OpenRouteServiceProvider("test-secret", opener=opener, min_interval_seconds=0)
    safe_request, raw, normalized = provider.fetch_matrix(cities)
    assert safe_request["body"]["locations"] == [[1.0, 1.0], [2.0, 2.0]]
    assert safe_request["body"]["preference"] == "fastest"
    assert normalized["distance_km"] == [[0, 1], [1.2, 0]]
    assert normalized["time_hours"] == [[0, 0.5], [2 / 3, 0]]
    assert raw["sources"][0]["location"] == [1.1, 1.1]
    assert calls[0].get_header("Authorization") == "test-secret"


def test_etl_records_construct_existing_economic_tsp_contract():
    cities = (_city("x", 1, 1), _city("y", 2, 2))
    records = (
        _alternative("x", "y", "xy", duration=1,
                     toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fuel=True),
        _alternative("y", "x", "yx", duration=2,
                     toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fuel=True),
    )
    problem = AlternativeTSPProblem(cities, records, hour_value_eur_per_hour=5, mode="economic")
    result = problem.evaluate_route([0, 1])
    assert result.closed_route == (0, 1, 0)
    assert result.total_time_hours == 3
    assert result.selected_alternative_ids == ("xy", "yx")


def test_missing_ors_key_fails_before_transport():
    called = False

    def opener(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no se debe invocar transporte")

    provider = OpenRouteServiceProvider(api_key="", opener=opener)
    with pytest.raises(ProviderError, match="falta ORS_API_KEY"):
        provider.fetch(AcquisitionRequest(_city("x", 1, 1), _city("y", 2, 2)))
    assert called is False


def test_ors_retries_429_with_retry_after_and_rejects_auth_without_retry():
    sleeps = []
    responses = [
        type("Response", (), {"status": 429, "headers": {"Retry-After": "3"},
                              "read": lambda self: b"", "__enter__": lambda self: self,
                              "__exit__": lambda self, *args: False})(),
        _FakeHttpResponse({"ok": True}),
    ]

    def opener(*args, **kwargs):
        return responses.pop(0)

    provider = OpenRouteServiceProvider("secret", opener=opener, sleep=sleeps.append,
                                        min_interval_seconds=0)
    assert provider._post("https://fixture.invalid", {}) == {"ok": True}
    assert sleeps == [3.0]

    unauthorized = type("Response", (), {"status": 401, "headers": {}, "read": lambda self: b"",
                                           "__enter__": lambda self: self,
                                           "__exit__": lambda self, *args: False})()
    provider = OpenRouteServiceProvider("secret", opener=lambda *a, **k: unauthorized,
                                        sleep=lambda _: pytest.fail("no se debe reintentar"),
                                        min_interval_seconds=0)
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider._post("https://fixture.invalid", {})


class _FakeHttpResponse:
    status = 200
    headers = {}

    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_provider_uses_mock_transport_and_never_stores_api_key(tmp_path):
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return _FakeHttpResponse(_ors_response())

    origin, destination = _city("x", 40, -3), _city("y", 41, -4)
    provider = OpenRouteServiceProvider("test-secret", opener=opener, min_interval_seconds=0,
                                        today=lambda: "2026-10-12")
    request = AcquisitionRequest(origin, destination)
    safe_request, raw, routes = provider.fetch(request)
    assert len(calls) == 1
    assert calls[0][0].get_header("Authorization") == "test-secret"
    assert "test-secret" not in json.dumps(safe_request)
    assert len(routes) == 2
    store = RouteStore(tmp_path)
    store.save_success("ors:" + request.request_id, safe_request, raw, routes)
    assert "test-secret" not in "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert store.request_succeeded("ors:" + request.request_id)
    loaded = store.load_alternatives()
    assert loaded == routes


def test_acquisition_resumes_without_duplicate_calls_and_records_failures(tmp_path):
    class Provider:
        provider_name = "fake"
        calls = 0

        def fetch(self, request):
            self.calls += 1
            route = _alternative(request.origin.city_id, request.destination.city_id, "fast")
            return {"url": "fixture"}, {"mock": True}, (route,)

    provider = Provider()
    store = RouteStore(tmp_path)
    manager = AcquisitionManager(provider, store)
    request = AcquisitionRequest(_city("x", 1, 1), _city("y", 2, 2))
    first = manager.run([request], max_requests=1)
    second = manager.run([request], max_requests=1)
    assert (first.acquired, second.skipped_existing, provider.calls) == (1, 1, 1)
    with pytest.raises(ValueError, match="supera"):
        manager.run([request], max_requests=0)


def test_acquisition_checks_daily_quota_before_any_network_call(tmp_path):
    class Provider:
        provider_name = "quota-test"
        profile = "car"
        calls = 0

        def fetch(self, request):
            self.calls += 1
            return {}, {}, (_alternative(request.origin.city_id, request.destination.city_id, "fast"),)

    provider = Provider()
    request = AcquisitionRequest(_city("x", 1, 1), _city("y", 2, 2))
    reverse = AcquisitionRequest(_city("y", 2, 2), _city("x", 1, 1))
    manager = AcquisitionManager(provider, RouteStore(tmp_path), daily_quota=1)
    with pytest.raises(ValueError, match="cuota restante"):
        manager.run([request, reverse], max_requests=2)
    assert provider.calls == 0


def test_matrix_builder_keeps_direction_and_does_not_turn_unknown_tolls_into_zero(tmp_path):
    cities = (_city("x", 1, 1), _city("y", 2, 2))
    records = (_alternative("x", "y", "xy"), _alternative("y", "x", "yx", duration=2))
    report = build_matrix_files(cities, records, tmp_path, mode="fastest")
    assert report.directed_arc_count == 2
    assert report.complete_toll_arcs == 0
    assert report.economic_matrix_written is False
    assert not (tmp_path / "economic_cost_eur.csv").exists()
    with (tmp_path / "toll_cost_eur.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[1][2] == ""
    assert rows[2][1] == ""
    with pytest.raises(ValueError, match="celdas ausentes"):
        load_complete_matrix(tmp_path / "toll_cost_eur.csv", ["x", "y"])


def test_complete_matrix_is_labeled_ordered_immutable_and_asymmetric(tmp_path):
    cities = (_city("x", 1, 1), _city("y", 2, 2))
    records = (
        _alternative("x", "y", "xy", duration=1, toll_status=TollStatus.VERIFIED_WITHOUT_TOLL,
                     toll=0, fuel=1),
        _alternative("y", "x", "yx", duration=2, toll_status=TollStatus.VERIFIED_WITH_TOLL,
                     toll=2, fuel=1),
    )
    report = build_matrix_files(cities, records, tmp_path, mode="fastest", hour_value_eur_per_hour=10)
    assert report.economic_matrix_written
    matrix = load_complete_matrix(tmp_path / "time_hours.csv", ["x", "y"])
    assert matrix[0, 1] == 1 and matrix[1, 0] == 2
    assert not matrix.flags.writeable
    with pytest.raises(ValueError, match="orden"):
        load_complete_matrix(tmp_path / "time_hours.csv", ["y", "x"])


def test_economic_matrix_selects_local_cheapest_route_and_rejects_missing_costs(tmp_path):
    cities = (_city("x", 1, 1), _city("y", 2, 2))
    fast = _alternative("x", "y", "fast", duration=1,
                        toll_status=TollStatus.VERIFIED_WITH_TOLL, toll=5, fuel=1)
    slow = _alternative("x", "y", "slow", duration=2,
                         toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fuel=1, fastest="fast")
    reverse = _alternative("y", "x", "reverse", duration=1,
                           toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fuel=1)
    build_matrix_files(cities, [fast, slow, reverse], tmp_path / "low", mode="economic", hour_value_eur_per_hour=0)
    build_matrix_files(cities, [fast, slow, reverse], tmp_path / "high", mode="economic", hour_value_eur_per_hour=10)
    low = load_complete_matrix(tmp_path / "low" / "time_hours.csv", ["x", "y"])
    high = load_complete_matrix(tmp_path / "high" / "time_hours.csv", ["x", "y"])
    assert low[0, 1] == 2
    assert high[0, 1] == 1
    with pytest.raises(ValueError, match="costo no verificable"):
        build_matrix_files(cities, [_alternative("x", "y", "unknown"), reverse],
                           tmp_path / "incomplete", mode="economic", hour_value_eur_per_hour=5)


def test_real_catalog_can_be_used_without_any_network_access(tmp_path):
    cities = load_city_catalog()
    assert len(cities) == 47
    # Solo se usa la instancia sintética 2x2 arriba; la matriz nacional no se genera aquí.
    assert not list(tmp_path.iterdir())


def test_project_etl_yaml_is_loaded_and_validated():
    config = load_etl_config()
    assert config.profile == "driving-car"
    assert config.standard_plan_daily_directions_limit == 2000
    assert config.standard_plan_daily_matrix_limit == 500
    assert config.raw_responses.as_posix() == "data/raw/routes"


def test_project_fuel_config_and_sensitivity_keep_unverified_price_pending():
    economics = load_fuel_economics()
    assert [economics.consumption(case) for case in ("low", "reference", "high")] == [5.3, 5.4, 5.5]
    assert economics.price_eur_per_liter is None
    assert economics.price_status == "pending_direct_source_verification"


def test_fuel_configuration_returns_copies_and_supports_sensitivity_without_fabricating_price():
    from src.tsp.etl.economics import FuelEconomics

    route = _alternative("x", "y", "fast")
    values = {"low": 5.3, "reference": 5.4, "high": 5.5}
    pending_config = FuelEconomics("test-car", "gasoline_95", values, "synthetic fixture",
                                   "synthetic://consumption", None, "synthetic://price", "2026-10-08",
                                   None, "2026-10-12", "pending_direct_source_verification")
    pending = apply_fuel_economics((route,), pending_config)[0]
    assert pending is not route
    assert pending.fuel_cost_eur is None
    assert route.fuel_consumption_l_per_100km is None

    priced_config = FuelEconomics("test-car", "gasoline_95", values, "synthetic fixture",
                                  "synthetic://consumption", 1.0, "synthetic://price", "2026-10-08",
                                  "2026-10-12", "2026-10-12", "synthetic_test_only")
    low = apply_fuel_economics((route,), priced_config, scenario="low")[0]
    high = apply_fuel_economics((route,), priced_config, scenario="high")[0]
    assert low.fuel_consumption_l_per_100km == 5.3
    assert high.fuel_consumption_l_per_100km == 5.5
    assert low.fuel_cost_eur < high.fuel_cost_eur
    assert route.fuel_consumption_l_per_100km is None
