"""Registros inmutables de alternativas viales y reglas de dominancia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
from typing import Iterable


class TollStatus(str, Enum):
    """Estado de verificación de la tarifa para la alternativa y fecha indicadas."""

    VERIFIED_WITH_TOLL = "verificado_con_peaje"
    VERIFIED_WITHOUT_TOLL = "verificado_sin_peaje"
    UNKNOWN = "desconocido"


@dataclass(frozen=True)
class RouteAlternative:
    """Una ruta vial dirigida. Los datos ausentes se conservan como ``None``."""

    origin_id: str
    destination_id: str
    alternative_id: str
    fastest_route_id: str
    distance_km: float
    duration_hours: float
    toll_status: TollStatus | str
    toll_cost_eur: float | None
    routing_engine: str
    routing_engine_version: str
    profile: str
    source: str
    acquired_on: str
    network_data_version: str | None = None
    routing_parameters: tuple[tuple[str, str], ...] = ()
    road_references: tuple[str, ...] = ()
    toll_source: str | None = None
    toll_currency: str = "EUR"
    toll_checked_on: str | None = None
    toll_valid_from: str | None = None
    toll_valid_through: str | None = None
    geometry_lon_lat: tuple[tuple[float, float], ...] | None = None
    fuel_consumption_l_per_100km: float | None = None
    fuel_consumption_source: str | None = None
    fuel_price_eur_per_l: float | None = None
    fuel_price_reference: str | None = None
    vehicle_configuration: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "origin_id", "destination_id", "alternative_id", "fastest_route_id",
            "routing_engine", "routing_engine_version", "profile", "source",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} no puede estar vacío")
        if self.origin_id == self.destination_id:
            raise ValueError("una alternativa debe conectar ciudades distintas")
        for field_name in ("distance_km", "duration_hours"):
            _validate_nonnegative(getattr(self, field_name), field_name, allow_zero=False)
            object.__setattr__(self, field_name, float(getattr(self, field_name)))
        status = TollStatus(self.toll_status)
        object.__setattr__(self, "toll_status", status)
        if status is TollStatus.UNKNOWN:
            if self.toll_cost_eur is not None:
                raise ValueError("un peaje desconocido debe tener importe None, no cero")
        else:
            if self.toll_cost_eur is None:
                raise ValueError("una tarifa verificada debe incluir un importe")
            _validate_nonnegative(self.toll_cost_eur, "toll_cost_eur")
            object.__setattr__(self, "toll_cost_eur", float(self.toll_cost_eur))
            if self.toll_currency != "EUR":
                raise ValueError("el modelo económico común utiliza peajes en EUR")
            if status is TollStatus.VERIFIED_WITHOUT_TOLL and self.toll_cost_eur != 0:
                raise ValueError("un trayecto verificado sin peaje debe tener importe cero")
            if status is TollStatus.VERIFIED_WITH_TOLL and self.toll_cost_eur <= 0:
                raise ValueError("verificado_con_peaje requiere un importe positivo")
            if not self.toll_source or not self.toll_checked_on:
                raise ValueError("una verificación de peaje requiere fuente y fecha de consulta")
        _validate_iso_date(self.acquired_on, "acquired_on")
        for field_name in ("toll_checked_on", "toll_valid_from", "toll_valid_through"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_iso_date(value, field_name)
        if self.toll_valid_from and self.toll_valid_through and self.toll_valid_from > self.toll_valid_through:
            raise ValueError("la vigencia de la tarifa tiene fechas invertidas")
        fuel_values = (self.fuel_consumption_l_per_100km, self.fuel_price_eur_per_l)
        if (fuel_values[0] is None) != (fuel_values[1] is None):
            raise ValueError("consumo y precio de combustible deben estar presentes juntos")
        if fuel_values[0] is not None:
            _validate_nonnegative(fuel_values[0], "fuel_consumption_l_per_100km", allow_zero=False)
            _validate_nonnegative(fuel_values[1], "fuel_price_eur_per_l", allow_zero=False)
            object.__setattr__(self, "fuel_consumption_l_per_100km", float(fuel_values[0]))
            object.__setattr__(self, "fuel_price_eur_per_l", float(fuel_values[1]))
            if not self.fuel_price_reference or not self.fuel_consumption_source or not self.vehicle_configuration:
                raise ValueError("el combustible requiere fuentes, referencia de precio y configuración del vehículo")
        if self.geometry_lon_lat is not None:
            geometry = tuple(tuple(float(value) for value in point) for point in self.geometry_lon_lat)
            if len(geometry) < 2 or any(len(point) != 2 for point in geometry):
                raise ValueError("geometry_lon_lat debe contener al menos dos pares longitud/latitud")
            if any(not isfinite(lon) or not isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90
                   for lon, lat in geometry):
                raise ValueError("la geometría contiene coordenadas no válidas")
            object.__setattr__(self, "geometry_lon_lat", geometry)
        routing_parameters = tuple(tuple(pair) for pair in self.routing_parameters)
        if any(len(pair) != 2 or not all(isinstance(part, str) for part in pair)
               for pair in routing_parameters):
            raise ValueError("routing_parameters debe contener pares de cadenas clave/valor")
        if any(not isinstance(value, str) for value in (*self.limitations, *self.road_references)):
            raise ValueError("limitations y road_references deben contener texto")
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "routing_parameters", routing_parameters)
        object.__setattr__(self, "road_references", tuple(self.road_references))

    @property
    def fuel_cost_eur(self) -> float | None:
        """Costo calculado como distancia/100 × consumo × precio, si hay entradas."""
        if self.fuel_consumption_l_per_100km is None or self.fuel_price_eur_per_l is None:
            return None
        return self.distance_km / 100.0 * self.fuel_consumption_l_per_100km * self.fuel_price_eur_per_l

    @property
    def non_time_cost_eur(self) -> float | None:
        """Peaje más combustible; None si alguno de sus componentes no está verificado."""
        fuel = self.fuel_cost_eur
        if self.toll_cost_eur is None or fuel is None:
            return None
        return self.toll_cost_eur + fuel


def _validate_nonnegative(value: float, name: str, allow_zero: bool = True) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{name} debe ser numérico, no booleano")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser numérico") from exc
    if not isfinite(number) or number < 0 or (not allow_zero and number <= 0):
        qualifier = "positivo" if not allow_zero else "finito y no negativo"
        raise ValueError(f"{name} debe ser {qualifier}")


def _validate_iso_date(value: str, name: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe usar formato ISO YYYY-MM-DD") from exc


def remove_dominated_alternatives(
    alternatives: Iterable[RouteAlternative],
) -> tuple[RouteAlternative, ...]:
    """Conserva la frontera no dominada para v >= 0; conserva datos incompletos.

    ``a`` domina a ``b`` si su tiempo y costo no temporal son ambos menores o
    iguales, con al menos una desigualdad estricta. La ruta marcada como rápida
    siempre se conserva para que el Modelo A siga disponible. Una alternativa
    con peaje o combustible desconocido no se elimina por dominancia; solo se
    comparan registros del mismo arco dirigido.
    """
    records = tuple(alternatives)
    kept = []
    for candidate in records:
        # El Modelo A necesita poder reconstruir la ruta rápida aunque otra ruta
        # de igual duración tenga menor costo no temporal.
        if candidate.alternative_id == candidate.fastest_route_id:
            kept.append(candidate)
            continue
        candidate_base = candidate.non_time_cost_eur
        dominated = False
        if candidate_base is not None:
            for other in records:
                if (other is candidate or other.origin_id != candidate.origin_id
                        or other.destination_id != candidate.destination_id):
                    continue
                other_base = other.non_time_cost_eur
                if other_base is None:
                    continue
                if (other.duration_hours <= candidate.duration_hours
                        and other_base <= candidate_base
                        and (other.duration_hours < candidate.duration_hours or other_base < candidate_base)):
                    dominated = True
                    break
        if not dominated:
            kept.append(candidate)
    return tuple(kept)
