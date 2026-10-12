"""Modelo de alternativas viales: ruta rápida fija y selección económica local."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from .alternatives import RouteAlternative, TollStatus
from .cities import City
from .problem import RouteCost


class UnverifiableCostError(ValueError):
    """El costo solicitado depende de peajes o combustible sin verificar."""


@dataclass(frozen=True)
class SelectedAlternative:
    """Identificación legible de la alternativa elegida para un arco del tour."""

    origin_id: str
    destination_id: str
    alternative_id: str


class AlternativeTSPProblem:
    """Objetivo TSP dirigido construido a partir de alternativas por arco.

    En ``mode='fastest'`` fija la ruta rápida principal (Modelo A). En
    ``mode='economic'`` elige, de forma independiente para cada arco, la menor
    combinación ``v*T + toll + fuel`` (Modelo B).
    """

    MODES = {"fastest", "economic"}

    def __init__(
        self,
        cities: Sequence[City],
        alternatives: Sequence[RouteAlternative],
        hour_value_eur_per_hour: float,
        mode: str = "economic",
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.cities = tuple(cities)
        self.size = len(self.cities)
        if self.size < 2:
            raise ValueError("el problema necesita al menos dos ciudades")
        self._city_index = {city.city_id: index for index, city in enumerate(self.cities)}
        if len(self._city_index) != self.size:
            raise ValueError("las ciudades deben tener identificadores únicos")
        if mode not in self.MODES:
            raise ValueError("mode debe ser 'fastest' o 'economic'")
        self.mode = mode
        self.model_name = "fixed_fastest" if mode == "fastest" else "economic_alternatives"
        self._hour_value_eur_per_hour = self._validate_hour_value(hour_value_eur_per_hour)
        self.metadata = MappingProxyType(dict(metadata or {}))

        grouped: dict[tuple[str, str], list[RouteAlternative]] = defaultdict(list)
        seen_ids: set[tuple[str, str, str]] = set()
        for alternative in alternatives:
            if alternative.origin_id not in self._city_index or alternative.destination_id not in self._city_index:
                raise ValueError(f"la alternativa {alternative.alternative_id} refiere ciudades ajenas al problema")
            key = (alternative.origin_id, alternative.destination_id)
            record_key = (*key, alternative.alternative_id)
            if record_key in seen_ids:
                raise ValueError(f"identificador de alternativa duplicado para el arco {key}")
            seen_ids.add(record_key)
            grouped[key].append(alternative)

        expected = {
            (origin.city_id, destination.city_id)
            for origin in self.cities for destination in self.cities
            if origin.city_id != destination.city_id
        }
        missing = expected - set(grouped)
        extra = set(grouped) - expected
        if missing or extra:
            sample = sorted(missing or extra)[:3]
            raise ValueError(f"el catálogo debe cubrir todos los arcos dirigidos; arcos problemáticos: {sample}")
        for key, records in grouped.items():
            fastest_ids = {record.fastest_route_id for record in records}
            if len(fastest_ids) != 1:
                raise ValueError(f"el arco {key} declara identificadores de ruta rápida inconsistentes")
            fastest_id = next(iter(fastest_ids))
            matching = [record for record in records if record.alternative_id == fastest_id]
            if len(matching) != 1:
                raise ValueError(f"el arco {key} no incluye exactamente una alternativa rápida {fastest_id}")
            fastest = matching[0]
            if fastest.duration_hours > min(record.duration_hours for record in records):
                raise ValueError(f"la alternativa declarada rápida no es la de menor duración para el arco {key}")
        fuel_settings = {
            (record.fuel_consumption_l_per_100km, record.fuel_price_eur_per_l,
             record.fuel_price_reference, record.vehicle_configuration)
            for records in grouped.values() for record in records
            if record.fuel_consumption_l_per_100km is not None
        }
        if len(fuel_settings) > 1:
            raise ValueError("todas las alternativas con combustible conocido deben compartir vehículo y precio")
        self._alternatives_by_arc = MappingProxyType({
            key: tuple(sorted(value, key=lambda record: record.alternative_id))
            for key, value in grouped.items()
        })

    @staticmethod
    def _validate_hour_value(value: float) -> float:
        value = float(value)
        if not isfinite(value) or value < 0:
            raise ValueError("el valor de la hora debe ser finito y no negativo")
        return value

    @property
    def hour_value_eur_per_hour(self) -> float:
        return self._hour_value_eur_per_hour

    @property
    def alternatives_by_arc(self) -> Mapping[tuple[str, str], tuple[RouteAlternative, ...]]:
        return self._alternatives_by_arc

    def with_hour_value(self, value: float) -> "AlternativeTSPProblem":
        """Devuelve una instancia evaluadora nueva; no altera registros originales."""
        return AlternativeTSPProblem(
            self.cities, tuple(record for records in self._alternatives_by_arc.values() for record in records),
            value, self.mode, self.metadata,
        )

    def validate_route(self, route: Sequence[int]) -> tuple[int, ...]:
        try:
            values = tuple(route)
        except TypeError as exc:
            raise ValueError("la ruta debe ser una secuencia de índices") from exc
        if len(values) != self.size:
            raise ValueError(f"la ruta debe incluir exactamente {self.size} ciudades")
        normalized = []
        for index in values:
            if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)):
                raise ValueError("los índices de ruta deben ser enteros")
            normalized.append(int(index))
        result = tuple(normalized)
        if set(result) != set(range(self.size)):
            raise ValueError("la ruta debe visitar cada índice exactamente una vez")
        return result

    def _select(self, origin_id: str, destination_id: str, hour_value: float) -> RouteAlternative:
        records = self._alternatives_by_arc[(origin_id, destination_id)]
        if self.mode == "fastest":
            fastest_id = records[0].fastest_route_id
            selected = next(record for record in records if record.alternative_id == fastest_id)
            self._require_complete_cost(selected)
            return selected
        incomplete = [record.alternative_id for record in records
                      if record.toll_status is TollStatus.UNKNOWN or record.non_time_cost_eur is None]
        if incomplete:
            raise UnverifiableCostError(
                f"costo no verificable para {origin_id}->{destination_id}; "
                f"alternativas incompletas: {', '.join(sorted(incomplete))}"
            )
        # El segundo criterio fija un desempate estable e independiente del orden de entrada.
        return min(records, key=lambda record: (
            hour_value * record.duration_hours + float(record.non_time_cost_eur), record.alternative_id
        ))

    @staticmethod
    def _require_complete_cost(record: RouteAlternative) -> None:
        if record.toll_status is TollStatus.UNKNOWN or record.non_time_cost_eur is None:
            raise UnverifiableCostError(
                f"costo no verificable para {record.origin_id}->{record.destination_id} "
                f"en la alternativa {record.alternative_id}"
            )

    def cost_matrix_for_hour(self, hour_value_eur_per_hour: float) -> np.ndarray:
        value = self._validate_hour_value(hour_value_eur_per_hour)
        costs = np.zeros((self.size, self.size), dtype=float)
        for (origin_id, destination_id), records in self._alternatives_by_arc.items():
            selected = self._select(origin_id, destination_id, value)
            origin, destination = self._city_index[origin_id], self._city_index[destination_id]
            costs[origin, destination] = value * selected.duration_hours + float(selected.non_time_cost_eur)
        costs.setflags(write=False)
        return costs

    @property
    def cost_matrix_eur(self) -> np.ndarray:
        """Matriz económica dirigida para el valor horario de esta instancia."""
        return self.cost_matrix_for_hour(self.hour_value_eur_per_hour)

    def selected_alternatives_for_route(
        self, route: Sequence[int], hour_value_eur_per_hour: float | None = None,
    ) -> tuple[SelectedAlternative, ...]:
        order = self.validate_route(route)
        value = self.hour_value_eur_per_hour if hour_value_eur_per_hour is None else self._validate_hour_value(
            hour_value_eur_per_hour
        )
        closed = order + (order[0],)
        return tuple(
            SelectedAlternative(
                self.cities[origin].city_id, self.cities[destination].city_id,
                self._select(self.cities[origin].city_id, self.cities[destination].city_id, value).alternative_id,
            )
            for origin, destination in zip(closed[:-1], closed[1:])
        )

    def get_alternative(self, origin_id: str, destination_id: str, alternative_id: str) -> RouteAlternative:
        """Recupera el registro de procedencia a partir de la selección evaluada."""
        for record in self._alternatives_by_arc[(origin_id, destination_id)]:
            if record.alternative_id == alternative_id:
                return record
        raise KeyError((origin_id, destination_id, alternative_id))

    def evaluate_route(
        self, route: Sequence[int], hour_value_eur_per_hour: float | None = None,
    ) -> RouteCost:
        order = self.validate_route(route)
        value = self.hour_value_eur_per_hour if hour_value_eur_per_hour is None else self._validate_hour_value(
            hour_value_eur_per_hour
        )
        closed = order + (order[0],)
        chosen = tuple(
            self._select(self.cities[origin].city_id, self.cities[destination].city_id, value)
            for origin, destination in zip(closed[:-1], closed[1:])
        )
        distance = sum(record.distance_km for record in chosen)
        time = sum(record.duration_hours for record in chosen)
        tolls = sum(float(record.toll_cost_eur) for record in chosen)
        fuel = sum(float(record.fuel_cost_eur) for record in chosen)
        labor = value * time
        return RouteCost(
            closed_route=closed,
            total_distance_km=distance,
            total_time_hours=time,
            seller_time_cost_eur=labor,
            toll_cost_eur=tolls,
            fuel_cost_eur=fuel,
            total_cost_eur=labor + tolls + fuel,
            selected_alternative_ids=tuple(record.alternative_id for record in chosen),
        )
