"""Validaciones sintéticas del pipeline; no certifican peajes reales."""

from dataclasses import replace
import json

import numpy as np
import pytest

from experiments.tsp_toll_synthetic_demo import demo
from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl.toll_operation import (RouteEvidence, assess_evidenced_route,
                                         build_economic_arcs, geometry_sha256,
                                         load_route_evidence, require_complete_economic_matrix)
from src.tsp.etl.toll_tariffs import RouteTollSection, TollTariff


def _fixture():
    route = RouteAlternative("a", "b", "rapid-a-b", "rapid-a-b", 10, 1,
                             TollStatus.UNKNOWN, None, "synthetic", "1", "car", "synthetic://route",
                             "2026-10-13", geometry_lon_lat=((-4, 40), (-3.9, 40.1)))
    tariff = TollTariff("tariff", "Synthetic", "AP-X", "A", "B", "A->B", "ligero", 4,
                        "2026-01-01", "2026-12-31", "https://example.invalid/tariff", "",
                        "2026-10-13", "general", "verificado_con_peaje",
                        payment_method="sin_descuentos", source_document="fixture", source_page="1")
    section = RouteTollSection("s1", "Synthetic", "AP-X", "A", "B", "A->B", True,
                               ("synthetic://station-pair",))
    evidence = RouteEvidence("rapid-a-b", "a", "b", geometry_sha256(route), (section,),
                             False, "", "", "pendiente", "2026-10-13")
    return route, tariff, evidence


def test_complete_synthetic_case_values_both_directions():
    result = demo()
    assert result["closed_tour_cost_eur"] == 27.0
    assert [arc["toll_status"] for arc in result["arcs"]] == ["VERIFIED_AMOUNT", "VERIFIED_ZERO"]
    assert result["scenario"].startswith("SINTÉTICO")


def test_verified_section_remains_partial_without_complete_route_inventory():
    route, tariff, evidence = _fixture()
    assessment = assess_evidenced_route(route, evidence, (tariff,), as_of="2026-10-12",
                                         payment_method="sin_descuentos")
    assert assessment.amount_eur is None
    assert assessment.tariff_ids == ("tariff",)
    hours = np.array([[0., 1.], [1., 0.]])
    fuel = np.array([[0., 2.], [2., 0.]])
    arcs = build_economic_arcs(("a", "b"), hours, fuel, (route,), (evidence,), (tariff,),
                               hour_value_eur=10, as_of="2026-10-12", payment_method="sin_descuentos")
    assert arcs[0].toll_status == "PARTIAL" and arcs[0].verified_section_eur == 4
    assert arcs[0].toll_total_eur is None and arcs[0].cost_total_eur is None
    assert arcs[1].toll_status == "UNKNOWN"
    with pytest.raises(ValueError, match="incompleta"):
        require_complete_economic_matrix(("a", "b"), arcs)


def test_geometry_hash_and_direction_are_required_for_association():
    route, tariff, evidence = _fixture()
    with pytest.raises(ValueError, match="no corresponde"):
        assess_evidenced_route(route, replace(evidence, geometry_sha256="0" * 64), (tariff,),
                               as_of="2026-10-12")
    with pytest.raises(ValueError, match="no corresponde"):
        assess_evidenced_route(route, replace(evidence, origin_id="b"), (tariff,), as_of="2026-10-12")
    reversed_tariff = replace(tariff, direction="B->A")
    complete = replace(evidence, inventory_complete=True, inventory_source="synthetic://inventory",
                       review_status="revisado")
    result = assess_evidenced_route(route, complete, (reversed_tariff,), as_of="2026-10-12")
    assert result.amount_eur is None


def test_expired_tariff_and_unverified_station_do_not_value_route():
    route, tariff, evidence = _fixture()
    complete = replace(evidence, inventory_complete=True, inventory_source="synthetic://inventory",
                       review_status="revisado")
    assert assess_evidenced_route(route, complete, (replace(tariff, valid_through="2026-10-11"),),
                                  as_of="2026-10-12").amount_eur is None
    unverified = replace(complete, sections=(replace(complete.sections[0], route_match_verified=False),))
    assert assess_evidenced_route(route, unverified, (tariff,), as_of="2026-10-12").amount_eur is None


def test_missing_toll_is_not_verified_zero_and_duplicate_section_is_rejected():
    route, tariff, evidence = _fixture()
    empty = replace(evidence, sections=())
    assert assess_evidenced_route(route, empty, (tariff,), as_of="2026-10-12").amount_eur is None
    complete = replace(empty, inventory_complete=True, inventory_source="synthetic://inventory",
                       no_toll_source="synthetic://no-toll-check", review_status="revisado")
    assert assess_evidenced_route(route, complete, (tariff,), as_of="2026-10-12").amount_eur == 0
    with pytest.raises(ValueError, match="duplicadas"):
        replace(evidence, sections=(evidence.sections[0], evidence.sections[0]))


def test_evidence_loader_rejects_duplicate_route_ids():
    route, _, evidence = _fixture()
    from dataclasses import asdict
    from pathlib import Path
    path = Path("data/reference/.test-evidence-duplicate.json")
    payload = {"schema_version": 1, "routes": [asdict(evidence), asdict(evidence)]}
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicado"):
            load_route_evidence(path)
    finally:
        path.unlink(missing_ok=True)
    assert geometry_sha256(route) == evidence.geometry_sha256


def test_queue_does_not_repeat_locally_available_directed_geometry(monkeypatch):
    from experiments import plan_tsp_direction_queue as queue
    from pathlib import Path
    from src.tsp.cities import City
    route, _, _ = _fixture()
    cities = tuple(City(name, name, name, 40.0, -4.0, "synthetic://city", "2026-10-13",
                        "verificada", "fixture") for name in ("a", "b"))
    monkeypatch.setattr(queue, "load_published_dataset", lambda _: {
        "city_order": ("a", "b"), "duration_hours": np.array([[0., 1.], [2., 0.]])})
    monkeypatch.setattr(queue, "load_city_catalog", lambda: cities)
    monkeypatch.setattr(queue, "RouteStore", lambda _: type("Store", (), {
        "load_alternatives": lambda self: (route,)})())
    rows = queue.plan_queue(Path("synthetic-dataset"), Path("synthetic-routes"))
    assert [(r["origin_id"], r["destination_id"]) for r in rows] == [("b", "a")]
