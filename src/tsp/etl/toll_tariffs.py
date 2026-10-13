"""Importación y aplicación conservadora de tarifas oficiales de peaje.

El CSV normalizado es una transcripción revisable de una fuente oficial. Este
módulo no intenta extraer importes de PDF mediante OCR ni adivina estaciones.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date
import math
from pathlib import Path
import re
from typing import Iterable

from ..alternatives import RouteAlternative, TollStatus


TARIFF_REQUIRED_FIELDS = (
    "tariff_id", "operator", "road", "entry_station", "exit_station", "direction",
    "vehicle_category", "amount_eur", "valid_from", "valid_through", "source_url",
    "published_on", "acquired_on", "payment_conditions", "verification_status", "notes",
)
TARIFF_OPTIONAL_FIELDS = ("payment_method", "time_rule", "source_document", "source_page")
TARIFF_FIELDS = TARIFF_REQUIRED_FIELDS + TARIFF_OPTIONAL_FIELDS


@dataclass(frozen=True)
class TollTariff:
    tariff_id: str
    operator: str
    road: str
    entry_station: str
    exit_station: str
    direction: str
    vehicle_category: str
    amount_eur: float
    valid_from: str
    valid_through: str
    source_url: str
    published_on: str
    acquired_on: str
    payment_conditions: str
    verification_status: str
    notes: str = ""
    payment_method: str = "unknown"
    time_rule: str = ""
    source_document: str = ""
    source_page: str = ""

    def __post_init__(self) -> None:
        for field in ("tariff_id", "operator", "road", "entry_station", "exit_station", "direction",
                      "vehicle_category", "source_url", "payment_conditions"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} no puede estar vacío")
        amount = float(self.amount_eur)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("amount_eur debe ser finito y no negativo")
        object.__setattr__(self, "amount_eur", amount)
        for field in ("valid_from", "valid_through", "acquired_on"):
            date.fromisoformat(getattr(self, field))
        if self.published_on:
            date.fromisoformat(self.published_on)
        if self.valid_from > self.valid_through:
            raise ValueError("intervalo de vigencia invertido")
        if self.verification_status not in {"verificado_con_peaje", "verificado_sin_peaje"}:
            raise ValueError("la tarifa debe tener estado de verificación explícito")
        if self.verification_status == "verificado_con_peaje" and amount <= 0:
            raise ValueError("una tarifa pagada debe ser positiva; importe cero no corresponde a verificado_con_peaje")
        if self.verification_status == "verificado_sin_peaje" and amount != 0:
            raise ValueError("verificado_sin_peaje requiere importe cero")

    def applies_on(self, on_date: str) -> bool:
        date.fromisoformat(on_date)
        return self.valid_from <= on_date <= self.valid_through


@dataclass(frozen=True)
class RouteTollSection:
    """Sección ya resuelta a estaciones y sentido mediante evidencia revisada."""

    section_id: str
    operator: str | None
    road: str | None
    entry_station: str | None
    exit_station: str | None
    direction: str | None
    route_match_verified: bool
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.section_id.strip():
            raise ValueError("section_id no puede estar vacío")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.route_match_verified and not self.evidence:
            raise ValueError("una sección verificada requiere evidencia registrada")


@dataclass(frozen=True)
class RouteTollAssessment:
    route_id: str
    status: TollStatus
    amount_eur: float | None
    currency: str
    checked_on: str
    source_references: tuple[str, ...]
    tariff_ids: tuple[str, ...]
    unresolved_sections: tuple[str, ...]
    method: str


def import_official_tariffs_csv(path: str | Path) -> tuple[TollTariff, ...]:
    """Lee CSV UTF-8 con los campos normalizados y rechaza filas ambiguas."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(TARIFF_REQUIRED_FIELDS).issubset(reader.fieldnames):
            missing = sorted(set(TARIFF_REQUIRED_FIELDS) - set(reader.fieldnames or ()))
            raise ValueError(f"faltan columnas tarifarias: {', '.join(missing)}")
        records = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            if not row.get("tariff_id", "").strip():
                raise ValueError(f"tariff_id vacío en línea {line_number}")
            if row["tariff_id"] in seen:
                raise ValueError(f"tariff_id duplicado en línea {line_number}: {row['tariff_id']}")
            seen.add(row["tariff_id"])
            amount_text = row["amount_eur"].strip()
            # Permite decimal con coma usado en algunos documentos, no separadores de miles.
            if "," in amount_text and "." not in amount_text:
                amount_text = amount_text.replace(",", ".")
            values = {field: row.get(field, "").strip() for field in TARIFF_FIELDS}
            values["payment_method"] = values["payment_method"] or "unknown"
            records.append(TollTariff(**{**values, "amount_eur": float(amount_text)}))
    return tuple(records)


def export_official_tariffs_csv(path: str | Path, records: Iterable[TollTariff]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TARIFF_FIELDS)
        writer.writeheader()
        for record in records:
            row = {field: getattr(record, field) for field in TARIFF_FIELDS}
            row["amount_eur"] = f"{record.amount_eur:.6f}".rstrip("0").rstrip(".")
            writer.writerow(row)


def assess_route_tolls(
    route_id: str,
    sections: Iterable[RouteTollSection],
    tariffs: Iterable[TollTariff],
    *,
    vehicle_category: str,
    as_of: str,
    inventory_complete: bool = False,
    inventory_source: str | None = None,
    no_toll_source: str | None = None,
) -> RouteTollAssessment:
    """Calcula importe solo para secciones verificadas y tarifas vigentes exactas.

    Para declarar 0 EUR se requiere inventario explícitamente completo y fuente
    que confirme la ausencia de peaje. De otro modo el resultado es desconocido.
    """
    date.fromisoformat(as_of)
    sections, tariffs = tuple(sections), tuple(tariffs)
    ids = [section.section_id for section in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("secciones duplicadas: se previene cobrar dos veces el mismo tramo")
    if not inventory_complete:
        return RouteTollAssessment(route_id, TollStatus.UNKNOWN, None, "EUR", as_of, (), (),
                                   ("inventario de secciones de la ruta incompleto",),
                                   "no se calcula un total con cobertura tarifaria parcial")
    if not sections:
        if no_toll_source:
            return RouteTollAssessment(route_id, TollStatus.VERIFIED_WITHOUT_TOLL, 0.0, "EUR", as_of,
                                       (no_toll_source,), (), (), "inventario completo confirma ausencia de sección tarifada")
        return RouteTollAssessment(route_id, TollStatus.UNKNOWN, None, "EUR", as_of, (), (),
                                   ("cobertura tarifaria no demostrada",), "sin secciones cobradas identificadas")
    if not inventory_source:
        return RouteTollAssessment(route_id, TollStatus.UNKNOWN, None, "EUR", as_of, (), (),
                                   ("fuente de cobertura de la ruta ausente",),
                                   "no se calcula un total sin fuente de cobertura")

    total = 0.0
    refs: list[str] = [inventory_source]
    tariff_ids: list[str] = []
    unresolved: list[str] = []
    for section in sections:
        if (not section.route_match_verified or not section.operator or not section.road
                or not section.entry_station or not section.exit_station
                or not section.direction):
            unresolved.append(section.section_id)
            continue
        matches = [tariff for tariff in tariffs if (
            _norm(tariff.entry_station) == _norm(section.entry_station)
            and _norm(tariff.exit_station) == _norm(section.exit_station)
            and _norm(tariff.direction) == _norm(section.direction)
            and _norm(tariff.operator) == _norm(section.operator)
            and _norm(tariff.road) == _norm(section.road)
            and _norm(tariff.vehicle_category) == _norm(vehicle_category)
            and tariff.applies_on(as_of)
        )]
        if len(matches) != 1:
            unresolved.append(section.section_id)
            continue
        tariff = matches[0]
        total += tariff.amount_eur
        tariff_ids.append(tariff.tariff_id)
        refs.append(tariff.source_url)
        refs.extend(section.evidence)

    if unresolved:
        return RouteTollAssessment(route_id, TollStatus.UNKNOWN, None, "EUR", as_of,
                                   tuple(dict.fromkeys(refs)), tuple(tariff_ids), tuple(unresolved),
                                   "suma de secciones verificadas; total incompleto")
    status = TollStatus.VERIFIED_WITH_TOLL if total > 0 else TollStatus.VERIFIED_WITHOUT_TOLL
    return RouteTollAssessment(route_id, status, total, "EUR", as_of,
                               tuple(dict.fromkeys(refs)), tuple(tariff_ids), (),
                               "suma de tarifas oficiales por entrada, salida, sentido y categoría")


def apply_toll_assessment(route: RouteAlternative, assessment: RouteTollAssessment) -> RouteAlternative:
    """Proyecta una evaluación completa sobre RouteAlternative sin tocar su origen."""
    if assessment.route_id != route.alternative_id:
        raise ValueError("la evaluación tarifaria no corresponde a esta alternativa")
    if assessment.status is TollStatus.UNKNOWN or assessment.amount_eur is None:
        return route
    return replace(
        route,
        toll_status=assessment.status,
        toll_cost_eur=assessment.amount_eur,
        toll_source=";".join(assessment.source_references),
        toll_checked_on=assessment.checked_on,
        toll_valid_from=assessment.checked_on,
        toll_valid_through=assessment.checked_on,
    )


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
