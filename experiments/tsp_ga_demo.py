"""Demostración offline del GA sobre la instancia económica nacional de 47 capitales.

Uso (desde la raíz del repositorio):
    python -m experiments.tsp_ga_demo --config configs/tsp_ga_demo.yaml
    python -m experiments.tsp_ga_demo --set valor_hora_eur_h=50 --set ga.crossover=pmx --set presupuesto=5000
    python -m experiments.tsp_ga_demo --set incluir_peajes=false      # baseline sin peajes

Con valor_hora_eur_h = 10, 25 o 50 el costo coincide con model_a_v{10,25,50}_eur.csv (el cargador lo
verifica). Los peajes del paquete son experimentales: el programa imprime el alcance del costo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from src.config import load_config
from src.tsp import GeneticAlgorithm
from src.tsp.economic_dataset import load_economic_problem


def run_demo(config: dict) -> dict:
    problem = load_economic_problem(config["dataset"], float(config["valor_hora_eur_h"]),
                                    include_tolls=bool(config.get("incluir_peajes", True)))
    params = dict(config["ga"])
    started = perf_counter()
    result = GeneticAlgorithm().run(problem, int(config["semilla"]), int(config["presupuesto"]), **params)
    elapsed = perf_counter() - started
    b = result.best_breakdown
    return {
        "alcance_del_costo": problem.scope,
        "seed": result.seed,
        "parameters": params,
        "hour_value_eur_per_hour": problem.hour_value_eur_per_hour,
        "budget_requested": int(config["presupuesto"]),
        "objective_evaluations": result.objective_evaluations,
        "stop_reason": result.stop_reason,
        "best_route": [problem.cities[i].name for i in result.best_route],
        "best_cost_eur": result.best_cost_eur,
        "best_breakdown": {"distance_km": b.total_distance_km, "time_hours": b.total_time_hours,
                           "seller_time_cost_eur": b.seller_time_cost_eur, "tolls_eur": b.toll_cost_eur,
                           "fuel_eur": b.fuel_cost_eur},
        "convergence": [{"evaluations": p.evaluations, "best_cost_eur": p.best_cost_eur} for p in result.history],
        "runtime_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/tsp_ga_demo.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--output", help="opcional: guardar JSON completo (con convergencia) en una ruta local")
    args = parser.parse_args()
    payload = run_demo(load_config(args.config, args.overrides))
    print("ALCANCE:", payload["alcance_del_costo"])
    print(json.dumps({k: v for k, v in payload.items() if k != "convergence"}, ensure_ascii=False, indent=2))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
