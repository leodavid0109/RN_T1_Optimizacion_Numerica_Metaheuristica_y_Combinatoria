"""Pruebas sintéticas de la cola y del reporte: sin consultas externas."""

from dataclasses import replace

import pytest

from experiments.prioritize_tsp_direction_queue import rank_missing_arcs
from experiments.report_tsp_toll_coverage import verified_route_rows
from src.tsp.etl.toll_operation import RouteEvidence


def _missing(origin: str, destination: str, hours: float = 1.0) -> dict:
    return {"origin_id": origin, "destination_id": destination,
            "duration_hours_matrix": hours}


def test_priority_uses_directed_frequency_and_closing_arc():
    rows = rank_missing_arcs(
        [_missing("a", "b"), _missing("b", "c"), _missing("c", "a"), _missing("b", "a")],
        [{"method": "NN", "city_order": ["a", "b", "c"]},
         {"method": "ACO", "city_order": ["a", "b", "c"]}],
    )
    by_pair = {(r["origin_id"], r["destination_id"]): r for r in rows}
    assert by_pair[("c", "a")]["candidate_tour_frequency"] == 2
    assert by_pair[("b", "a")]["candidate_tour_frequency"] == 0
    assert by_pair[("a", "b")]["methods"] == "ACO;NN"


def test_priority_rejects_duplicate_queue_or_invalid_tour():
    with pytest.raises(ValueError, match="duplicada"):
        rank_missing_arcs([_missing("a", "b"), _missing("a", "b")], [])
    with pytest.raises(ValueError, match="duplicadas"):
        rank_missing_arcs([_missing("a", "b")], [{"method": "NN", "city_order": ["a", "a"]}])


def test_verified_report_excludes_unknown_and_requires_reviewed_evidence():
    record = RouteEvidence("route", "a", "b", "a" * 64, (), True,
                           "synthetic://inventory", "synthetic://zero", "revisado", "2026-10-13",
                           True, "synthetic://matrix-match")
    row = {"origin_id": "a", "destination_id": "b", "route_id": "route",
           "toll_status": "VERIFIED_ZERO", "toll_total_eur": "0.0", "cost_total_eur": "12.0"}
    assert verified_route_rows([{**row, "toll_status": "UNKNOWN"}], (record,)) == []
    assert verified_route_rows([row], (record,))[0]["no_toll_source"] == "synthetic://zero"
    with pytest.raises(ValueError, match="sin evidencia"):
        verified_route_rows([row], ())
    with pytest.raises(ValueError, match="sin evidencia"):
        verified_route_rows([{**row, "destination_id": "c"}], (record,))
    with pytest.raises(ValueError, match="cero de peaje"):
        verified_route_rows([row], (replace(record, no_toll_source=""),))
