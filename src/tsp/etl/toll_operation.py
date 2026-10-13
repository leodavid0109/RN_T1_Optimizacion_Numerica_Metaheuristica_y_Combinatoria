"""Valoración offline de rutas con evidencia explícita y matrices parciales."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from ..alternatives import RouteAlternative, TollStatus
from .toll_tariffs import RouteTollAssessment, RouteTollSection, TollTariff, assess_route_tolls


@dataclass(frozen=True)
class RouteEvidence:
    route_id: str
    origin_id: str
    destination_id: str
    geometry_sha256: str
    sections: tuple[RouteTollSection, ...]
    inventory_complete: bool
    inventory_source: str
    no_toll_source: str
    review_status: str
    reviewed_on: str
    matrix_route_equivalent: bool = False
    matrix_equivalence_source: str = ""

    def __post_init__(self) -> None:
        if not all((self.route_id, self.origin_id, self.destination_id, self.geometry_sha256)):
            raise ValueError("la evidencia requiere ruta, arco y hash de geometría")
        if len(self.geometry_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.geometry_sha256):
            raise ValueError("hash de geometría SHA-256 inválido")
        date.fromisoformat(self.reviewed_on)
        if self.review_status not in {"pendiente", "revisado"}:
            raise ValueError("review_status debe ser pendiente o revisado")
        if self.inventory_complete and (self.review_status != "revisado" or not self.inventory_source):
            raise ValueError("la cobertura completa requiere revisión y fuente explícitas")
        if self.matrix_route_equivalent and not self.matrix_equivalence_source:
            raise ValueError("equivalencia con Matrix requiere evidencia")
        ids = [section.section_id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("secciones duplicadas en la evidencia")


def geometry_sha256(route: RouteAlternative) -> str:
    if not route.geometry_lon_lat:
        raise ValueError(f"geometría ausente para {route.alternative_id}")
    encoded = json.dumps(route.geometry_lon_lat, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def load_route_evidence(path: str | Path) -> tuple[RouteEvidence, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("routes"), list):
        raise ValueError("registro de evidencia inválido")
    result = []
    seen = set()
    for item in payload["routes"]:
        sections = tuple(RouteTollSection(**{**section, "evidence": tuple(section["evidence"])})
                         for section in item.get("sections", []))
        record = RouteEvidence(**{**item, "sections": sections})
        if record.route_id in seen:
            raise ValueError(f"route_id duplicado: {record.route_id}")
        seen.add(record.route_id)
        result.append(record)
    return tuple(result)


def assess_evidenced_route(
    route: RouteAlternative, evidence: RouteEvidence, tariffs: Iterable[TollTariff],
    *, as_of: str, vehicle_category: str = "ligero", payment_method: str | None = None,
    time_rule: str | None = None,
) -> RouteTollAssessment:
    if (route.alternative_id != evidence.route_id or route.origin_id != evidence.origin_id
            or route.destination_id != evidence.destination_id or geometry_sha256(route) != evidence.geometry_sha256):
        raise ValueError("la evidencia no corresponde a la geometría y al arco de ORS")
    return assess_route_tolls(
        route.alternative_id, evidence.sections, tariffs, vehicle_category=vehicle_category,
        as_of=as_of, inventory_complete=evidence.inventory_complete,
        inventory_source=evidence.inventory_source or None,
        no_toll_source=evidence.no_toll_source or None,
        payment_method=payment_method, time_rule=time_rule,
    )


@dataclass(frozen=True)
class EconomicArc:
    origin_id: str
    destination_id: str
    route_id: str | None
    duration_hours: float
    fuel_eur: float
    labor_eur: float
    toll_status: str
    verified_section_eur: float | None
    toll_total_eur: float | None
    cost_total_eur: float | None
    reason: str


def build_economic_arcs(
    city_order: tuple[str, ...], duration_hours: np.ndarray, fuel_eur: np.ndarray,
    routes: Iterable[RouteAlternative], evidence: Iterable[RouteEvidence], tariffs: Iterable[TollTariff],
    *, hour_value_eur: float, as_of: str, payment_method: str | None = None,
    time_rule: str | None = None,
) -> tuple[EconomicArc, ...]:
    if not math.isfinite(hour_value_eur) or hour_value_eur < 0:
        raise ValueError("valor de hora inválido")
    date.fromisoformat(as_of)
    n = len(city_order)
    if duration_hours.shape != (n, n) or fuel_eur.shape != (n, n):
        raise ValueError("matrices de tiempo y combustible incompatibles")
    fast = tuple(r for r in routes if r.alternative_id == r.fastest_route_id)
    route_map = {(r.origin_id, r.destination_id): r for r in fast}
    if len(route_map) != len(fast):
        raise ValueError("hay rutas rápidas duplicadas por arco")
    evidence = tuple(evidence)
    evidence_map = {e.route_id: e for e in evidence}
    if len(evidence_map) != len(evidence):
        raise ValueError("route_id duplicado en evidencia")
    tariffs = tuple(tariffs)
    result = []
    for i, origin in enumerate(city_order):
        for j, destination in enumerate(city_order):
            if i == j:
                continue
            route = route_map.get((origin, destination))
            record = evidence_map.get(route.alternative_id) if route else None
            if route is None or record is None:
                result.append(EconomicArc(origin, destination, route.alternative_id if route else None,
                                          float(duration_hours[i, j]), float(fuel_eur[i, j]),
                                          float(hour_value_eur * duration_hours[i, j]),
                                          "UNKNOWN", None, None, None, "ruta o evidencia ausente"))
                continue
            assessment = assess_evidenced_route(route, record, tariffs, as_of=as_of,
                                                payment_method=payment_method, time_rule=time_rule)
            partial = sum(t.amount_eur for t in tariffs if t.tariff_id in assessment.tariff_ids)
            section_amount = partial if assessment.tariff_ids else None
            if assessment.status is TollStatus.UNKNOWN or assessment.amount_eur is None:
                status = "PARTIAL" if assessment.tariff_ids else "UNKNOWN"
                result.append(EconomicArc(origin, destination, route.alternative_id,
                                          float(duration_hours[i, j]), float(fuel_eur[i, j]),
                                          float(hour_value_eur * duration_hours[i, j]), status,
                                          section_amount, None, None,
                                          "; ".join(assessment.unresolved_sections)))
                continue
            # Matrix no contiene geometría: solo se agrega una tarifa Directions
            # cuando una revisión independiente demuestra que es la misma ruta.
            if not record.matrix_route_equivalent:
                result.append(EconomicArc(origin, destination, route.alternative_id,
                                          float(duration_hours[i, j]), float(fuel_eur[i, j]),
                                          float(hour_value_eur * duration_hours[i, j]), "PARTIAL",
                                          section_amount, None, None, "equivalencia Directions/Matrix pendiente"))
                continue
            total = float(hour_value_eur * duration_hours[i, j] + fuel_eur[i, j] + assessment.amount_eur)
            status = "VERIFIED_ZERO" if assessment.amount_eur == 0 else "VERIFIED_AMOUNT"
            result.append(EconomicArc(origin, destination, route.alternative_id,
                                      float(duration_hours[i, j]), float(fuel_eur[i, j]),
                                      float(hour_value_eur * duration_hours[i, j]), status,
                                      section_amount, assessment.amount_eur, total, ""))
    return tuple(result)


def write_economic_arcs(path: str | Path, arcs: Iterable[EconomicArc]) -> None:
    from dataclasses import asdict
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(EconomicArc.__dataclass_fields__))
        writer.writeheader()
        for arc in arcs:
            writer.writerow({key: "" if value is None else value for key, value in asdict(arc).items()})


def require_complete_economic_matrix(city_order: tuple[str, ...], arcs: Iterable[EconomicArc]) -> np.ndarray:
    arcs = tuple(arcs)
    n = len(city_order)
    if len(arcs) != n * (n - 1) or any(arc.cost_total_eur is None for arc in arcs):
        raise ValueError("matriz económica incompleta: hay peajes o rutas sin verificar")
    positions = {city_id: i for i, city_id in enumerate(city_order)}
    matrix = np.zeros((n, n))
    seen = set()
    for arc in arcs:
        pair = (arc.origin_id, arc.destination_id)
        if pair in seen or pair[0] not in positions or pair[1] not in positions or pair[0] == pair[1]:
            raise ValueError("arcos económicos duplicados o fuera del catálogo")
        seen.add(pair)
        matrix[positions[pair[0]], positions[pair[1]]] = arc.cost_total_eur
    if len(seen) != n * (n - 1):
        raise ValueError("matriz económica incompleta")
    matrix.setflags(write=False)
    return matrix
