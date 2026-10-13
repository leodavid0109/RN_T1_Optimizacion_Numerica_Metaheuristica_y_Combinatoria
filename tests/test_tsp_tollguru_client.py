"""Pruebas con transporte simulado; no son respuestas reales de TollGuru."""

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src.tsp.etl.tollguru import TollGuruClient, TollGuruError


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def make_client(opener=None, **kwargs):
    return TollGuruClient(
        api_key="test-secret",
        opener=opener or (lambda *_a, **_k: FakeResponse({"route": {"hasTolls": True}, "meta": {"tx": 1}})),
        now=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc),
        **kwargs,
    )


def test_polyline_plan_converts_geojson_coordinate_order_and_dry_run_is_offline():
    calls = []
    client = make_client(opener=lambda *a, **k: calls.append((a, k)))
    plan = client.plan_polyline(
        "bizkaia-zaragoza-fast",
        ((-2.9, 43.2), (-1.0, 42.0)),
        vehicle={"type": "unresolved-Spain-light-car"},
    )
    assert plan.endpoint.endswith("/complete-polyline-from-mapping-service")
    assert plan.payload["path"] == "43.2000000,-2.9000000|42.0000000,-1.0000000"
    assert client.execute(plan) is plan
    assert calls == []
    assert client.http_requests_made == 0


def test_od_plan_requires_origins_destination_and_vehicle():
    client = make_client()
    with pytest.raises(ValueError, match="from y to"):
        client.plan_origin_destination("x", {"from": {}, "to": {}})
    plan = client.plan_origin_destination(
        "x", {"from": {"lat": 43.2, "lng": -2.9}, "to": {"lat": 41.7, "lng": -0.9},
              "vehicle": {"type": "pending-provider-class"}},
    )
    assert plan.endpoint.endswith("/origin-destination-waypoints")


def test_execute_requires_key_without_leaking_its_name_or_value(monkeypatch):
    monkeypatch.delenv("TOLLGURU_API_KEY", raising=False)
    client = TollGuruClient(api_key=None, opener=lambda *_a, **_k: pytest.fail("no debe llamar"))
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    with pytest.raises(TollGuruError, match="TOLLGURU_API_KEY") as error:
        client.execute(plan, execute=True)
    assert "test-secret" not in str(error.value)
    assert client.http_requests_made == 0


def test_mocked_request_uses_documented_header_and_counts_transaction_not_route_cost():
    seen = {}

    def opener(request, timeout):
        seen["headers"] = dict(request.header_items())
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data)
        return FakeResponse({"route": {"hasTolls": True, "costs": {"cash": None}}, "meta": {"tx": 2}})

    client = make_client(opener=opener, max_http_requests=1)
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    result = client.execute(plan, execute=True)
    assert result.status_code == 200
    assert result.provider_transaction_count == 2
    assert result.queried_at == "2026-10-13T00:00:00+00:00"
    assert seen["headers"]["X-api-key"] == "test-secret"
    assert seen["timeout"] == 30.0
    assert "toll_cost_eur" not in result.raw_payload
    assert client.http_requests_made == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_are_sanitized_and_counted(status):
    def opener(request, timeout):
        raise HTTPError(request.full_url, status, "remote error", {}, BytesIO(b"secret server body"))

    client = make_client(opener=opener, max_http_requests=1)
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    with pytest.raises(TollGuruError) as error:
        client.execute(plan, execute=True)
    assert error.value.status_code == status
    assert "secret server body" not in str(error.value)
    assert "test-secret" not in str(error.value)
    assert client.http_requests_made == 1
    assert client.http_status_codes == [status]


def test_strict_request_budget_and_geometry_validation():
    client = make_client(max_http_requests=1)
    with pytest.raises(ValueError):
        client.plan_polyline("r", ((-3.0, 40.0),), vehicle={"type": "x"})
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    client.execute(plan, execute=True)
    with pytest.raises(TollGuruError, match="presupuesto"):
        client.execute(plan, execute=True)


def test_departure_time_requires_iso8601_with_timezone():
    client = make_client()
    with pytest.raises(ValueError, match="ISO 8601"):
        client.plan_polyline("r", ((-3, 40), (-2, 41)), vehicle={"type": "x"}, departure_time="yesterday")
    with pytest.raises(ValueError, match="zona horaria"):
        client.plan_origin_destination(
            "r", {"from": {"lat": 40, "lng": -3}, "to": {"lat": 41, "lng": -2}, "vehicle": {"type": "x"}},
            departure_time="2026-10-12T12:00:00",
        )


def test_timeout_and_invalid_json_are_sanitized():
    from urllib.error import URLError

    client = make_client(opener=lambda *_a, **_k: (_ for _ in ()).throw(URLError("offline")))
    plan = client.plan_polyline("r", ((-3, 40), (-2, 41)), vehicle={"type": "x"})
    with pytest.raises(TollGuruError, match="falló la conexión"):
        client.execute(plan, execute=True)
    assert client.http_requests_made == 1

    class InvalidJsonResponse(FakeResponse):
        def __init__(self):
            self.payload = b"not-json"

    client = make_client(opener=lambda *_a, **_k: InvalidJsonResponse())
    plan = client.plan_polyline("r", ((-3, 40), (-2, 41)), vehicle={"type": "x"})
    with pytest.raises(TollGuruError, match="no JSON"):
        client.execute(plan, execute=True)

    client = make_client(opener=lambda *_a, **_k: FakeResponse({"message": "incomplete"}))
    plan = client.plan_polyline("r", ((-3, 40), (-2, 41)), vehicle={"type": "x"})
    with pytest.raises(TollGuruError, match="incompleta"):
        client.execute(plan, execute=True)


def test_raw_local_persistence_marks_provider_result_unverified_and_does_not_store_key(monkeypatch):
    saved = {}
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: None)
    monkeypatch.setattr(Path, "write_text", lambda path, content, **_k: saved.__setitem__(str(path), content))
    client = make_client()
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    response = client.execute(plan, execute=True)
    path = client.save_local(response, "local-only")
    record_text = saved[str(path)]
    record = json.loads(record_text)
    assert record["economic_status"] == "unverified_provider_estimate"
    assert "test-secret" not in record_text
    assert record["provider_transaction_count"] == 1


def test_persistence_retains_distinct_responses_for_same_request(monkeypatch):
    saved = {}
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: None)
    monkeypatch.setattr(Path, "write_text", lambda path, content, **_k: saved.__setitem__(str(path), content))
    client = make_client()
    plan = client.plan_polyline("r", ((-3.0, 40.0), (-2.0, 41.0)), vehicle={"type": "x"})
    first = client.execute(plan, execute=True)
    changed = type(first)(**{**first.__dict__, "raw_payload": {"route": {"hasTolls": False}}})
    one = client.save_local(first, "local-only")
    two = client.save_local(changed, "local-only")
    assert one != two
    assert str(one) in saved and str(two) in saved
