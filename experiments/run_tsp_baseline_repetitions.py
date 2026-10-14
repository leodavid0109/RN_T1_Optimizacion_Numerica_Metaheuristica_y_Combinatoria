"""Ejecuta 30 corridas ACO reproducibles sobre el baseline nacional sin peajes."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter

import numpy as np

from src.tsp import AntSystem, City, TSPProblem
from src.tsp.etl.dataset_export import load_published_dataset


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/datasets/spain_tsp_2026"
DEFAULT_OUTPUT = ROOT / "data/processed/tsp/baseline_aco_30_runs.json"
DEFAULT_SEEDS = tuple(range(20261014, 20261044))
HOUR_VALUES = (10.0, 25.0, 50.0)


def load_baseline_problem(dataset_dir: Path, hour_value: float) -> tuple[TSPProblem, tuple[City, ...]]:
    """Carga exclusivamente datos del dataset versionado; no usa red ni snapshots."""
    dataset = load_published_dataset(dataset_dir)
    with (dataset_dir / "cities.csv").open(encoding="utf-8", newline="") as stream:
        cities = tuple(
            City(**{**row, "latitude": float(row["latitude"]), "longitude": float(row["longitude"])})
            for row in csv.DictReader(stream)
        )
    if tuple(city.city_id for city in cities) != dataset["city_order"]:
        raise ValueError("el catálogo no coincide con el orden de las matrices")
    if hour_value not in (10, 25, 50):
        raise ValueError("el baseline publicado admite v=10, 25 o 50 EUR/h")
    problem = TSPProblem(
        cities,
        dataset["distance_km"],
        dataset["duration_hours"],
        np.zeros_like(dataset["distance_km"]),
        dataset["fuel_reference_eur"],
        hour_value,
    )
    # Reconcile constructed objective against the published canonical matrix.
    expected = dataset[f"baseline_cost_v_{int(hour_value)}_eur"]
    if not np.allclose(problem.cost_matrix_eur, expected, rtol=1e-13, atol=1e-12):
        raise ValueError("la instancia TSP no reproduce la matriz base publicada")
    return problem, cities


def run_repetitions(
    dataset_dir: Path,
    *,
    hour_values: tuple[float, ...] = HOUR_VALUES,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    budget: int = 100,
) -> dict:
    if len(seeds) != 30 or len(set(seeds)) != 30:
        raise ValueError("el protocolo requiere exactamente 30 semillas únicas")
    if budget < 1:
        raise ValueError("budget debe ser positivo")
    records = []
    summaries = []
    for value in hour_values:
        problem, cities = load_baseline_problem(dataset_dir, value)
        results = []
        for seed in seeds:
            started = perf_counter()
            result = AntSystem().run(
                problem, seed=seed, budget=budget,
                n_ants=10, alpha=1.0, beta=2.0, rho=0.5, q=1.0, tau0=1.0,
            )
            runtime = perf_counter() - started
            if len(result.best_route) != 47 or len(set(result.best_route)) != 47:
                raise ValueError("ACO produjo un tour inválido")
            closed = result.best_route + (result.best_route[0],)
            if len(closed) != 48:
                raise ValueError("el tour no incluye correctamente el cierre")
            row = {
                "hour_value_eur_per_hour": value,
                "seed": seed,
                "budget_requested": budget,
                "objective_evaluations": result.objective_evaluations,
                "best_cost_eur": result.best_cost_eur,
                "total_time_hours": result.best_breakdown.total_time_hours,
                "fuel_eur": result.best_breakdown.fuel_cost_eur,
                "toll_eur": result.best_breakdown.toll_cost_eur,
                "runtime_seconds": runtime,
                "tour_city_ids": [cities[index].city_id for index in result.best_route],
                "closed_tour_city_ids": [cities[index].city_id for index in closed],
                "convergence": [
                    {"evaluations": point.evaluations, "best_cost_eur": point.best_cost_eur}
                    for point in result.history
                ],
                "tolls_included": False,
                "scenario": "BASELINE SIN COMPONENTE DE PEAJES",
            }
            results.append(row)
            records.append(row)
        costs = [item["best_cost_eur"] for item in results]
        runtimes = [item["runtime_seconds"] for item in results]
        summaries.append({
            "hour_value_eur_per_hour": value,
            "runs": len(results),
            "objective_budget_each": budget,
            "objective_evaluations_min": min(item["objective_evaluations"] for item in results),
            "objective_evaluations_max": max(item["objective_evaluations"] for item in results),
            "best_cost_min_eur": min(costs),
            "best_cost_mean_eur": mean(costs),
            "best_cost_sample_std_eur": stdev(costs),
            "best_cost_max_eur": max(costs),
            "runtime_mean_seconds": mean(runtimes),
        })
    return {
        "schema_version": 1,
        "dataset": "data/datasets/spain_tsp_2026",
        "scenario": "BASELINE SIN COMPONENTE DE PEAJES",
        "objective": "value_hour_eur_per_hour * duration_hours + fuel_reference_eur",
        "tolls_included": False,
        "algorithm": "AntSystem",
        "algorithm_parameters": {"n_ants": 10, "alpha": 1.0, "beta": 2.0, "rho": 0.5, "q": 1.0, "tau0": 1.0},
        "seed_policy": {"seeds": list(seeds), "paired_across_hour_values": True},
        "summaries": summaries,
        "runs": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--budget", type=int, default=100)
    args = parser.parse_args()
    result = run_repetitions(args.dataset, budget=args.budget)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summaries"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
