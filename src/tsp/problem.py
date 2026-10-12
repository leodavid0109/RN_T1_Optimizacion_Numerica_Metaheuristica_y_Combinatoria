"""Modelo matemático y evaluación completa de rutas TSP dirigidas."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Sequence

import numpy as np

from .cities import City
from .matrices import validate_matrix


@dataclass(frozen=True)
class RouteCost:
    """Desglose del costo de una ruta cerrada, con unidades explícitas."""

    closed_route: tuple[int, ...]
    total_distance_km: float
    total_time_hours: float
    seller_time_cost_eur: float
    toll_cost_eur: float
    fuel_cost_eur: float
    total_cost_eur: float


class TSPProblem:
    """TSP dirigido con matrices de componentes de costo para N ciudades."""

    def __init__(
        self,
        cities: Sequence[City],
        distance_km,
        time_hours,
        toll_cost_eur,
        fuel_cost_eur,
        hour_value_eur_per_hour: float,
    ) -> None:
        self.cities = tuple(cities)
        self.size = len(self.cities)
        if self.size < 2:
            raise ValueError("el problema necesita al menos dos ciudades")
        ids = [city.city_id for city in self.cities]
        if len(set(ids)) != self.size:
            raise ValueError("las ciudades del problema deben tener identificadores únicos")

        self.distance_km = validate_matrix(distance_km, self.size, "distancias (km)")
        self.time_hours = validate_matrix(time_hours, self.size, "tiempos (h)")
        self.toll_cost_eur = validate_matrix(toll_cost_eur, self.size, "peajes (EUR)")
        self.fuel_cost_eur = validate_matrix(fuel_cost_eur, self.size, "combustible (EUR)")
        self._hour_value_eur_per_hour = self._validate_hour_value(hour_value_eur_per_hour)

    @property
    def hour_value_eur_per_hour(self) -> float:
        return self._hour_value_eur_per_hour

    @staticmethod
    def _validate_hour_value(value: float) -> float:
        value = float(value)
        if not np.isfinite(value) or value < 0:
            raise ValueError("el valor de la hora debe ser finito y no negativo")
        return value

    def validate_route(self, route: Sequence[int]) -> tuple[int, ...]:
        """Exige una permutación de los índices 0..N-1; el cierre se añade al evaluar."""
        try:
            values = tuple(route)
        except TypeError as exc:
            raise ValueError("la ruta debe ser una secuencia de índices") from exc
        if len(values) != self.size:
            raise ValueError(f"la ruta debe incluir exactamente {self.size} ciudades")
        if any(not isinstance(index, Integral) or isinstance(index, (bool, np.bool_)) for index in values):
            raise ValueError("los índices de ruta deben ser enteros")
        normalized = tuple(int(index) for index in values)
        if set(normalized) != set(range(self.size)):
            raise ValueError("la ruta debe visitar cada índice exactamente una vez")
        return normalized

    def evaluate_route(
        self, route: Sequence[int], hour_value_eur_per_hour: float | None = None
    ) -> RouteCost:
        """Suma cada arco incluyendo el retorno al inicio, con matrices inmutables."""
        order = self.validate_route(route)
        value = self.hour_value_eur_per_hour if hour_value_eur_per_hour is None else self._validate_hour_value(
            hour_value_eur_per_hour
        )
        closed = order + (order[0],)
        origin = np.asarray(closed[:-1], dtype=int)
        destination = np.asarray(closed[1:], dtype=int)

        distance = float(self.distance_km[origin, destination].sum())
        time = float(self.time_hours[origin, destination].sum())
        tolls = float(self.toll_cost_eur[origin, destination].sum())
        fuel = float(self.fuel_cost_eur[origin, destination].sum())
        labor = value * time
        return RouteCost(
            closed_route=closed,
            total_distance_km=distance,
            total_time_hours=time,
            seller_time_cost_eur=labor,
            toll_cost_eur=tolls,
            fuel_cost_eur=fuel,
            total_cost_eur=labor + tolls + fuel,
        )
