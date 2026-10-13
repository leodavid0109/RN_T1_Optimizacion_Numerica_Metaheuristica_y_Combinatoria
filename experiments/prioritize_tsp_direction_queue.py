"""Prioriza offline arcos sin geometría usando recorridos auxiliares TSP.

La puntuación organiza trabajo de adquisición; no estima el óptimo económico.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from pathlib import Path

import numpy as np

from experiments.plan_tsp_direction_queue import plan_queue
from src.tsp import AntSystem, City, TSPProblem
from src.tsp.baselines import NearestNeighbor, NearestNeighborTwoOpt
from src.tsp.etl.dataset_export import load_published_dataset


CORRIDOR_HINTS = {
    frozenset(("bizkaia", "la_rioja")): "AP-68; hipótesis por extremos",
    frozenset(("la_rioja", "zaragoza")): "AP-68; hipótesis por extremos",
    frozenset(("madrid", "segovia")): "AP-6/AP-61; hipótesis por extremos",
    frozenset(("madrid", "avila")): "AP-6/AP-51; hipótesis por extremos",
    frozenset(("asturias", "leon")): "AP-66; hipótesis por extremos",
    frozenset(("a_coruna", "pontevedra")): "AP-9; hipótesis por extremos",
}


def rank_missing_arcs(missing: list[dict], tours: list[dict]) -> list[dict]:
    pairs = [(row["origin_id"], row["destination_id"]) for row in missing]
    if len(pairs) != len(set(pairs)) or any(a == b for a, b in pairs):
        raise ValueError("cola de arcos duplicada o con diagonal")
    frequency: Counter[tuple[str, str]] = Counter()
    methods: dict[tuple[str, str], set[str]] = {}
    for run in tours:
        order = tuple(run["city_order"])
        if not order or len(order) != len(set(order)):
            raise ValueError("recorrido candidato vacío o con ciudades duplicadas")
        for origin, destination in zip(order, order[1:] + order[:1]):
            pair = (origin, destination)
            frequency[pair] += 1
            methods.setdefault(pair, set()).add(run["method"])
    ranked = []
    for row in missing:
        pair = row["origin_id"], row["destination_id"]
        hint = CORRIDOR_HINTS.get(frozenset(pair), "")
        count = frequency[pair]
        ranked.append({**row, "candidate_tour_frequency": count,
                       "methods": ";".join(sorted(methods.get(pair, ()))),
                       "possible_toll_corridor_hint": hint,
                       "priority_score": 100 * count + (10 if hint else 0)
                       + min(float(row["duration_hours_matrix"]), 10.0),
                       "available_data": "Matrix distancia/tiempo/combustible; geometría rápida ausente",
                       "missing_data": "geometría Directions, peaje total y evidencia tarifaria"})
    ranked.sort(key=lambda row: (-row["priority_score"], row["origin_id"], row["destination_id"]))
    return ranked


def build_candidate_tours(dataset_dir: Path, *, seed: int = 42) -> list[dict]:
    dataset = load_published_dataset(dataset_dir)
    with (dataset_dir / "cities.csv").open(encoding="utf-8", newline="") as stream:
        cities = tuple(City(**{**row, "latitude": float(row["latitude"]),
                                "longitude": float(row["longitude"])}) for row in csv.DictReader(stream))
    if tuple(city.city_id for city in cities) != dataset["city_order"]:
        raise ValueError("catálogo y matrices no coinciden")
    zeros = np.zeros_like(dataset["distance_km"])
    runs = []
    for hour_value in (10.0, 25.0, 50.0):
        problem = TSPProblem(cities, dataset["distance_km"], dataset["duration_hours"], zeros,
                             dataset["fuel_reference_eur"], hour_value)
        configurations = (
            ("NearestNeighbor", NearestNeighbor(), seed, 47, {}),
            ("NearestNeighborTwoOpt", NearestNeighborTwoOpt(), seed, 200,
             {"policy": "first_improvement"}),
            ("AntSystem", AntSystem(), seed, 80,
             {"n_ants": 10, "alpha": 1.0, "beta": 2.0, "rho": 0.5, "q": 1.0, "tau0": 1.0}),
            ("AntSystem", AntSystem(), seed + 1, 80,
             {"n_ants": 10, "alpha": 1.0, "beta": 2.0, "rho": 0.5, "q": 1.0, "tau0": 1.0}),
        )
        for method, algorithm, run_seed, budget, params in configurations:
            result = algorithm.run(problem, run_seed, budget, **params)
            runs.append({"method": method, "hour_value_eur": hour_value, "seed": run_seed,
                         "budget": budget, "evaluations": result.objective_evaluations,
                         "city_order": [cities[i].city_id for i in result.best_route],
                         "auxiliary_cost_eur": result.best_cost_eur})
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--routes", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/prioritized_queue"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    missing = plan_queue(args.dataset, args.routes)
    tours = build_candidate_tours(args.dataset, seed=args.seed)
    rows = rank_missing_arcs(missing, tours)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "directions_priority.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"scenario": "auxiliar: tiempo y combustible; peajes excluidos",
                "rule": "100*frecuencia + 10*hipótesis_corredor + min(horas_Matrix,10)",
                "universe": 2162, "existing_geometries": 2162 - len(rows),
                "pending": len(rows), "candidate_tours": tours,
                "top20": rows[:20], "http_requests": 0,
                "note": "Prioridad de adquisición, no ruta óptima económica global."}
    (args.output / "priority_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pending": len(rows), "candidate_tours": len(tours),
                      "top20": [{"arc": f"{r['origin_id']}->{r['destination_id']}",
                                 "frequency": r["candidate_tour_frequency"],
                                 "methods": r["methods"], "hint": r["possible_toll_corridor_hint"]}
                                for r in rows[:20]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
