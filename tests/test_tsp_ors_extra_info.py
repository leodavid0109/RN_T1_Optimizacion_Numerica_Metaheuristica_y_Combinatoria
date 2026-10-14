"""Respuestas ORS sintéticas: no constituyen evidencia vial real."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket
from urllib.error import HTTPError, URLError

import pytest
import numpy as np

from experiments.acquire_tsp_routes import record_quarantined_failures
from experiments.prioritize_tsp_direction_queue import exclude_quarantined, load_quarantined_pairs
from experiments.analyze_tsp_ors_extras import analyze_saved_routes
from src.tsp.cities import City
from src.tsp.etl.acquisition import AcquisitionManager, AcquisitionRequest
from src.tsp.etl.ors import OpenRouteServiceProvider, ProviderError
from src.tsp.etl.ors_extras import (analyze_geojson_extras, decode_waycategory_mask,
                                    plan_overpass_way_queries)
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_infrastructure import (OverpassCatalogStore, OverpassClient, OverpassError,
                                             overpass_node_ids_query)


def _city(city_id: str, lon: float) -> City:
    return City(city_id, city_id, city_id, 40.0, lon, "synthetic://test", "2026-10-13",
                "verificada", "coordenada sintética")


def _response(*, enriched: bool = True, change_geometry: bool = False) -> dict:
    points = [[-3.0, 40.0], [-3.01, 40.0], [-3.02, 40.0],
              [-3.03, 40.01 if change_geometry else 40.0], [-3.04, 40.0]]
    props = {"summary": {"distance": 3000, "duration": 180},
             "segments": [{"steps": [{"name": "AP-X", "ref": "AP-X", "distance": 3000,
                                        "way_points": [0, 4]}]}]}
    if enriched:
        props["extras"] = {
            "tollways": {"values": [[0, 2, 0], [2, 4, 1]],
                         "summary": [{"value": 0, "distance": 1000},
                                     {"value": 1, "distance": 2000}]},
            "osmId": {"values": [[0, 1, 101], [1, 2, 102], [2, 3, 103], [3, 4, 103]]},
            "waycategory": {"values": [[0, 2, 1], [2, 4, 3]]},
        }
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": props,
         "geometry": {"type": "LineString", "coordinates": points}}]}


class _Response:
    status = 200
    headers = {}

    def __init__(self, payload: dict, headers: dict | None = None):
        self.payload = payload
        self.headers = headers or {}

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_enriched_request_has_new_identity_and_preserves_legacy_id():
    base = AcquisitionRequest(_city("a", -3), _city("b", -4))
    enriched = replace(base, extra_info=("waycategory", "osmid", "tollways"))
    assert enriched.extra_info == ("osmid", "tollways", "waycategory")
    assert enriched.request_id != base.request_id
    assert enriched.fastest_route_id("driving-car") == base.fastest_route_id("driving-car")
    assert replace(enriched, extra_info=("tollways", "waycategory", "osmid")).request_id == enriched.request_id
    with pytest.raises(ValueError, match="únicos"):
        replace(base, extra_info=("tollways", "tollways"))


def test_extra_sections_indices_and_unknown_monetary_toll():
    row = analyze_geojson_extras(_response(), required=("tollways", "osmid", "waycategory"))[0]
    assert row["coverage"] == "complete_cartographic"
    assert row["toll_distance_km"] == 2
    assert row["osm_way_ids"] == [101, 102, 103]
    assert row["toll_sections"][0]["osm_way_ids"] == [103]
    assert row["toll_sections"][0]["start_index"] == 2
    assert row["toll_sections"][0]["end_index"] == 4
    assert row["toll_cost_eur"] is None and row["toll_verification"] == "UNKNOWN"
    assert row["toll_sections"][0]["waycategory_names"] == ["Highway", "Tollways"]
    assert row["toll_sections"][0]["instruction_names"] == ["AP-X"]
    assert row["toll_sections"][0]["instruction_refs"] == ["AP-X"]
    assert row["toll_sections"][0]["length_km_approx"] > 0
    assert row["toll_sections"][0]["end_position_km_approx"] <= row["distance_km"]
    assert decode_waycategory_mask(0) == ()


def test_cartographic_zero_missing_extras_and_invalid_overlap():
    response = _response()
    response["features"][0]["properties"]["extras"]["tollways"] = {
        "values": [[0, 4, 0]], "summary": [{"value": 0, "distance": 3000}]}
    row = analyze_geojson_extras(response, required=("tollways",))[0]
    assert row["toll_distance_km"] == 0 and row["toll_cost_eur"] is None
    assert row["toll_verification"] == "UNKNOWN"
    missing = analyze_geojson_extras(_response(enriched=False))[0]
    assert missing["coverage"] == "missing_tollways" and missing["toll_distance_km"] is None
    with pytest.raises(ValueError, match="sin extra_info"):
        analyze_geojson_extras(_response(enriched=False), required=("tollways",))
    response["features"][0]["properties"]["extras"]["tollways"]["values"] = [[0, 3, 0], [2, 4, 1]]
    with pytest.raises(ValueError, match="realmente solapados"):
        analyze_geojson_extras(response, required=("tollways",))


def test_extra_intervals_allow_shared_endpoints_and_mark_gaps_as_unknown():
    response = _response()
    extras = response["features"][0]["properties"]["extras"]
    # [0,2] y [2,4] comparten vértice 2, pero no aristas; cubren toda la ruta.
    extras["tollways"]["values"] = [[0, 2, 0], [2, 4, 1]]
    complete = analyze_geojson_extras(response, required=("tollways",))[0]
    assert complete["coverage"] == "complete_cartographic"
    assert complete["extra_coverage"]["tollways"] == "complete"

    # Falta la arista 1->2. Se conserva la sección conocida, pero no se infiere
    # cobertura total ni tollways=0 para el tramo no clasificado.
    extras["tollways"]["values"] = [[0, 1, 0], [2, 4, 1]]
    partial = analyze_geojson_extras(response, required=("tollways",))[0]
    assert partial["coverage"] == "partial_cartographic"
    assert partial["extra_coverage"]["tollways"] == "partial"
    assert partial["toll_distance_km"] is None
    assert partial["toll_distance_summary_km"] == 2
    assert partial["toll_segment_count"] == 1
    assert any("no se infiere cero" in warning for warning in partial["warnings"])


@pytest.mark.parametrize("values, message", [
    ([[0, 3, 0], [2, 4, 1]], "realmente solapados"),
    ([[0, 5, 0]], "fuera de geometría"),
    ([[1, 4, 0], [0, 1, 1]], "desordenados"),
])
def test_extra_intervals_reject_true_overlap_out_of_bounds_and_disorder(values, message):
    response = _response()
    response["features"][0]["properties"]["extras"]["tollways"]["values"] = values
    with pytest.raises(ValueError, match=message):
        analyze_geojson_extras(response, required=("tollways",))


def test_provider_sends_extra_info_and_rejects_incomplete_response():
    payloads = []

    def opener(request, timeout):
        payloads.append(json.loads(request.data))
        return _Response(_response())

    request = AcquisitionRequest(_city("a", -3), _city("b", -4), extra_info=("tollways", "osmid", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=opener, max_retries=0,
                                        max_http_requests=1, min_interval_seconds=0)
    safe, raw, routes = provider.fetch(request)
    assert payloads[0]["extra_info"] == ["osmid", "tollways", "waycategory"]
    assert safe["body"]["geometry"] and safe["body"]["instructions"]
    assert routes[0].alternative_id != routes[0].fastest_route_id
    assert routes[0].toll_cost_eur is None
    assert "synthetic-secret" not in json.dumps(safe)
    bad = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_args, **_kw: _Response(_response(enriched=False)),
                                   max_retries=0, max_http_requests=1, min_interval_seconds=0)
    with pytest.raises(ProviderError, match="enriquecida incompleta"):
        bad.fetch(request)


def test_partial_extra_intervals_are_saved_without_claiming_complete_toll_coverage(tmp_path):
    response = _response()
    response["features"][0]["properties"]["extras"]["tollways"]["values"] = [
        [0, 1, 0], [2, 4, 1],
    ]
    request = AcquisitionRequest(_city("valladolid", -4.7), _city("badajoz", -6.9),
                                 extra_info=("tollways", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(response),
                                        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    store = RouteStore(tmp_path / "routes", raw_dir=tmp_path / "raw")
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)

    assert summary.acquired == 1 and summary.failed == 0
    state = json.loads(store.state_path.read_text(encoding="utf-8"))["requests"]
    record = next(iter(state.values()))
    raw = json.loads(Path(record["raw_file"]).read_text(encoding="utf-8"))
    analysis = analyze_geojson_extras(raw["response"], required=request.extra_info)[0]
    assert analysis["coverage"] == "partial_cartographic"
    assert analysis["toll_distance_km"] is None
    assert analysis["toll_distance_summary_km"] == 2
    assert raw["response"] == response


def test_invalid_interval_diagnostic_records_received_http_200_as_processed(tmp_path):
    response = _response()
    response["features"][0]["properties"]["extras"]["tollways"]["values"] = [
        [0, 3, 0], [2, 4, 1],
    ]
    request = AcquisitionRequest(_city("valladolid", -4.7), _city("badajoz", -6.9),
                                 extra_info=("tollways", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(response),
                                        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    store = RouteStore(tmp_path / "routes")
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)

    assert summary.failed == 1 and summary.http_status_codes == (200,)
    failure = summary.failures[0]
    assert failure["category"] == "missing_extra_info"
    assert failure["response_received"] is True
    assert failure["provider_may_have_processed_request"] is True
    assert failure["http_request_counted"] is True


def test_provider_uses_heigit_effective_url_and_two_requested_extras():
    observed = {}

    def opener(request, timeout):
        observed["url"] = request.full_url
        observed["payload"] = json.loads(request.data)
        response = _response()
        del response["features"][0]["properties"]["extras"]["osmId"]
        return _Response(response)

    request = AcquisitionRequest(_city("a", -3), _city("b", -4),
                                 extra_info=("tollways", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=opener, max_retries=0,
                                        max_http_requests=1, min_interval_seconds=0)
    provider.fetch(request)
    assert observed["url"] == (
        "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson"
    )
    assert observed["payload"]["extra_info"] == ["tollways", "waycategory"]
    # La respuesta es válida sin osmId porque el primer piloto no lo solicita.


def test_persistence_resume_and_geometry_comparison_offline(tmp_path: Path):
    original = RouteStore(tmp_path / "original", raw_dir=tmp_path / "raw-original")
    enriched = RouteStore(tmp_path / "enriched", raw_dir=tmp_path / "raw-enriched")
    base = AcquisitionRequest(_city("a", -3), _city("b", -4))
    extra = replace(base, extra_info=("tollways", "osmid", "waycategory"))
    first = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(_response()),
                                     max_retries=0, min_interval_seconds=0)
    AcquisitionManager(first, original).run([base], max_requests=1)
    second = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(_response(change_geometry=True)),
                                      max_retries=0, max_http_requests=1, min_interval_seconds=0)
    manager = AcquisitionManager(second, enriched)
    acquired = manager.run([extra], max_requests=1)
    resumed = manager.run([extra], max_requests=1)
    assert (acquired.acquired, acquired.http_requests, resumed.skipped_existing, resumed.http_requests) == (1, 1, 1, 0)
    assert len(original.load_alternatives()) == 1
    rows = analyze_saved_routes(enriched.root, enriched.raw_dir, original.root)
    assert len(rows) == 1 and rows[0]["geometry_equal_to_previous"] is False
    assert rows[0]["first_different_coordinate_index"] == 3
    assert rows[0]["previous_geometry_sha256"] != rows[0]["geometry_sha256"]
    assert rows[0]["toll_verification"] == "UNKNOWN"


def test_saved_analyzer_accepts_two_extras_and_skips_legacy_without_aborting(tmp_path: Path):
    original = RouteStore(tmp_path / "original", raw_dir=tmp_path / "raw-original")
    enriched = RouteStore(tmp_path / "enriched", raw_dir=tmp_path / "raw-enriched")
    a, b = _city("a", -3), _city("b", -4)
    legacy = AcquisitionRequest(a, b)
    enhanced = replace(legacy, extra_info=("tollways", "waycategory"))
    response = _response()
    del response["features"][0]["properties"]["extras"]["osmId"]
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(response),
                                        max_retries=0, max_http_requests=2, min_interval_seconds=0)
    manager = AcquisitionManager(provider, enriched)
    assert manager.run([legacy, enhanced], max_requests=2).acquired == 2
    skipped = []
    rows = analyze_saved_routes(enriched.root, enriched.raw_dir, original.root, skipped)
    assert len(rows) == 1
    assert rows[0]["extra_info_requested"] == ["tollways", "waycategory"]
    assert rows[0]["extra_info_present"] == ["tollways", "waycategory"]
    assert rows[0]["extra_info_status"]["osmid"] == "no_solicitado_ausente"
    assert rows[0]["toll_verification"] == "UNKNOWN"
    assert [item["status"] for item in skipped] == ["legacy_snapshot_without_extras"]


def test_saved_analyzer_rejects_response_changed_after_snapshot_hash(tmp_path: Path):
    store = RouteStore(tmp_path / "enriched")
    request = AcquisitionRequest(_city("a", -3), _city("b", -4),
                                 extra_info=("tollways", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(_response()),
                                        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    assert AcquisitionManager(provider, store).run([request], max_requests=1).acquired == 1
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    raw_path = Path(next(iter(state["requests"].values()))["raw_file"])
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["response"]["features"][0]["properties"]["summary"]["distance"] += 10
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    skipped = []
    rows = analyze_saved_routes(store.root, store.raw_dir, tmp_path / "original", skipped)

    assert rows == []
    assert skipped[0]["status"] == "corrupt_snapshot"
    assert "hash de respuesta" in skipped[0]["reason"]


def test_saved_analyzer_reports_requested_but_missing_extra(tmp_path: Path):
    cities = (_city("a", -3), _city("b", -4))
    request = AcquisitionRequest(cities[0], cities[1], extra_info=("tollways", "waycategory"))
    store = RouteStore(tmp_path / "enriched", raw_dir=tmp_path / "raw")
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(_response()),
                                        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    assert AcquisitionManager(provider, store).run([request], max_requests=1).acquired == 1
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    key = next(iter(state["requests"]))
    raw_path = Path(state["requests"][key]["raw_file"])
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    del raw["response"]["features"][0]["properties"]["extras"]["waycategory"]
    raw["response_sha256"] = sha256(json.dumps(
        raw["response"], sort_keys=True, ensure_ascii=False
    ).encode("utf-8")).hexdigest()[:16]
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    skipped = []
    rows = analyze_saved_routes(store.root, store.raw_dir, tmp_path / "original", skipped)
    assert rows == []
    assert skipped[0]["status"] == "requested_attribute_missing"
    assert "waycategory" in skipped[0]["reason"]


@pytest.mark.parametrize(("status", "reason"), [(403, "authentication_rejected"),
                                                   (429, "rate_limited")])
def test_acquisition_manager_stops_batch_on_provider_limit(tmp_path: Path, status: int,
                                                           reason: str):
    cities = (_city("a", -3), _city("b", -4), _city("c", -5))
    requests = (AcquisitionRequest(cities[0], cities[1]),
                AcquisitionRequest(cities[1], cities[2]))

    def rate_limited(http_request, timeout):
        raise HTTPError(http_request.full_url, status, "synthetic provider limit", {}, BytesIO(b"{}"))

    provider = OpenRouteServiceProvider("synthetic-secret", opener=rate_limited, max_retries=0,
                                        max_http_requests=2, min_interval_seconds=0)
    summary = AcquisitionManager(provider, RouteStore(tmp_path / "routes")).run(
        requests, max_requests=2)
    assert summary.failed == 1 and summary.http_requests == 1
    assert summary.stopped_reason == reason and summary.not_attempted == 1


def test_enriched_queue_skips_only_valid_snapshots_with_requested_extras(tmp_path: Path, monkeypatch):
    from experiments import plan_tsp_direction_queue as queue
    cities = (_city("a", -3), _city("b", -4))
    monkeypatch.setattr(queue, "load_published_dataset", lambda _: {
        "city_order": ("a", "b"), "duration_hours": np.array([[0., 1.], [2., 0.]])})
    monkeypatch.setattr(queue, "load_city_catalog", lambda: cities)
    store = RouteStore(tmp_path / "enriched", raw_dir=tmp_path / "raw")
    response = _response()
    del response["features"][0]["properties"]["extras"]["osmId"]
    request = AcquisitionRequest(cities[0], cities[1], extra_info=("tollways", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(response),
        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    assert AcquisitionManager(provider, store).run([request], max_requests=1).acquired == 1
    rows = queue.plan_enriched_queue(tmp_path / "dataset", store.root, store.raw_dir)
    assert [(row["origin_id"], row["destination_id"]) for row in rows] == [("b", "a")]
    assert rows[0]["request_id"] == AcquisitionRequest(
        cities[1], cities[0], extra_info=("tollways", "waycategory")).request_id


def test_http_504_is_recorded_and_can_resume_without_hidden_retry(tmp_path: Path):
    request = AcquisitionRequest(_city("a", -3), _city("b", -4), extra_info=("tollways",))
    store = RouteStore(tmp_path / "enriched")

    def unavailable(*_args, **_kwargs):
        raise HTTPError("synthetic://ors", 504, "synthetic server timeout", {}, BytesIO())

    failed_provider = OpenRouteServiceProvider("synthetic-secret", opener=unavailable,
                                               max_retries=0, max_http_requests=1, min_interval_seconds=0)
    failed = AcquisitionManager(failed_provider, store).run([request], max_requests=1)
    assert (failed.failed, failed.http_requests, failed.http_status_codes) == (1, 1, (504,))
    assert store.load_alternatives() == ()
    payload = _response()
    recovered_provider = OpenRouteServiceProvider("synthetic-secret", opener=lambda *_a, **_k: _Response(payload),
                                                  max_retries=0, max_http_requests=1, min_interval_seconds=0)
    recovered = AcquisitionManager(recovered_provider, store).run([request], max_requests=1)
    assert (recovered.acquired, recovered.http_requests) == (1, 1)


def test_overpass_way_plan_deduplicates_and_limits_batches():
    plan = plan_overpass_way_queries([1, 2, 2, 3], known_way_ids=[1], batch_size=1)
    assert len(plan) == 2
    assert plan[0]["osm_type"] == "way" and plan[0]["osm_way_ids"] == [2]
    assert plan[1]["osm_way_ids"] == [3]
    assert plan[0]["query"] == "[out:json][timeout:25];way(id:2);out body geom;"
    with pytest.raises(ValueError, match="enteros positivos"):
        plan_overpass_way_queries([0])


def test_overpass_way_lookup_caches_and_recovers_after_504(tmp_path: Path):
    store = OverpassCatalogStore(tmp_path)

    def unavailable(*_args, **_kwargs):
        raise HTTPError("synthetic://overpass", 504, "synthetic timeout", {}, BytesIO())

    failed_client = OverpassClient(opener=unavailable)
    with pytest.raises(OverpassError) as failure:
        store.get_or_fetch_way_ids(failed_client, (103, 101))
    assert failure.value.status_code == 504 and failed_client.http_attempts == 1
    payload = {"elements": [{"type": "way", "id": 101, "tags": {"ref": "AP-X"},
                             "geometry": [{"lon": -3.0, "lat": 40.0}, {"lon": -3.1, "lat": 40.1}]}]}
    requests = []

    def available(request, timeout):
        requests.append(request.data.decode())
        return _Response(payload)

    client = OverpassClient(opener=available)
    first, acquired = store.get_or_fetch_way_ids(client, (101, 103))
    cached, repeated = store.get_or_fetch_way_ids(client, (103, 101))
    assert acquired is True and repeated is False and first == cached == payload
    assert client.http_attempts == 1 and len(requests) == 1
    assert "way%28id%3A101%2C103%29" in requests[0]


def test_overpass_known_node_lookup_is_exact_bounded_and_incremental(tmp_path: Path):
    assert overpass_node_ids_query([41270656, 35292790]) == (
        "[out:json][timeout:25];node(id:35292790,41270656);out body;"
    )
    store = OverpassCatalogStore(tmp_path)
    payload = {"elements": [{"type": "node", "id": 35292790,
                             "lat": 41.777228, "lon": -1.124528,
                             "tags": {"barrier": "toll_booth", "name": "Peaje de Alagon"}}]}
    requests = []

    def available(request, timeout):
        requests.append(request.data.decode())
        return _Response(payload)

    client = OverpassClient(opener=available)
    first, fetched = store.get_or_fetch_node_ids(client, (41270656, 35292790))
    cached, fetched_again = store.get_or_fetch_node_ids(client, (35292790, 41270656))
    assert first == cached == payload
    assert fetched is True and fetched_again is False
    assert client.http_attempts == len(requests) == 1
    assert "node%28id%3A35292790%2C41270656%29" in requests[0]
    with pytest.raises(ValueError, match="entre 1 y 50"):
        overpass_node_ids_query(range(1, 52))


def test_ors_connection_refused_writes_safe_diagnostic_and_counts_attempt(tmp_path: Path):
    request = AcquisitionRequest(_city("madrid", -3), _city("toledo", -4),
                                 extra_info=("tollways", "waycategory"))
    token = "synthetic-api-secret"

    def refused(*_args, **_kwargs):
        raise URLError(ConnectionRefusedError(10061, "connection refused"))

    provider = OpenRouteServiceProvider(token, opener=refused, max_retries=0,
                                        max_http_requests=1, min_interval_seconds=0)
    store = RouteStore(tmp_path / "routes")
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)
    failure = summary.failures[0]
    diagnostic = json.loads(Path(failure["diagnostic_file"]).read_text(encoding="utf-8"))
    assert summary.failed == 1 and summary.http_requests == 1
    assert failure["category"] == "connection_refused"
    assert failure["stage"] == "transport" and failure["http_request_counted"] is True
    assert failure["http_status_code"] is None and failure["http_status_codes"] == ()
    assert diagnostic["request_id"].endswith(request.request_id)
    assert token not in json.dumps(diagnostic)


@pytest.mark.parametrize(("reason", "expected_category"), [
    (socket.gaierror(-2, "name resolution failed"), "dns_error"),
    (socket.timeout("synthetic timeout"), "timeout"),
])
def test_ors_transport_failures_are_classified_without_http_status(
    tmp_path: Path, reason, expected_category: str,
):
    request = AcquisitionRequest(_city("madrid", -3), _city("toledo", -4))
    provider = OpenRouteServiceProvider("synthetic-api-secret",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(reason)),
        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    summary = AcquisitionManager(provider, RouteStore(tmp_path / expected_category)).run(
        [request], max_requests=1)
    failure = summary.failures[0]
    assert failure["category"] == expected_category
    assert failure["http_request_counted"] is True
    assert failure["http_status_code"] is None and summary.http_status_codes == ()
    if expected_category == "timeout":
        assert failure["effective_endpoint"].endswith("/driving-car/geojson")
        assert failure["timeout_seconds"] == 30.0
        assert failure["provider_may_have_processed_request"] is True


def test_ors_http_400_keeps_sanitized_provider_message_and_status(tmp_path: Path):
    request = AcquisitionRequest(_city("madrid", -3), _city("toledo", -4),
                                 extra_info=("osmid",))
    token = "synthetic-api-secret"
    body = json.dumps({"error": {"code": 2010,
        "message": "Invalid extra_info value osmid; do not echo synthetic-api-secret"}}).encode()

    def bad_parameter(http_request, timeout):
        raise HTTPError(http_request.full_url, 400, "Bad Request", {}, BytesIO(body))

    provider = OpenRouteServiceProvider(token, opener=bad_parameter, max_retries=0,
                                        max_http_requests=1, min_interval_seconds=0)
    store = RouteStore(tmp_path / "routes")
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)
    failure = summary.failures[0]
    assert summary.http_requests == 1 and summary.http_status_codes == (400,)
    assert failure["category"] == "invalid_parameters" and failure["http_status_code"] == 400
    assert "Invalid extra_info value osmid" in failure["message"]
    assert token not in failure["message"]
    assert token not in Path(failure["diagnostic_file"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(("status", "expected_category"), [
    (401, "authentication_rejected"), (403, "authentication_rejected"),
    (429, "rate_limited"), (503, "server_error"),
])
def test_ors_http_status_categories_are_diagnosed(status: int, expected_category: str,
                                                  tmp_path: Path):
    request = AcquisitionRequest(_city("madrid", -3), _city("toledo", -4))

    def rejected(http_request, timeout):
        raise HTTPError(http_request.full_url, status, "synthetic response", {},
                        BytesIO(b'{"error":{"message":"synthetic provider response"}}'))

    provider = OpenRouteServiceProvider("synthetic-api-secret", opener=rejected,
        max_retries=0, max_http_requests=1, min_interval_seconds=0)
    summary = AcquisitionManager(provider, RouteStore(tmp_path / str(status))).run(
        [request], max_requests=1)
    failure = summary.failures[0]
    assert failure["category"] == expected_category
    assert failure["http_status_code"] == status
    assert summary.http_requests == 1 and summary.http_status_codes == (status,)


def test_ors_persistence_failure_after_http_200_is_separated_from_transport(tmp_path: Path,
                                                                            monkeypatch):
    request = AcquisitionRequest(_city("madrid", -3), _city("toledo", -4),
                                 extra_info=("tollways", "osmid", "waycategory"))
    provider = OpenRouteServiceProvider("synthetic-api-secret",
        opener=lambda *_args, **_kwargs: _Response(_response()), max_retries=0,
        max_http_requests=1, min_interval_seconds=0)
    store = RouteStore(tmp_path / "routes")

    def fail_persist(*_args, **_kwargs):
        raise OSError("synthetic disk error")

    monkeypatch.setattr(store, "save_success", fail_persist)
    summary = AcquisitionManager(provider, store).run([request], max_requests=1)
    failure = summary.failures[0]
    diagnostic = json.loads(Path(failure["diagnostic_file"]).read_text(encoding="utf-8"))
    assert summary.http_requests == 1 and summary.http_status_codes == (200,)
    assert failure["category"] == "persistence_error"
    assert failure["stage"] == "persistence" and failure["http_status_code"] == 200
    assert failure["http_request_counted"] is True
    assert diagnostic["persistence_exception_type"] == "OSError"
    assert "disk error" in diagnostic["persistence_message"]
    assert "synthetic-api-secret" not in json.dumps(diagnostic)


def test_failed_arcs_are_quarantined_and_remain_pending_recovery(tmp_path):
    path = tmp_path / "quarantine_pairs.json"
    record_quarantined_failures(path, ({
        "origin_id": "segovia", "destination_id": "avila", "category": "timeout",
        "diagnostic_file": "diagnostics/timeout.json", "http_status_code": None,
    },))
    quarantine = load_quarantined_pairs(path)
    assert ("segovia", "avila") in quarantine
    rows = [
        {"origin_id": "segovia", "destination_id": "avila"},
        {"origin_id": "madrid", "destination_id": "toledo"},
    ]
    selected, recovery = exclude_quarantined(rows, set(quarantine))
    assert [(row["origin_id"], row["destination_id"]) for row in selected] == [
        ("madrid", "toledo")]
    assert [(row["origin_id"], row["destination_id"]) for row in recovery] == [
        ("segovia", "avila")]


def test_invalid_quarantine_fails_closed(tmp_path):
    path = tmp_path / "quarantine_pairs.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="evitar repetir fallos"):
        load_quarantined_pairs(path)


def test_rate_limit_headers_are_persisted_and_zero_remaining_stops_batch(tmp_path):
    calls = []

    def limited(*_args, **_kwargs):
        calls.append(1)
        return _Response(_response(), {"x-ratelimit-limit": "2000",
                                       "x-ratelimit-remaining": "0",
                                       "x-ratelimit-reset": "1791926400"})

    requests = [
        AcquisitionRequest(_city("a", -3), _city("b", -4),
                           extra_info=("tollways", "waycategory")),
        AcquisitionRequest(_city("a", -3), _city("c", -5),
                           extra_info=("tollways", "waycategory")),
    ]
    store = RouteStore(tmp_path / "quota-routes")
    provider = OpenRouteServiceProvider("synthetic-api-secret", opener=limited,
        max_retries=0, max_http_requests=2, min_interval_seconds=0)
    summary = AcquisitionManager(provider, store).run(requests, max_requests=2)
    saved = json.loads(Path(store._state()["requests"][
        f"{provider.cache_namespace}:{requests[0].request_id}"]["raw_file"]).read_text(encoding="utf-8"))
    assert summary.acquired == 1 and summary.not_attempted == 1
    assert summary.stopped_reason == "provider_reported_no_remaining_quota"
    assert summary.http_requests == 1 and len(calls) == 1
    assert saved["request"]["acquisition"]["rate_limit_headers"][
        "x-ratelimit-remaining"] == "0"


def test_daily_quota_budget_stops_retry_without_exceeding_http_attempts(tmp_path):
    calls = []

    def failing(*_args, **_kwargs):
        calls.append(1)
        raise HTTPError("https://fixture.invalid", 502, "bad gateway", {}, BytesIO(b"{}"))

    provider = OpenRouteServiceProvider(
        "synthetic-secret", opener=failing, sleep=lambda _seconds: None,
        max_retries=3, max_http_requests=10, min_interval_seconds=0,
    )
    request = AcquisitionRequest(_city("a", -3), _city("b", -4),
                                 extra_info=("tollways", "waycategory"))
    summary = AcquisitionManager(
        provider, RouteStore(tmp_path / "daily-quota-retry"), daily_quota=1,
    ).run([request], max_requests=1)

    assert len(calls) == 1
    assert summary.http_requests == 1
    assert summary.stopped_reason == "http_budget_exhausted"
    assert summary.failures[0]["category"] == "http_budget_exhausted"
