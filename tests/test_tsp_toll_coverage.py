"""Pruebas sintéticas de cobertura de peajes; no representan datos de España."""

import pytest

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl.toll_coverage import build_toll_coverage_report, coverage_report_as_dict


def _route(origin, destination, alternative_id, *, fastest_id=None, status=TollStatus.UNKNOWN,
           amount=None, geometry=None):
    return RouteAlternative(
        origin_id=origin,
        destination_id=destination,
        alternative_id=alternative_id,
        fastest_route_id=fastest_id or alternative_id,
        distance_km=10,
        duration_hours=0.5,
        toll_status=status,
        toll_cost_eur=amount,
        routing_engine="fixture",
        routing_engine_version="1",
        profile="car",
        source="fixture sintético",
        acquired_on="2026-10-12",
        toll_source="fixture tariff" if status is not TollStatus.UNKNOWN else None,
        toll_checked_on="2026-10-12" if status is not TollStatus.UNKNOWN else None,
        geometry_lon_lat=geometry,
    )


def test_reports_each_coverage_stage_without_treating_candidates_as_tariffs():
    cities = ("a", "b", "c")
    matrix_arcs = {("a", "b"), ("b", "a"), ("a", "c"), ("c", "a"), ("b", "c"), ("c", "b")}
    routes = (
        _route("a", "b", "ab-fast", geometry=((0, 0), (1, 1))),
        _route("a", "b", "ab-avoid", fastest_id="ab-fast", status=TollStatus.VERIFIED_WITHOUT_TOLL,
               amount=0, geometry=((0, 0), (1, 1))),
        _route("b", "c", "bc-fast", status=TollStatus.VERIFIED_WITH_TOLL, amount=2.0),
    )
    matches = (
        {"route_id": "ab-fast", "infrastructure_id": "osm:way/1"},
        {"route_id": "ab-fast", "infrastructure_id": "osm:way/1"},
        {"route_id": "ab-fast", "infrastructure_id": "osm:node/2"},
    )
    report = build_toll_coverage_report(
        cities,
        distance_duration_arcs=matrix_arcs,
        alternatives=routes,
        infrastructure_matches=matches,
        verified_entry_exit_route_ids=("bc-fast",),
        fuel_consumption_l_per_100km=5.4,
        fuel_price_eur_per_l=1.8,
    )

    ab = next(row for row in report.rows if (row.origin_id, row.destination_id) == ("a", "b"))
    bc = next(row for row in report.rows if (row.origin_id, row.destination_id) == ("b", "c"))
    assert report.expected_directed_arcs == report.distance_duration_arcs == 6
    assert report.arcs_with_route_geometry == 1
    assert report.arcs_with_infrastructure_candidates == 1
    assert ab.infrastructure_candidate_count == 2
    assert ab.tariff_verified_route_count == 1
    assert not ab.model_a_economic_cost_complete  # fastest sigue desconocida
    assert not ab.model_b_known_options_evaluable  # no convierte UNKNOWN en cero
    assert bc.model_a_economic_cost_complete
    assert bc.model_b_known_options_evaluable
    assert report.model_a_economic_arcs == 1
    assert report.alternative_inventory_exhaustive is False
    assert "no se convierten en cero" in " ".join(coverage_report_as_dict(report)["notes"])


def test_rejects_invalid_catalog_arcs_and_duplicate_alternatives():
    with pytest.raises(ValueError, match="duplicados"):
        build_toll_coverage_report(
            ("a", "a"), distance_duration_arcs=(), alternatives=(),
            fuel_consumption_l_per_100km=5.4, fuel_price_eur_per_l=1.8,
        )
    with pytest.raises(ValueError, match="fuera del catálogo"):
        build_toll_coverage_report(
            ("a", "b"), distance_duration_arcs={("a", "a")}, alternatives=(),
            fuel_consumption_l_per_100km=5.4, fuel_price_eur_per_l=1.8,
        )
    duplicate = _route("a", "b", "same")
    with pytest.raises(ValueError, match="alternative_id duplicado"):
        build_toll_coverage_report(
            ("a", "b"), distance_duration_arcs=(), alternatives=(duplicate, duplicate),
            fuel_consumption_l_per_100km=5.4, fuel_price_eur_per_l=1.8,
        )


def test_model_b_coverage_requires_the_fastest_option_to_be_present():
    only_candidate = _route(
        "a", "b", "ab-avoid", fastest_id="ab-fast", status=TollStatus.VERIFIED_WITHOUT_TOLL,
        amount=0,
    )
    report = build_toll_coverage_report(
        ("a", "b"), distance_duration_arcs={("a", "b"), ("b", "a")},
        alternatives=(only_candidate,), fuel_consumption_l_per_100km=5.4, fuel_price_eur_per_l=1.8,
    )
    ab = next(row for row in report.rows if (row.origin_id, row.destination_id) == ("a", "b"))
    assert not ab.model_b_known_options_evaluable


def test_fuel_configuration_must_be_positive_and_finite():
    with pytest.raises(ValueError, match="consumo"):
        build_toll_coverage_report(
            ("a", "b"), distance_duration_arcs=(), alternatives=(),
            fuel_consumption_l_per_100km=0, fuel_price_eur_per_l=1.8,
        )
