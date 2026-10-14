"""Pruebas del ETL con objetos sintéticos; no son datos de carreteras españolas."""

import csv
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
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
from src.tsp.etl.matrices import build_fuel_matrix, load_complete_matrix, rebuild_matrix_snapshot
from src.tsp.etl.matrix_validation import compare_matrix_to_directions
from src.tsp.etl.config import normalize_ors_endpoint


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
    matrix_path = next((tmp_path / "processed" / "ors_snapshots").glob(
        "distance_km_ors_matrix_synthetic_*.csv"))
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
    assert "preference" not in safe_request["body"]
    assert "sources" not in safe_request["body"]
    assert "destinations" not in safe_request["body"]
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


def test_ors_http_budget_counts_retries_and_prevents_extra_transport_calls():
    calls = []
    responses = [
        type("Response", (), {"status": 429, "headers": {"Retry-After": "0"},
                              "read": lambda self: b"", "__enter__": lambda self: self,
                              "__exit__": lambda self, *args: False})(),
        type("Response", (), {"status": 429, "headers": {"Retry-After": "0"},
                              "read": lambda self: b"", "__enter__": lambda self: self,
                              "__exit__": lambda self, *args: False})(),
    ]

    def opener(*args, **kwargs):
        calls.append(args[0])
        return responses.pop(0)

    provider = OpenRouteServiceProvider("synthetic-test-key", opener=opener,
                                        max_http_requests=2, max_retries=3,
                                        min_interval_seconds=0, sleep=lambda _: None)
    with pytest.raises(ProviderError, match="presupuesto total"):
        provider._post("https://fixture.invalid", {})
    assert len(calls) == 2
    assert provider.http_requests_made == 2
    assert provider.http_status_codes == [429, 429]


def test_route_acquisition_requires_http_budget_when_execution_is_enabled():
    from experiments.acquire_tsp_routes import main

    argv = ["acquire_tsp_routes", "--pairs", "madrid:toledo", "--strategy", "fastest",
            "--max-requests", "1", "--execute"]
    with pytest.raises(SystemExit) as error:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("sys.argv", argv)
            main()
    assert error.value.code == 2


def test_route_acquisition_cli_can_select_one_http_attempt_without_retries(monkeypatch, tmp_path):
    from experiments import acquire_tsp_routes

    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured["provider"] = kwargs

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

    class FakeManager:
        def __init__(self, provider, store, **kwargs):
            captured["manager"] = kwargs

        def run(self, requests, **kwargs):
            captured["requests"] = requests
            captured["run"] = kwargs
            return type("Summary", (), {"failed": 0, "__str__": lambda self: "simulated"})()

    monkeypatch.setattr(acquire_tsp_routes, "load_etl_config", lambda path: type(
        "Config", (), {
            "profile": "driving-car", "directions_endpoint": "https://fixture.invalid/v2/directions",
            "timeout_seconds": 1.0, "max_retries": 3,
            "minimum_seconds_between_requests": 0.0,
            "standard_plan_daily_directions_limit": 10,
            "route_catalog": tmp_path / "routes.csv", "raw_responses": tmp_path / "raw",
        })())
    monkeypatch.setattr(acquire_tsp_routes, "OpenRouteServiceProvider", FakeProvider)
    monkeypatch.setattr(acquire_tsp_routes, "RouteStore", FakeStore)
    monkeypatch.setattr(acquire_tsp_routes, "AcquisitionManager", FakeManager)
    monkeypatch.setattr("sys.argv", [
        "acquire_tsp_routes", "--pairs", "madrid:toledo", "--strategy", "fastest",
        "--max-requests", "1", "--max-http-requests", "1", "--max-retries", "0", "--execute",
    ])

    assert acquire_tsp_routes.main() == 0
    assert len(captured["requests"]) == 1
    assert captured["provider"]["max_http_requests"] == 1
    assert captured["provider"]["max_retries"] == 0
    assert captured["run"] == {"max_requests": 1, "refresh": False}


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


def test_acquisition_persists_http_attempts_status_and_timestamp_without_key(tmp_path):
    provider = OpenRouteServiceProvider(
        "synthetic-private-key", opener=lambda *a, **k: _FakeHttpResponse(_ors_response()),
        min_interval_seconds=0, max_http_requests=1, today=lambda: "2026-10-12",
    )
    request = AcquisitionRequest(_city("x", 40, -3), _city("y", 41, -4))
    store = RouteStore(tmp_path / "processed", raw_dir=tmp_path / "raw")
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)

    assert (summary.acquired, summary.http_requests, summary.http_status_codes) == (1, 1, (200,))
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    request_state = next(iter(state["requests"].values()))
    raw_record = json.loads(Path(request_state["raw_file"]).read_text(encoding="utf-8"))
    acquisition = raw_record["request"]["acquisition"]
    assert acquisition["http_requests"] == 1
    assert acquisition["http_status_codes"] == [200]
    acquired_at = datetime.fromisoformat(acquisition["acquired_at"])
    assert acquired_at.tzinfo == timezone.utc
    assert "synthetic-private-key" not in json.dumps(raw_record)


def test_ors_toll_avoidance_uses_documented_array_shape():
    calls = []

    def opener(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        return _FakeHttpResponse(_ors_response())

    provider = OpenRouteServiceProvider("synthetic-test-key", opener=opener, min_interval_seconds=0)
    provider.fetch(AcquisitionRequest(_city("x", 40, -3), _city("y", 41, -4),
                                      strategy="avoid_tolls", avoid_tolls=True))
    assert calls[0]["options"]["avoid_features"] == ["tollways"]


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
    assert config.directions_endpoint == "https://api.heigit.org/openrouteservice/v2/directions"
    assert config.matrix_endpoint == "https://api.heigit.org/openrouteservice/v2/matrix"
    assert config.raw_responses.as_posix() == "data/raw/routes"


def test_ors_endpoint_migration_normalizes_heigit_and_rejects_legacy_host(monkeypatch):
    assert normalize_ors_endpoint("https://api.heigit.org/v2/directions/", "directions") == (
        "https://api.heigit.org/openrouteservice/v2/directions"
    )
    assert normalize_ors_endpoint("https://api.heigit.org/openrouteservice/v2", "directions") == (
        "https://api.heigit.org/openrouteservice/v2/directions"
    )
    with pytest.raises(ValueError, match="obsoleto"):
        normalize_ors_endpoint("https://api.openrouteservice.org/v2/directions", "directions")
    monkeypatch.setenv("ORS_DIRECTIONS_ENDPOINT", "https://api.openrouteservice.org/v2/directions")
    with pytest.raises(ValueError, match="obsoleto"):
        load_etl_config()
    monkeypatch.setenv("ORS_DIRECTIONS_ENDPOINT", "https://fixture.invalid/custom/directions")
    assert load_etl_config().directions_endpoint == "https://fixture.invalid/custom/directions"


def test_ors_endpoint_rejects_embedded_credentials_and_duplicate_heigit_path():
    with pytest.raises(ValueError, match="credenciales"):
        normalize_ors_endpoint("https://user:secret@api.heigit.org/v2/directions", "directions")
    with pytest.raises(ValueError, match="duplica"):
        normalize_ors_endpoint(
            "https://api.heigit.org/openrouteservice/v2/openrouteservice/directions", "directions"
        )


def test_routes_plan_shows_effective_endpoint_without_credentials(tmp_path, monkeypatch, capsys):
    from experiments import acquire_tsp_routes

    config = type("Config", (), {
        "profile": "driving-car",
        "directions_endpoint": "https://api.heigit.org/openrouteservice/v2/directions",
        "timeout_seconds": 30.0,
        "route_catalog": tmp_path / "routes.csv",
        "raw_responses": tmp_path / "raw",
    })()
    monkeypatch.setattr(acquire_tsp_routes, "load_etl_config", lambda _path: config)
    monkeypatch.setattr("sys.argv", [
        "acquire_tsp_routes", "--pairs", "madrid:toledo", "--strategy", "fastest",
        "--extra-info", "tollways,waycategory", "--max-requests", "1",
        "--max-http-requests", "1", "--max-retries", "0",
    ])
    assert acquire_tsp_routes.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["effective_endpoint"] == (
        "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
    )
    assert plan["requests"][0]["extra_info"] == ["tollways", "waycategory"]
    assert plan["max_http_requests"] == 1 and plan["max_retries"] == 0
    assert "ORS_API_KEY" not in json.dumps(plan)


def test_project_fuel_config_has_verified_bulletin_price_and_source_hash():
    economics = load_fuel_economics()
    assert [economics.consumption(case) for case in ("low", "reference", "high")] == [5.3, 5.4, 5.5]
    assert economics.price_eur_per_liter == pytest.approx(1.8490983979999999)
    assert economics.price_status == "verified_official_bulletin"
    assert economics.price_source_unit == "EUR/1000 L"
    assert economics.price_source_cell == "B28"
    assert economics.price_source_sha256 == sha256(Path(economics.price_source_file).read_bytes()).hexdigest().upper()


def test_official_fuel_price_calculates_synthetic_100km_route_and_both_models():
    economics = load_fuel_economics()
    price = economics.price_eur_per_liter
    hundred_km = replace(_alternative("x", "y", "one-hundred"), distance_km=100.0)
    enriched_100km = apply_fuel_economics((hundred_km,), economics)[0]
    expected_100km = 100.0 / 100.0 * 5.4 * price
    assert enriched_100km.fuel_cost_eur == pytest.approx(expected_100km)
    cities = (_city("x", 40, -3), _city("y", 41, -4))
    raw = (
        replace(_alternative("x", "y", "fast-xy", duration=1,
                             toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fastest="fast-xy"),
                distance_km=10.0),
        replace(_alternative("x", "y", "shorter-xy", duration=2,
                             toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0, fastest="fast-xy"),
                distance_km=8.0),
        replace(_alternative("y", "x", "fast-yx", duration=1,
                             toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll=0),
                distance_km=10.0),
    )
    routes = apply_fuel_economics(raw, economics)
    model_a = AlternativeTSPProblem(cities, routes, 0, mode="fastest").evaluate_route((0, 1))
    model_b = AlternativeTSPProblem(cities, routes, 0, mode="economic").evaluate_route((0, 1))
    assert model_a.fuel_cost_eur == pytest.approx(20.0 / 100 * 5.4 * price)
    assert model_b.fuel_cost_eur == pytest.approx(18.0 / 100 * 5.4 * price)


def test_national_matrix_provider_uses_one_full_ordered_request_and_public_endpoint():
    cities = load_city_catalog()
    size = len(cities)
    distances = [[0 if i == j else 1000 + i * size + j for j in range(size)]
                 for i in range(size)]
    durations = [[0 if i == j else 3600 + i * size + j for j in range(size)]
                 for i in range(size)]
    response = {"distances": distances, "durations": durations,
                "sources": [{"location": [city.longitude + 0.001, city.latitude + 0.001]}
                            for city in cities]}
    calls = []

    def opener(request, timeout):
        calls.append(request)
        return _FakeHttpResponse(response)

    provider = OpenRouteServiceProvider(
        "synthetic-test-key", profile="driving-car",
        matrix_endpoint="https://api.heigit.org/openrouteservice/v2/matrix",
        max_http_requests=1, max_retries=0, opener=opener, min_interval_seconds=0,
    )
    safe_request, raw, normalized = provider.fetch_matrix(cities)
    assert len(calls) == provider.http_requests_made == 1
    assert calls[0].full_url == "https://api.heigit.org/openrouteservice/v2/matrix/driving-car"
    assert safe_request["city_order"] == [city.city_id for city in cities]
    assert safe_request["units"] == {"distance": "km", "duration": "h"}
    assert len(safe_request["body"]["locations"]) == 47
    assert "sources" not in safe_request["body"] and "destinations" not in safe_request["body"]
    assert "preference" not in safe_request["body"]
    assert len(normalized["distance_km"]) == 47
    assert sum(len(row) for row in normalized["distance_km"]) == 2209
    assert normalized["distance_km"][0][1] != normalized["distance_km"][1][0]
    assert normalized["distance_km"][0][1] == pytest.approx(distances[0][1] / 1000)
    assert raw["sources"][0]["location"][0] == pytest.approx(cities[0].longitude + 0.001)


def test_matrix_plan_for_all_cities_is_offline_and_reports_request_limits(monkeypatch, capsys, tmp_path):
    from experiments.acquire_tsp_matrix import main

    monkeypatch.setattr("sys.argv", ["acquire_tsp_matrix", "--all-cities", "--max-cells", "3500",
                                     "--max-http-requests", "1", "--max-retries", "0",
                                     "--store", str(tmp_path / "routes"),
                                     "--raw-dir", str(tmp_path / "raw")])
    assert main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["network_access_performed"] is False
    assert plan["http_requests"] == plan["max_http_requests"] == 1
    assert plan["max_retries"] == 0
    assert plan["dimensions"] == [47, 47]
    assert plan["cell_count_including_diagonal"] == 2209
    assert plan["directed_arcs_excluding_diagonal"] == 2162
    assert plan["sources_and_destinations"] == "all locations (parameters omitted)"
    assert plan["request_body"]["units"] == "m"


@pytest.mark.parametrize("response", [
    {"distances": [[0, float("nan")], [1, 0]], "durations": [[0, 1], [1, 0]]},
    {"distances": [[0, -1], [1, 0]], "durations": [[0, 1], [1, 0]]},
    {"distances": [[1, 1], [1, 0]], "durations": [[0, 1], [1, 0]]},
])
def test_matrix_parser_rejects_nonfinite_negative_or_nonzero_diagonal(response):
    with pytest.raises(ProviderError, match="diagonal inválida"):
        parse_ors_matrix(response, 2)


def test_fuel_matrix_is_reconstructed_offline_without_toll_or_total_cost(tmp_path):
    ids = ["x", "y"]
    distance_path = tmp_path / "distance_km.csv"
    with distance_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["city_id", *ids])
        writer.writerow(["x", 0, 100])
        writer.writerow(["y", 120, 0])
    economics = load_fuel_economics()
    target = build_fuel_matrix(distance_path, tmp_path / "fuel_cost_eur.csv", ids, economics)
    fuel = load_complete_matrix(target, ids)
    expected = 5.4 * economics.price_eur_per_liter
    assert fuel[0, 1] == pytest.approx(expected)
    assert fuel[1, 0] == pytest.approx(1.2 * expected)
    manifest = json.loads(target.with_suffix(".csv.manifest.json").read_text(encoding="utf-8"))
    assert manifest["tolls_included"] is False
    assert manifest["economic_total_created"] is False
    assert manifest["distance_matrix_file"] == distance_path.as_posix()
    assert manifest["distance_matrix_sha256"] == sha256(distance_path.read_bytes()).hexdigest()
    assert manifest["fuel_matrix_sha256"] == sha256(target.read_bytes()).hexdigest()


def test_matrix_snapshot_rebuilds_offline_and_checks_response_hash(tmp_path):
    response = {
        "distances": [[0, 12500], [13200, 0]],
        "durations": [[0, 3600], [4200, 0]],
        "metadata": {"timestamp": 1791861282096, "attribution": "synthetic attribution"},
    }
    response_hash = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    source = tmp_path / "raw_snapshot.json"
    payload = {
        "request_id": "synthetic-matrix",
        "provider": "synthetic-test",
        "request": {"url": "https://example.invalid/v2/matrix/driving-car",
                    "body": {"units": "m", "metrics": ["distance", "duration"]},
                    "city_order": ["x", "y"]},
        "response": response,
        "city_order": ["x", "y"],
        "response_sha256": response_hash,
        "acquired_at": "2026-10-12T00:00:00+00:00",
    }
    source.write_text(json.dumps(payload), encoding="utf-8")

    paths = rebuild_matrix_snapshot(source, tmp_path / "rebuilt", ["x", "y"])
    assert load_complete_matrix(paths["distance_km"], ["x", "y"]).tolist() == [[0, 12.5], [13.2, 0]]
    times = load_complete_matrix(paths["time_hours"], ["x", "y"])
    assert times[0, 0] == 0 and times[0, 1] == pytest.approx(1)
    assert times[1, 0] == pytest.approx(4200 / 3600) and times[1, 1] == 0
    manifest = json.loads((tmp_path / "rebuilt" / "matrix_manifest_raw_snapshot.json").read_text())
    assert manifest["rebuild_method"] == "offline_from_verified_raw_snapshot"
    assert manifest["response_sha256"] == response_hash
    assert manifest["units"] == {"distance_km": "km", "time_hours": "h"}
    assert manifest["matrices"]["distance_km"]["sha256"] == sha256(paths["distance_km"].read_bytes()).hexdigest()

    payload["response"]["distances"][0][1] += 1
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        rebuild_matrix_snapshot(source, tmp_path / "tampered", ["x", "y"])


def test_matrix_direction_comparison_uses_fastest_records_and_reports_percentages():
    fastest = _alternative("x", "y", "fast", duration=2)
    nonfast = replace(_alternative("x", "y", "alt", duration=3), fastest_route_id="fast")
    comparison = compare_matrix_to_directions(["x", "y"], [[0, 12], [15, 0]],
                                              [[0, 2.2], [3, 0]], (fastest, nonfast))
    assert len(comparison) == 1
    assert comparison[0].origin_id == "x"
    assert comparison[0].absolute_distance_difference_km == pytest.approx(2)
    assert comparison[0].distance_difference_percent == pytest.approx(20)
    assert comparison[0].absolute_duration_difference_hours == pytest.approx(0.2)
    assert comparison[0].duration_difference_percent == pytest.approx(10)


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
