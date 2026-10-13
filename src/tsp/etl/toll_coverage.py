"""Cobertura auditable del inventario tarifario frente a los arcos del TSP.

Este módulo solo combina registros locales. La presencia de un candidato OSM
no confirma tránsito, estación, tarifa ni costo económico completo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from ..alternatives import RouteAlternative, TollStatus


@dataclass(frozen=True)
class ArcTollCoverage:
    origin_id: str
    destination_id: str
    distance_duration_present: bool
    route_geometry_count: int
    infrastructure_candidate_count: int
    verified_entry_exit_count: int
    tariff_verified_route_count: int
    model_a_economic_cost_complete: bool
    model_b_known_options_evaluable: bool
    model_b_known_option_count: int


@dataclass(frozen=True)
class TollCoverageReport:
    city_order: tuple[str, ...]
    expected_directed_arcs: int
    distance_duration_arcs: int
    arcs_with_route_geometry: int
    arcs_with_infrastructure_candidates: int
    arcs_with_verified_entry_exit: int
    arcs_with_verified_tariff: int
    model_a_economic_arcs: int
    model_b_arcs_with_multiple_known_options: int
    model_b_known_options_evaluable_arcs: int
    alternative_inventory_exhaustive: bool
    rows: tuple[ArcTollCoverage, ...]


def build_toll_coverage_report(
    city_order: Iterable[str],
    *,
    distance_duration_arcs: Iterable[tuple[str, str]],
    alternatives: Iterable[RouteAlternative],
    infrastructure_matches: Iterable[Mapping[str, object]] = (),
    verified_entry_exit_route_ids: Iterable[str] = (),
    fuel_consumption_l_per_100km: float,
    fuel_price_eur_per_l: float,
    alternative_inventory_exhaustive: bool = False,
) -> TollCoverageReport:
    """Resume en qué fase de verificación está cada conexión dirigida.

    ``verified_entry_exit_route_ids`` solo debe incluir rutas con revisión
    documentada de estaciones y sentido. ``infrastructure_matches`` admite
    filas del informe Overpass; sus IDs se deduplican por ruta e infraestructura.
    La completitud del Modelo B se refiere exclusivamente a las alternativas
    conocidas; por defecto no se presume que el conjunto sea exhaustivo.
    """
    cities = tuple(city_order)
    if len(cities) < 2 or any(not isinstance(city, str) or not city for city in cities):
        raise ValueError("city_order debe contener al menos dos identificadores no vacíos")
    if len(set(cities)) != len(cities):
        raise ValueError("city_order contiene identificadores duplicados")
    consumption = _positive_finite(fuel_consumption_l_per_100km, "consumo")
    price = _positive_finite(fuel_price_eur_per_l, "precio de combustible")

    expected = {(origin, destination) for origin in cities for destination in cities if origin != destination}
    matrix_arcs = set(distance_duration_arcs)
    if not matrix_arcs <= expected:
        raise ValueError("distance_duration_arcs contiene ciudades o diagonales fuera del catálogo")
    route_groups: dict[tuple[str, str], list[RouteAlternative]] = {}
    route_ids: set[str] = set()
    for route in alternatives:
        pair = (route.origin_id, route.destination_id)
        if pair not in expected:
            raise ValueError(f"alternativa {route.alternative_id} no corresponde a un arco del catálogo")
        if route.alternative_id in route_ids:
            raise ValueError(f"alternative_id duplicado: {route.alternative_id}")
        route_ids.add(route.alternative_id)
        route_groups.setdefault(pair, []).append(route)

    infrastructure_by_route: dict[str, set[str]] = {}
    for match in infrastructure_matches:
        route_id = str(match.get("route_id", ""))
        infrastructure_id = str(match.get("infrastructure_id", ""))
        if route_id and infrastructure_id:
            infrastructure_by_route.setdefault(route_id, set()).add(infrastructure_id)
    verified_entry_exit = set(verified_entry_exit_route_ids)

    rows = []
    for origin, destination in sorted(expected):
        routes = route_groups.get((origin, destination), [])
        primary = [route for route in routes if route.alternative_id == route.fastest_route_id]
        if len(primary) > 1:
            raise ValueError(f"hay más de una ruta rápida para {origin}->{destination}")
        route_geometry_count = sum(route.geometry_lon_lat is not None for route in routes)
        candidate_ids = set().union(*(infrastructure_by_route.get(route.alternative_id, set())
                                      for route in routes)) if routes else set()
        verified_routes = [route for route in routes if route.toll_status is not TollStatus.UNKNOWN]
        tariff_routes = [route for route in verified_routes if route.toll_source and route.toll_checked_on]
        known_options = 0
        for route in routes:
            if route.toll_status is TollStatus.UNKNOWN:
                continue
            toll = route.toll_cost_eur
            if toll is not None and toll >= 0:
                known_options += 1
        # The published fuel inputs permit a deterministic fuel calculation for
        # each route. Toll completeness remains mandatory for economic scoring.
        primary_complete = bool(primary and primary[0] in tariff_routes)
        rows.append(ArcTollCoverage(
            origin_id=origin,
            destination_id=destination,
            distance_duration_present=(origin, destination) in matrix_arcs,
            route_geometry_count=route_geometry_count,
            infrastructure_candidate_count=len(candidate_ids),
            verified_entry_exit_count=sum(route.alternative_id in verified_entry_exit for route in routes),
            tariff_verified_route_count=len(tariff_routes),
            model_a_economic_cost_complete=primary_complete,
            model_b_known_options_evaluable=bool(primary and routes) and known_options == len(routes),
            model_b_known_option_count=known_options,
        ))

    return TollCoverageReport(
        city_order=cities,
        expected_directed_arcs=len(expected),
        distance_duration_arcs=sum(row.distance_duration_present for row in rows),
        arcs_with_route_geometry=sum(row.route_geometry_count > 0 for row in rows),
        arcs_with_infrastructure_candidates=sum(row.infrastructure_candidate_count > 0 for row in rows),
        arcs_with_verified_entry_exit=sum(row.verified_entry_exit_count > 0 for row in rows),
        arcs_with_verified_tariff=sum(row.tariff_verified_route_count > 0 for row in rows),
        model_a_economic_arcs=sum(row.model_a_economic_cost_complete for row in rows),
        model_b_arcs_with_multiple_known_options=sum(row.model_b_known_option_count > 1 for row in rows),
        model_b_known_options_evaluable_arcs=sum(row.model_b_known_options_evaluable for row in rows),
        alternative_inventory_exhaustive=bool(alternative_inventory_exhaustive),
        rows=tuple(rows),
    )


def coverage_report_as_dict(report: TollCoverageReport) -> dict:
    """Serializa un resumen JSON sin omitir los estados desconocidos."""
    return {
        "city_order": list(report.city_order),
        "expected_directed_arcs": report.expected_directed_arcs,
        "coverage": {
            "distance_duration_arcs": report.distance_duration_arcs,
            "arcs_with_route_geometry": report.arcs_with_route_geometry,
            "arcs_with_infrastructure_candidates": report.arcs_with_infrastructure_candidates,
            "arcs_with_verified_entry_exit": report.arcs_with_verified_entry_exit,
            "arcs_with_verified_tariff": report.arcs_with_verified_tariff,
            "model_a_economic_arcs": report.model_a_economic_arcs,
            "model_b_arcs_with_multiple_known_options": report.model_b_arcs_with_multiple_known_options,
            "model_b_known_options_evaluable_arcs": report.model_b_known_options_evaluable_arcs,
        },
        "alternative_inventory_exhaustive": report.alternative_inventory_exhaustive,
        "rows": [asdict(row) for row in report.rows],
        "notes": [
            "Candidato OSM no equivale a tránsito confirmado ni a tarifa.",
            "Los peajes desconocidos no se convierten en cero.",
            "La evaluación del Modelo B cubre solo alternativas conocidas.",
        ],
    }


def _positive_finite(value: float, name: str) -> float:
    from math import isfinite

    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} debe ser positivo y finito")
    return number
