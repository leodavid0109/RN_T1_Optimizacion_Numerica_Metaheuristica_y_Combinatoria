"""Validaciones offline de matriz ORS frente a rutas Directions ya persistidas."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from ..alternatives import RouteAlternative


@dataclass(frozen=True)
class MatrixDirectionsDifference:
    origin_id: str
    destination_id: str
    matrix_distance_km: float
    directions_distance_km: float
    absolute_distance_difference_km: float
    distance_difference_percent: float
    matrix_duration_hours: float
    directions_duration_hours: float
    absolute_duration_difference_hours: float
    duration_difference_percent: float


def compare_matrix_to_directions(
    city_order: Sequence[str],
    distance_km,
    duration_hours,
    alternatives: Sequence[RouteAlternative],
) -> tuple[MatrixDirectionsDifference, ...]:
    """Compara seis u otros arcos emparejados; porcentaje relativo a Directions.

    Solo usa el registro identificado como ruta rápida principal. Diferencias no
    implican por sí solas un error: los endpoints no garantizan geometría idéntica.
    """
    ids = tuple(city_order)
    size = len(ids)
    if size < 2 or len(set(ids)) != size:
        raise ValueError("city_order debe contener ids únicos")
    if (len(distance_km) != size or len(duration_hours) != size
            or any(len(row) != size for row in distance_km)
            or any(len(row) != size for row in duration_hours)):
        raise ValueError("las matrices deben coincidir con el orden de ciudades")
    positions = {city_id: index for index, city_id in enumerate(ids)}
    fastest: dict[tuple[str, str], RouteAlternative] = {}
    for route in alternatives:
        if route.alternative_id != route.fastest_route_id:
            continue
        key = (route.origin_id, route.destination_id)
        if key in fastest:
            raise ValueError(f"hay más de una ruta rápida registrada para {key[0]}->{key[1]}")
        fastest[key] = route
    rows = []
    for (origin, destination), route in sorted(fastest.items()):
        if origin not in positions or destination not in positions:
            raise ValueError(f"el arco Directions está fuera del orden de matriz: {origin}->{destination}")
        i, j = positions[origin], positions[destination]
        md = float(distance_km[i][j])
        mt = float(duration_hours[i][j])
        dd, dt = route.distance_km, route.duration_hours
        values = (md, mt, dd, dt)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError(f"valor inválido al comparar {origin}->{destination}")
        rows.append(MatrixDirectionsDifference(
            origin, destination, md, dd, abs(md - dd), abs(md - dd) / dd * 100.0,
            mt, dt, abs(mt - dt), abs(mt - dt) / dt * 100.0,
        ))
    return tuple(rows)
