"""Caso sintético 2×2 de peajes completos; no representa España."""

from __future__ import annotations

from dataclasses import asdict
import json

import numpy as np

from src.tsp.alternatives import RouteAlternative, TollStatus
from src.tsp.etl.toll_operation import (RouteEvidence, build_economic_arcs, geometry_sha256,
                                         require_complete_economic_matrix)
from src.tsp.etl.toll_tariffs import RouteTollSection, TollTariff


def demo() -> dict:
    def route(origin: str, destination: str) -> RouteAlternative:
        return RouteAlternative(origin, destination, f"synthetic-{origin}-{destination}",
                                f"synthetic-{origin}-{destination}", 10.0, 1.0,
                                TollStatus.UNKNOWN, None, "synthetic", "1", "car",
                                "synthetic://test", "2026-10-13",
                                geometry_lon_lat=((-4.0, 40.0), (-3.9, 40.1)))

    routes = (route("a", "b"), route("b", "a"))
    tariffs = tuple(TollTariff(
        tariff_id=f"synthetic-{r.origin_id}-{r.destination_id}", operator="Sintético",
        road="AP-TEST", entry_station=r.origin_id, exit_station=r.destination_id,
        direction=f"{r.origin_id}->{r.destination_id}", vehicle_category="ligero",
        amount_eur=3.0 if r.origin_id == "a" else 0.0,
        valid_from="2026-01-01", valid_through="2026-12-31",
        source_url="https://example.invalid/synthetic", published_on="", acquired_on="2026-10-13",
        payment_conditions="sintético", verification_status=(
            "verificado_con_peaje" if r.origin_id == "a" else "verificado_sin_peaje"),
        payment_method="sin_descuentos", source_document="fixture", source_page="1",
    ) for r in routes)
    evidence = tuple(RouteEvidence(
        route_id=r.alternative_id, origin_id=r.origin_id, destination_id=r.destination_id,
        geometry_sha256=geometry_sha256(r), sections=(RouteTollSection(
            f"section-{r.origin_id}-{r.destination_id}", "Sintético", "AP-TEST",
            r.origin_id, r.destination_id, f"{r.origin_id}->{r.destination_id}", True,
            ("synthetic://station-map",)),), inventory_complete=True,
        inventory_source="synthetic://complete-inventory", no_toll_source="",
        review_status="revisado", reviewed_on="2026-10-13", matrix_route_equivalent=True,
        matrix_equivalence_source="synthetic://same-matrix-route",
    ) for r in routes)
    arcs = build_economic_arcs(("a", "b"), np.array([[0, 1], [1, 0.]]),
                               np.array([[0, 2], [2, 0.]]), routes, evidence, tariffs,
                               hour_value_eur=10, as_of="2026-10-12", payment_method="sin_descuentos")
    costs = require_complete_economic_matrix(("a", "b"), arcs)
    return {"scenario": "SINTÉTICO; no valida AP-68 ni tarifas españolas",
            "arcs": [asdict(arc) for arc in arcs], "closed_tour_cost_eur": float(costs[0, 1] + costs[1, 0])}


if __name__ == "__main__":
    print(json.dumps(demo(), ensure_ascii=False, indent=2))
