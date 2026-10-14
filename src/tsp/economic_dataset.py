"""Carga offline de la instancia económica nacional (matrices del 13-10-2026) como un ``TSPProblem``.

El paquete ``data/datasets/spain_tsp_economic_20261013`` publica el costo total por arco dirigido para
tres valores de la hora (``model_a_v{10,25,50}_eur.csv``). Esas matrices son ``v*T + peaje + combustible``;
sus componentes están en ``toll_components.csv``. Cargar los componentes (y no solo la matriz de un ``v``)
permite estudiar cualquier valor de la hora sin perder el desglose por ruta. Para los valores publicados el
cargador comprueba que el costo reconstruido coincida con la matriz publicada.

ADVERTENCIA de alcance: los peajes del paquete son EXPERIMENTALES (no son un tarifario verificado). En
2162 arcos hay 1136 con proxy sin calibrar (0,14145 EUR por km de tramo de peaje), 1020 con cero asumido
desde ORS y solo 6 con inferencia oficial. Todo resultado debe declarar ese alcance.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .cities import load_city_catalog
from .problem import TSPProblem

DEFAULT_DATASET = "data/datasets/spain_tsp_economic_20261013"
PUBLISHED_HOUR_VALUES = (10, 25, 50)
SCOPE_WITH_TOLLS = "MODELO A EXPERIMENTAL: peajes proxy/supuestos, no es un tarifario verificado"
SCOPE_WITHOUT_TOLLS = "BASELINE SIN PEAJES: v*T + combustible; no es el costo económico total"


def load_economic_problem(
    dataset_dir: str | Path = DEFAULT_DATASET,
    hour_value: float = 25.0,
    include_tolls: bool = True,
    verify: bool = True,
) -> TSPProblem:
    """Construye el problema dirigido de 47 ciudades con los componentes del paquete económico."""
    root = Path(dataset_dir)
    cities = load_city_catalog(root / "cities.csv")
    n = len(cities)
    index = {city.city_id: i for i, city in enumerate(cities)}
    distance, hours, fuel, toll = (np.zeros((n, n)) for _ in range(4))
    seen = np.zeros((n, n), dtype=bool)
    with (root / "toll_components.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            i, j = index[row["origin_id"]], index[row["destination_id"]]
            if i == j or seen[i, j]:
                raise ValueError(f"arco repetido o inválido: {row['origin_id']} -> {row['destination_id']}")
            seen[i, j] = True
            distance[i, j] = float(row["distance_km"])
            hours[i, j] = float(row["duration_hours"])
            fuel[i, j] = float(row["fuel_eur"])
            toll[i, j] = float(row["toll_eur_base"])
    off_diagonal = ~np.eye(n, dtype=bool)
    if not seen[off_diagonal].all():
        raise ValueError("toll_components.csv no cubre todos los arcos dirigidos")

    problem = TSPProblem(cities, distance, hours, toll if include_tolls else np.zeros((n, n)), fuel, hour_value)
    problem.model_name = "model_a_economico_experimental" if include_tolls else "baseline_sin_peajes"
    problem.scope = SCOPE_WITH_TOLLS if include_tolls else SCOPE_WITHOUT_TOLLS
    if verify and include_tolls:
        _verify_against_published(problem, root, hour_value)
    return problem


def load_published_matrix(path: str | Path, city_ids: list[str]) -> np.ndarray:
    """Lee una matriz publicada (``city_id`` + 47 columnas) validando el orden de las ciudades."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if [row["city_id"] for row in rows] != city_ids:
        raise ValueError(f"el orden de ciudades de {Path(path).name} no coincide con cities.csv")
    return np.array([[float(row[city]) for city in city_ids] for row in rows])


def _verify_against_published(problem: TSPProblem, root: Path, hour_value: float) -> None:
    if not float(hour_value).is_integer() or int(hour_value) not in PUBLISHED_HOUR_VALUES:
        return  # valor sin matriz publicada: no hay contra qué comparar
    path = root / f"model_a_v{int(hour_value)}_eur.csv"
    if not path.exists():
        return
    published = load_published_matrix(path, [city.city_id for city in problem.cities])
    if not np.allclose(problem.cost_matrix_for_hour(hour_value), published, rtol=0.0, atol=1e-6):
        raise ValueError(f"los componentes no reproducen {path.name}: revise el paquete de datos")
