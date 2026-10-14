from __future__ import annotations

import pytest

from experiments.prepare_tsp_acquisition_plan import (
    render_overpass_query,
    validate_pending_rows,
)


def _pending_row(origin: str = "madrid", destination: str = "toledo") -> dict:
    return {
        "origin_id": origin,
        "destination_id": destination,
        "origin_lon": -3.7,
        "origin_lat": 40.4,
        "destination_lon": -4.0,
        "destination_lat": 39.9,
        "profile": "driving-car",
        "strategy": "fastest",
        "extra_info": "tollways,waycategory",
    }


def test_pending_manifest_rejects_duplicates_diagonal_and_quarantine() -> None:
    row = _pending_row()
    with pytest.raises(ValueError, match="duplicados"):
        validate_pending_rows([row, dict(row)], set(), 2)
    diagonal = _pending_row("madrid", "madrid")
    with pytest.raises(ValueError, match="diagonales"):
        validate_pending_rows([diagonal], set(), 1)
    with pytest.raises(ValueError, match="cuarentena"):
        validate_pending_rows([row], {("madrid", "toledo")}, 1)


def test_pending_manifest_checks_coordinates_and_requested_route_contract() -> None:
    row = _pending_row()
    row["origin_lon"] = 181
    with pytest.raises(ValueError, match="coordenada inválida"):
        validate_pending_rows([row], set(), 1)
    row = _pending_row()
    row["extra_info"] = "osmid"
    with pytest.raises(ValueError, match="parámetros inesperados"):
        validate_pending_rows([row], set(), 1)


def test_overpass_query_uses_wgs84_lat_lon_and_bounded_radius() -> None:
    query = render_overpass_query([(-1.25, 41.5)], radius_m=1200)
    assert "around:1200,41.500000,-1.250000" in query
    assert '["barrier"="toll_booth"]' in query
    assert '["highway"="toll_gantry"]' in query
    assert '["toll"="yes"]' in query
    with pytest.raises(ValueError, match="radio >=100"):
        render_overpass_query([(-1.25, 41.5)], radius_m=50)
