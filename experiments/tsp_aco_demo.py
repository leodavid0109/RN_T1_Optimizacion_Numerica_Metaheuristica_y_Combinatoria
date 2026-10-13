"""Demostración offline de Ant System sobre una instancia dirigida sintética."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from src.config import load_config
from src.tsp import AntSystem, City, TSPProblem


def synthetic_problem(hour_value: float) -> TSPProblem:
    """Crea una instancia didáctica sintética; no representa España."""
    size = 5
    cities = tuple(
        City(f"synthetic-{index}", f"Ciudad sintética {index}", f"Provincia sintética {index}",
             0.0, 0.0, "synthetic://aco-demo", "2026-10-12", "verificada",
             "instancia sintética de demostración")
        for index in range(size)
    )
    rng = np.random.default_rng(2026)
    directed = rng.integers(8, 70, size=(size, size)).astype(float)
    np.fill_diagonal(directed, 0.0)
    time = rng.uniform(0.05, 0.8, size=(size, size))
    np.fill_diagonal(time, 0.0)
    # Los valores dirigidos son únicamente costos sintéticos en EUR; el tiempo
    # se incluye por separado para que el desglose del resultado sea ilustrativo.
    toll = directed
    return TSPProblem(cities, np.zeros_like(directed), time, toll, np.zeros_like(directed), hour_value)


def run_demo(config: dict) -> dict:
    problem = synthetic_problem(float(config["valor_hora_eur_h"]))
    parameters = dict(config["aco"])
    started = perf_counter()
    result = AntSystem().run(problem, int(config["semilla"]), int(config["presupuesto"]), **parameters)
    elapsed = perf_counter() - started
    return {
        "tipo_instancia": "sintética dirigida; no representa rutas de España",
        "seed": result.seed,
        "parameters": parameters,
        "hour_value_eur_per_hour": problem.hour_value_eur_per_hour,
        "budget_requested": int(config["presupuesto"]),
        "objective_evaluations": result.objective_evaluations,
        "stop_reason": result.stop_reason,
        "best_route": [problem.cities[index].city_id for index in result.best_route],
        "best_cost_eur": result.best_cost_eur,
        "best_breakdown": {
            "time_hours": result.best_breakdown.total_time_hours,
            "seller_time_cost_eur": result.best_breakdown.seller_time_cost_eur,
            "tolls_eur": result.best_breakdown.toll_cost_eur,
            "fuel_eur": result.best_breakdown.fuel_cost_eur,
        },
        "convergence": [
            {"evaluations": point.evaluations, "best_cost_eur": point.best_cost_eur}
            for point in result.history
        ],
        "runtime_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/tsp_aco_demo.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--output", help="opcional: guardar JSON en una ruta local")
    args = parser.parse_args()
    payload = run_demo(load_config(args.config, args.overrides))
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
