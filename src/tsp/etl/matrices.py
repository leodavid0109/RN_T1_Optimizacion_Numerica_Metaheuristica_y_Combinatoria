"""Construcción offline de matrices CSV con pendientes explícitos."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Sequence

import numpy as np

from ..alternatives import RouteAlternative, TollStatus
from ..cities import City


@dataclass(frozen=True)
class MatrixBuildReport:
    city_count: int
    directed_arc_count: int
    routed_arcs: int
    complete_toll_arcs: int
    complete_fuel_arcs: int
    missing_arcs: tuple[str, ...]
    economic_matrix_written: bool
    mode: str


def build_matrix_files(
    cities: Sequence[City],
    alternatives: Sequence[RouteAlternative],
    output_dir: str | Path,
    *,
    mode: str = "fastest",
    hour_value_eur_per_hour: float | None = None,
) -> MatrixBuildReport:
    """Escribe matrices dirigidas desde datos persistidos; no completa valores faltantes.

    Las celdas ausentes se serializan vacías. La matriz económica se escribe solo
    cuando todos los arcos tienen peajes y combustible completos y se proporciona v.
    En modo economic, se elige localmente min(v*T + P + F), con desempate por id.
    """
    if mode not in {"fastest", "economic"}:
        raise ValueError("mode debe ser fastest o economic")
    if mode == "economic" and (hour_value_eur_per_hour is None or not math.isfinite(hour_value_eur_per_hour)
                                or hour_value_eur_per_hour < 0):
        raise ValueError("el modo economic requiere valor horario finito y no negativo")
    cities = tuple(cities)
    if len(cities) < 2 or len({city.city_id for city in cities}) != len(cities):
        raise ValueError("el catálogo de ciudades debe ser único y contener al menos dos ciudades")
    ids = [city.city_id for city in cities]
    by_arc: dict[tuple[str, str], list[RouteAlternative]] = {}
    for record in alternatives:
        if record.origin_id not in ids or record.destination_id not in ids:
            raise ValueError(f"alternativa fuera del catálogo: {record.origin_id}->{record.destination_id}")
        by_arc.setdefault((record.origin_id, record.destination_id), []).append(record)

    selected: dict[tuple[str, str], RouteAlternative] = {}
    missing: list[str] = []
    for origin in ids:
        for destination in ids:
            if origin == destination:
                continue
            candidates = by_arc.get((origin, destination), [])
            if not candidates:
                missing.append(f"{origin}->{destination}:ruta_ausente")
                continue
            if mode == "fastest":
                fastest_ids = {candidate.fastest_route_id for candidate in candidates}
                if len(fastest_ids) != 1:
                    raise ValueError(f"referencias de ruta rápida inconsistentes en {origin}->{destination}")
                fastest_id = next(iter(fastest_ids))
                matching = [candidate for candidate in candidates if candidate.alternative_id == fastest_id]
                if len(matching) != 1:
                    raise ValueError(f"no existe una ruta rápida única para {origin}->{destination}")
                selected[(origin, destination)] = matching[0]
            else:
                for candidate in candidates:
                    _complete_economic_cost(candidate)
                selected[(origin, destination)] = min(
                    candidates,
                    key=lambda item: (hour_value_eur_per_hour * item.duration_hours
                                      + float(item.non_time_cost_eur), item.alternative_id),
                )

    n = len(ids)
    matrices: dict[str, list[list[float | None]]] = {
        name: [[0.0 if row == col else None for col in range(n)] for row in range(n)]
        for name in ("distance_km", "time_hours", "toll_cost_eur", "fuel_cost_eur", "economic_cost_eur")
    }
    complete_toll = complete_fuel = 0
    for (origin, destination), route in selected.items():
        i, j = ids.index(origin), ids.index(destination)
        matrices["distance_km"][i][j] = route.distance_km
        matrices["time_hours"][i][j] = route.duration_hours
        if route.toll_status is not TollStatus.UNKNOWN and route.toll_cost_eur is not None:
            matrices["toll_cost_eur"][i][j] = route.toll_cost_eur
            complete_toll += 1
        else:
            missing.append(f"{origin}->{destination}:peaje_desconocido")
        fuel = route.fuel_cost_eur
        if fuel is not None:
            matrices["fuel_cost_eur"][i][j] = fuel
            complete_fuel += 1
        else:
            missing.append(f"{origin}->{destination}:combustible_pendiente")
        if route.toll_cost_eur is not None and fuel is not None and route.toll_status is not TollStatus.UNKNOWN:
            labor = (hour_value_eur_per_hour or 0.0) * route.duration_hours
            matrices["economic_cost_eur"][i][j] = labor + route.toll_cost_eur + fuel

    expected_arcs = n * (n - 1)
    all_complete = (len(selected) == expected_arcs and complete_toll == expected_arcs
                    and complete_fuel == expected_arcs and hour_value_eur_per_hour is not None)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, matrix in matrices.items():
        if name == "economic_cost_eur" and not all_complete:
            continue
        _write_matrix(out / f"{name}.csv", ids, matrix)
    _write_json_atomic(out / "matrix_manifest.json", {
        "schema_version": 1,
        "mode": mode,
        "city_order": ids,
        "dimensions": [n, n],
        "units": {"distance_km": "km", "time_hours": "h", "toll_cost_eur": "EUR",
                  "fuel_cost_eur": "EUR", "economic_cost_eur": "EUR"},
        "hour_value_eur_per_hour": hour_value_eur_per_hour,
        "economic_matrix_written": all_complete,
        "missing_or_unverified": missing,
        "provenance": "Generado exclusivamente a partir del catálogo local de alternativas.",
    })
    return MatrixBuildReport(n, expected_arcs, len(selected), complete_toll, complete_fuel,
                             tuple(missing), all_complete, mode)


def load_complete_matrix(path: str | Path, city_order: Sequence[str]) -> np.ndarray:
    """Carga una matriz etiquetada solo si sus celdas son completas y el orden coincide."""
    expected = tuple(city_order)
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows or tuple(rows[0][1:]) != expected or rows[0][0] != "city_id":
        raise ValueError("el orden de ciudades de la matriz no coincide con el esperado")
    if len(rows) != len(expected) + 1:
        raise ValueError("la matriz CSV no tiene el número de filas esperado")
    values = []
    for expected_id, row in zip(expected, rows[1:]):
        if len(row) != len(expected) + 1 or row[0] != expected_id:
            raise ValueError("fila de matriz mal formada o fuera de orden")
        if any(not value for value in row[1:]):
            raise ValueError("la matriz contiene celdas ausentes; no puede usarse como matriz completa")
        values.append([float(value) for value in row[1:]])
    from ..matrices import validate_matrix
    return validate_matrix(values, len(expected), Path(path).stem)


def build_fuel_matrix(
    distance_matrix_path: str | Path,
    output_path: str | Path,
    city_order: Sequence[str],
    economics,
    *,
    scenario: str = "reference",
) -> Path:
    """Deriva offline solo combustible desde una matriz completa de distancias (km).

    No escribe una matriz de costo total porque no incorpora ni verifica peajes.
    """
    distances = load_complete_matrix(distance_matrix_path, city_order)
    if economics.price_eur_per_liter is None:
        raise ValueError("no se puede calcular combustible: precio €/L pendiente")
    consumption = economics.consumption(scenario)
    fuel = distances / 100.0 * consumption * economics.price_eur_per_liter
    fuel.setflags(write=False)
    target = Path(output_path)
    _write_matrix(target, list(city_order), fuel.tolist())
    _write_json_atomic(target.with_suffix(target.suffix + ".manifest.json"), {
        "schema_version": 1,
        "matrix_type": "fuel_cost",
        "units": {"distance": "km", "consumption": "L/100 km", "fuel_price": "EUR/L",
                  "fuel_cost": "EUR"},
        "city_order": list(city_order),
        "dimensions": list(fuel.shape),
        "vehicle_id": economics.vehicle_id,
        "fuel_grade": economics.fuel_grade,
        "consumption_l_per_100km": consumption,
        "fuel_price_eur_per_liter": economics.price_eur_per_liter,
        "fuel_price_source": economics.price_source,
        "fuel_price_reference_date": economics.price_reference_date,
        "fuel_price_acquired_on": economics.price_acquired_on,
        "study_reference_date": economics.study_reference_date,
        "scenario": scenario,
        "tolls_included": False,
        "economic_total_created": False,
    })
    return target


def _complete_economic_cost(route: RouteAlternative) -> None:
    if route.toll_status is TollStatus.UNKNOWN or route.toll_cost_eur is None or route.non_time_cost_eur is None:
        raise ValueError(f"costo no verificable para {route.origin_id}->{route.destination_id}/{route.alternative_id}")


def _write_matrix(path: Path, ids: list[str], matrix: list[list[float | None]]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["city_id", *ids])
            for city_id, row in zip(ids, matrix):
                writer.writerow([city_id, *["" if value is None else f"{value:.12g}" for value in row]])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_atomic(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            import json
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
