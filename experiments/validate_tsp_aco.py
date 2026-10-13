"""Comparación pequeña offline de líneas base, Ant System y óptimo exhaustivo."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter

import numpy as np

from src.config import load_config
from src.tsp import (
    AntSystem,
    City,
    NearestNeighbor,
    NearestNeighborTwoOpt,
    TSPProblem,
    solve_exact_small,
)


SYNTHETIC_DIRECTED_COSTS = np.asarray([
    [0, 4, 20, 17, 11],
    [5, 0, 4, 18, 14],
    [16, 7, 0, 4, 21],
    [20, 15, 8, 0, 4],
    [4, 20, 17, 9, 0],
], dtype=float)


def synthetic_problem() -> TSPProblem:
    """Instancia dirigida pequeña para validar metodología, no España."""
    size = len(SYNTHETIC_DIRECTED_COSTS)
    cities = tuple(
        City(f"demo-{index}", f"Ciudad demo {index}", f"Provincia demo {index}",
             0.0, 0.0, "synthetic://baseline-demo", "2026-10-12", "verificada",
             "matriz sintética dirigida de comparación")
        for index in range(size)
    )
    zeros = np.zeros_like(SYNTHETIC_DIRECTED_COSTS)
    return TSPProblem(cities, zeros, zeros, SYNTHETIC_DIRECTED_COSTS, zeros, 0.0)


def _run_row(method: str, seed: int, result, elapsed: float, optimum: float) -> dict:
    gap = max(result.best_cost_eur - optimum, 0.0)
    return {
        "metodo": method,
        "semilla": seed,
        "recorrido": "->".join(str(index) for index in result.best_route),
        "costo_eur": result.best_cost_eur,
        "optimo_eur": optimum,
        "brecha_eur": gap,
        "brecha_pct": 100.0 * gap / optimum if optimum > 0 else 0.0,
        "evaluaciones": result.objective_evaluations,
        "tiempo_segundos": elapsed,
        "motivo_parada": result.stop_reason,
        "convergencia_json": json.dumps([
            {"evaluaciones": point.evaluations, "mejor_costo_eur": point.best_cost_eur}
            for point in result.history
        ], ensure_ascii=False),
    }


def run_comparison(config: dict, output_dir: str | Path = "results/tsp_baselines_demo") -> tuple[list[dict], str]:
    problem = synthetic_problem()
    exact_started = perf_counter()
    exact = solve_exact_small(problem)
    exact_seconds = perf_counter() - exact_started
    budget = int(config["presupuesto"])
    policy = str(config["dos_opt_policy"])
    aco_params = dict(config["aco"])
    rows = []

    for seed_value in config["semillas"]:
        seed = int(seed_value)
        methods = (
            ("Nearest Neighbor", NearestNeighbor(), {}),
            ("Nearest Neighbor + 2-opt", NearestNeighborTwoOpt(), {"policy": policy}),
            ("Ant System", AntSystem(), aco_params),
        )
        for name, algorithm, parameters in methods:
            started = perf_counter()
            result = algorithm.run(problem, seed=seed, budget=budget, **parameters)
            elapsed = perf_counter() - started
            rows.append(_run_row(name, seed, result, elapsed, exact.best_cost_eur))

    lines = [
        "# Comparación reducida de ACO y líneas base",
        "",
        "Fixture sintético dirigido de cinco ciudades; no representa España.",
        f"Óptimo exhaustivo: **{exact.best_cost_eur:.6f} €**, "
        f"{len(exact.optimal_routes)} ruta(s) óptima(s), "
        f"{exact.objective_evaluations} evaluaciones exactas, {exact_seconds:.6f} s.",
        f"Presupuesto por corrida heurística: {budget} evaluaciones completas; semillas: "
        f"{', '.join(str(value) for value in config['semillas'])}.",
        "",
        "| Método | Costo medio ± desv. (EUR) | Brecha media (%) | Evaluaciones medias | Tiempo medio (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in ("Nearest Neighbor", "Nearest Neighbor + 2-opt", "Ant System"):
        subset = [row for row in rows if row["metodo"] == method]
        costs = [row["costo_eur"] for row in subset]
        gaps = [row["brecha_pct"] for row in subset]
        evaluations = [row["evaluaciones"] for row in subset]
        runtimes = [row["tiempo_segundos"] for row in subset]
        cost_spread = stdev(costs) if len(costs) > 1 else 0.0
        lines.append(
            f"| {method} | {mean(costs):.6f} ± {cost_spread:.6f} | {mean(gaps):.4f} | "
            f"{mean(evaluations):.2f} | {mean(runtimes):.6f} |"
        )
    lines.extend([
        "",
        "Las evaluaciones cuentan únicamente llamadas a `evaluate_route` sobre ciclos completos.",
        "Las inspecciones locales de arcos del vecino más cercano no consumen ese presupuesto.",
        "2-opt cuenta cada vecino cuya ruta completa evalúa; se detiene al agotar el presupuesto "
        "o alcanzar un óptimo local. Las diferencias de CPU por operador se reflejan en tiempo, "
        "por lo que igual presupuesto no significa igual costo computacional.",
        "",
        "Las curvas de convergencia por corrida, recorridos, brechas, evaluaciones y tiempos "
        "quedan en `runs.csv`. Ant System es estocástico; esta muestra de tres semillas es solo "
        "una validación pequeña y no estima de forma definitiva su rendimiento.",
    ])
    summary = "\n".join(lines) + "\n"

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "runs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (destination / "summary.md").write_text(summary, encoding="utf-8")
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/tsp_baselines_demo.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--output-dir", default="results/tsp_baselines_demo")
    args = parser.parse_args()
    _, summary = run_comparison(load_config(args.config, args.overrides), args.output_dir)
    print(summary)
    print(f"Archivos regenerables guardados en: {Path(args.output_dir)}")


if __name__ == "__main__":
    main()
