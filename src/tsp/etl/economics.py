"""Configuración económica parametrizada aplicada a alternativas en memoria."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import yaml

from ..alternatives import RouteAlternative


@dataclass(frozen=True)
class FuelEconomics:
    vehicle_id: str
    fuel_grade: str
    consumption_l_per_100km: Mapping[str, float]
    consumption_basis: str
    consumption_source: str
    price_eur_per_liter: float | None
    price_source: str
    price_reference_date: str
    price_acquired_on: str | None
    study_reference_date: str
    price_status: str

    def __post_init__(self) -> None:
        values = {name: float(value) for name, value in self.consumption_l_per_100km.items()}
        if (set(values) != {"low", "reference", "high"}
                or any(not isfinite(value) or value <= 0 for value in values.values())
                or not values["low"] <= values["reference"] <= values["high"]):
            raise ValueError("consumos deben ser positivos y ordenarse low <= reference <= high")
        object.__setattr__(self, "consumption_l_per_100km", MappingProxyType(values))

    def consumption(self, scenario: str = "reference") -> float:
        try:
            return self.consumption_l_per_100km[scenario]
        except KeyError as exc:
            raise ValueError("scenario debe ser low, reference o high") from exc


def load_fuel_economics(path: str | Path = "configs/tsp_economics.yaml") -> FuelEconomics:
    """Carga y valida parámetros; no realiza llamadas de red."""
    source = Path(path)
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        vehicle, price = data["vehicle"], data["fuel_price"]
        values = {name: float(value) for name, value in vehicle["consumption_l_per_100km"].items()}
        result = FuelEconomics(
            vehicle_id=str(vehicle["id"]), fuel_grade=str(vehicle["fuel"]),
            consumption_l_per_100km=values, consumption_basis=str(vehicle["consumption_basis"]),
            consumption_source=str(vehicle["source"]),
            price_eur_per_liter=None if price["eur_per_liter"] is None else float(price["eur_per_liter"]),
            price_source=str(price["source"]), price_reference_date=str(price["publication_date"]),
            price_acquired_on=price["acquired_on"], study_reference_date=str(data["study_reference_date"]),
            price_status=str(price["status"]),
        )
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"configuración económica inválida en {source}: {exc}") from exc
    if (not result.vehicle_id or result.fuel_grade != "gasoline_95"
            or not result.consumption_basis or not result.consumption_source or not result.price_source):
        raise ValueError("configuración de consumo/vehículo fuera de rango")
    if result.price_eur_per_liter is not None and (
        not isfinite(result.price_eur_per_liter) or result.price_eur_per_liter <= 0
    ):
        raise ValueError("el precio de combustible debe ser finito y positivo")
    if result.price_eur_per_liter is None and result.price_status != "pending_direct_source_verification":
        raise ValueError("un precio ausente debe conservar estado pendiente")
    return result


def apply_fuel_economics(
    alternatives: Iterable[RouteAlternative], economics: FuelEconomics, *, scenario: str = "reference",
) -> tuple[RouteAlternative, ...]:
    """Enriquece copias inmutables sin modificar ni persistir los registros fuente.

    Si el precio no está verificado, consumo y precio se dejan ausentes para que
    la matriz económica permanezca incompleta, nunca igual a un costo cero.
    """
    consumption = economics.consumption(scenario)
    if economics.price_eur_per_liter is None:
        return tuple(replace(route, fuel_consumption_l_per_100km=None,
                             fuel_consumption_source=None, fuel_price_eur_per_l=None,
                             fuel_price_reference=None, vehicle_configuration=None)
                     for route in alternatives)
    reference = (f"{economics.price_source}#publicado={economics.price_reference_date};"
                 f"adquirido={economics.price_acquired_on}")
    source = f"{economics.consumption_source} ({economics.consumption_basis}; escenario={scenario})"
    return tuple(replace(route, fuel_consumption_l_per_100km=consumption,
                         fuel_consumption_source=source,
                         fuel_price_eur_per_l=economics.price_eur_per_liter,
                         fuel_price_reference=reference, vehicle_configuration=economics.vehicle_id)
                 for route in alternatives)
