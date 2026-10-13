"""Respuestas ORS sintéticas: no constituyen evidencia vial real."""

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from experiments.analyze_tsp_ors_extras import analyze_saved_routes
from src.tsp.cities import City
from src.tsp.etl.acquisition import AcquisitionManager, AcquisitionRequest
from src.tsp.etl.ors import OpenRouteServiceProvider, ProviderError
from src.tsp.etl.ors_extras import analyze_geojson_extras, plan_overpass_way_queries
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_infrastructure import OverpassCatalogStore, OverpassClient, OverpassError


def _city(city_id: str, lon: float) -> City:
    return City(city_id, city_id, city_id, 40.0, lon, "synthetic://test", "2026-10-13",
                "verificada", "coordenada sintética")


def _response(*, enriched: bool = True, change_geometry: bool = False) -> dict:
    points = [[-3.0, 40.0], [-3.01, 40.0], [-3.02, 40.0],
              [-3.03, 40.01 if change_geometry else 40.0], [-3.04, 40.0]]
    props = {"summary": {"distance": 3000, "duration": 180},
             "segments": [{"steps": [{"name": "AP-X", "distance": 3000}]}]}
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

    def __init__(self, payload: dict):
        self.payload = payload

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
    with pytest.raises(ValueError, match="solapados"):
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
