"""Run paired 30-seed ACO repetitions on the complete experimental Model A.

The baseline experiment lives in ``run_tsp_baseline_repetitions``. This module
only reads the already built economic bundle; it does not use network access.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter

import numpy as np

from experiments.run_tsp_baseline_repetitions import DEFAULT_SEEDS, DEFAULT_DATASET
from src.tsp import AntSystem, City, TSPProblem


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/datasets/spain_tsp_economic_20261013"
DEFAULT_OUTPUT_JSON = ROOT / "data/processed/tsp/model_a_experimental_aco_30_runs.json"
HOURS = (10.0, 25.0, 50.0)


def load_model_a_problem(bundle_dir: Path, dataset_dir: Path, hour_value: float):
    with (dataset_dir / "cities.csv").open(encoding="utf-8", newline="") as stream:
        cities = tuple(City(**{**row, "latitude": float(row["latitude"]),
                               "longitude": float(row["longitude"])})
                       for row in csv.DictReader(stream))
    order = tuple(city.city_id for city in cities)
    if len(order) != 47 or len(set(order)) != 47:
        raise ValueError("el catálogo del TSP debe contener 47 ciudades únicas")
    index = {city: i for i, city in enumerate(order)}
    distance = np.zeros((47, 47), dtype=float)
    duration = np.zeros((47, 47), dtype=float)
    fuel = np.zeros((47, 47), dtype=float)
    toll = np.zeros((47, 47), dtype=float)
    with (bundle_dir / "toll_components.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = 47 * 46
    if len(rows) != expected or len({(row["origin_id"], row["destination_id"]) for row in rows}) != expected:
        raise ValueError("toll_components.csv no contiene los 2.162 arcos únicos")
    for row in rows:
        i, j = index[row["origin_id"]], index[row["destination_id"]]
        distance[i, j] = float(row["distance_km"])
        duration[i, j] = float(row["duration_hours"])
        fuel[i, j] = float(row["fuel_eur"])
        toll[i, j] = float(row["toll_eur_base"])
    for matrix, label in ((distance, "distance"), (duration, "duration"),
                          (fuel, "fuel"), (toll, "toll")):
        if not np.all(np.isfinite(matrix)) or np.any(matrix < 0):
            raise ValueError(f"componente {label} inválido")
    problem = TSPProblem(cities, distance, duration, toll, fuel, hour_value)
    with (bundle_dir / f"model_a_v{int(hour_value)}_eur.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        matrix_rows = list(csv.DictReader(stream))
    expected_matrix = np.array([[float(row[city]) for city in order] for row in matrix_rows])
    if not np.allclose(problem.cost_matrix_eur, expected_matrix, rtol=1e-12, atol=1e-10):
        raise ValueError("TSPProblem no reproduce el costo publicado del Modelo A")
    return problem, cities


def run_repetitions(
    *, bundle_dir: Path = DEFAULT_OUTPUT, dataset_dir: Path = DEFAULT_DATASET,
    hour_values: tuple[float, ...] = HOURS, seeds: tuple[int, ...] = DEFAULT_SEEDS,
    budget: int = 100,
) -> dict:
    if len(seeds) != 30 or len(set(seeds)) != 30:
        raise ValueError("el protocolo requiere 30 semillas independientes")
    records = []
    summaries = []
    for value in hour_values:
        problem, cities = load_model_a_problem(bundle_dir, dataset_dir, value)
        results = []
        for seed in seeds:
            started = perf_counter()
            result = AntSystem().run(
                problem, seed=seed, budget=budget, n_ants=10,
                alpha=1.0, beta=2.0, rho=0.5, q=1.0, tau0=1.0,
            )
            runtime = perf_counter() - started
            if len(result.best_route) != 47 or len(set(result.best_route)) != 47:
                raise ValueError("ACO produjo una permutación inválida")
            closed = result.best_route + (result.best_route[0],)
            if len(closed) != 48 or result.objective_evaluations != budget:
                raise ValueError("ACO no respetó el cierre o presupuesto")
            row = {
                "scenario": "MODEL_A_EXPERIMENTAL_PROXY_BASE",
                "hour_value_eur_per_hour": value, "seed": seed,
                "budget_requested": budget, "objective_evaluations": result.objective_evaluations,
                "best_cost_eur": result.best_cost_eur,
                "distance_km": result.best_breakdown.total_distance_km,
                "duration_hours": result.best_breakdown.total_time_hours,
                "fuel_eur": result.best_breakdown.fuel_cost_eur,
                "toll_eur": result.best_breakdown.toll_cost_eur,
                "runtime_seconds": runtime,
                "tour_city_ids": [cities[i].city_id for i in result.best_route],
                "closed_tour_city_ids": [cities[i].city_id for i in closed],
                "tolls_are_estimated": True,
                "convergence": [{"evaluations": point.evaluations,
                                 "best_cost_eur": point.best_cost_eur}
                                for point in result.history],
            }
            records.append(row)
            results.append(row)
        costs = [row["best_cost_eur"] for row in results]
        summaries.append({
            "scenario": "MODEL_A_EXPERIMENTAL_PROXY_BASE",
            "hour_value_eur_per_hour": value, "runs": len(results),
            "objective_budget_each": budget,
            "best_cost_min_eur": min(costs), "best_cost_mean_eur": mean(costs),
            "best_cost_sample_std_eur": stdev(costs), "best_cost_max_eur": max(costs),
            "runtime_mean_seconds": mean(row["runtime_seconds"] for row in results),
        })
    return {
        "schema_version": 1, "dataset": "data/datasets/spain_tsp_economic_20261013",
        "scenario": "MODEL A experimental base proxy; not a verified tariff matrix",
        "objective": "v * Directions_duration + fuel_from_Directions_distance + experimental_toll",
        "algorithm": "AntSystem", "seeds": list(seeds), "budget_each": budget,
        "algorithm_parameters": {"n_ants": 10, "alpha": 1.0, "beta": 2.0,
                                 "rho": 0.5, "q": 1.0, "tau0": 1.0},
        "summaries": summaries, "runs": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--budget", type=int, default=100)
    args = parser.parse_args()
    result = run_repetitions(bundle_dir=args.bundle, dataset_dir=args.dataset, budget=args.budget)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summaries"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
