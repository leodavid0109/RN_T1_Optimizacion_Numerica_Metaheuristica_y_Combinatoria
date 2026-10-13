"""ACO offline de validación algorítmica: tiempo y combustible, peajes excluidos."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from src.tsp import AntSystem, City, TSPProblem
from src.tsp.etl.dataset_export import load_published_dataset


SCENARIO = "Escenario auxiliar de validación algorítmica — no representa el costo económico total"


def run_auxiliary(dataset_dir: Path, hour_value: float, seed: int, budget: int) -> dict:
    dataset = load_published_dataset(dataset_dir)
    with (dataset_dir / "cities.csv").open(encoding="utf-8", newline="") as stream:
        cities = tuple(City(**{**row, "latitude": float(row["latitude"]),
                                "longitude": float(row["longitude"])}) for row in csv.DictReader(stream))
    if tuple(city.city_id for city in cities) != dataset["city_order"]:
        raise ValueError("orden de ciudades incompatible con el dataset")
    # La matriz cero es una exclusión explícita del componente de peajes en
    # este escenario auxiliar; nunca se reutiliza como tarifa verificada.
    auxiliary = TSPProblem(cities, dataset["distance_km"], dataset["duration_hours"],
                           np.zeros_like(dataset["distance_km"]), dataset["fuel_reference_eur"], hour_value)
    started = perf_counter()
    result = AntSystem().run(auxiliary, seed=seed, budget=budget,
                             n_ants=10, alpha=1.0, beta=2.0, rho=0.5, q=1.0, tau0=1.0)
    elapsed = perf_counter() - started
    return {"scenario": SCENARIO, "hour_value_eur": hour_value, "seed": seed,
            "budget": budget, "objective_evaluations": result.objective_evaluations,
            "best_city_order": [cities[i].city_id for i in result.best_route],
            "total_time_hours": result.best_breakdown.total_time_hours,
            "fuel_eur": result.best_breakdown.fuel_cost_eur,
            "auxiliary_cost_eur": result.best_cost_eur,
            "convergence": [{"evaluations": p.evaluations, "best_cost_eur": p.best_cost_eur}
                            for p in result.history], "runtime_seconds": elapsed,
            "tolls_included": False, "dataset": str(dataset_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--hour-values", default="10,25,50")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/aco_auxiliary.json"))
    args = parser.parse_args(argv)
    payload = [run_auxiliary(args.dataset, float(value), args.seed, args.budget)
               for value in args.hour_values.split(",")]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{"hour_value_eur": item["hour_value_eur"],
                       "objective_evaluations": item["objective_evaluations"],
                       "auxiliary_cost_eur": item["auxiliary_cost_eur"]} for item in payload],
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
