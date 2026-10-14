"""Run ACO and nearest-neighbor baselines on experimental Model A and animate ACO.

Offline only. The animation uses the local published ORS route geometries as a
faint road-network backdrop and the best-so-far tour at each objective evaluation.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import sys
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.animation import FuncAnimation, PillowWriter

import src.tsp.aco as aco_module
import src.tsp.baselines as baselines_module
from experiments.run_tsp_economic_aco import load_model_a_problem
from src.tsp import AntSystem, NearestNeighbor, NearestNeighborTwoOpt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "data/datasets/spain_tsp_economic_20261013"
DEFAULT_DATASET = ROOT / "data/datasets/spain_tsp_2026"
DEFAULT_OUTPUT = ROOT / "data/processed/tsp"


class _RecordingEvaluator(aco_module.RunEvaluator):
    """Capture the exact best-so-far tours without changing AntSystem itself."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.best_route_states: list[dict] = []

    def evaluate(self, route):
        previous = self.best_breakdown.total_cost_eur if self.best_breakdown else None
        breakdown = super().evaluate(route)
        if previous is None or breakdown.total_cost_eur < previous:
            self.best_route_states.append({
                "evaluations": self.objective_evaluations,
                "best_cost_eur": breakdown.total_cost_eur,
                "route": self.best_route,
            })
        return breakdown


def _load_route_geometries(directory: Path) -> dict[tuple[str, str], list[tuple[float, float]]]:
    geometries: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for path in sorted(directory.glob("routes-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                record = json.loads(line)
                key = (record["origin_id"], record["destination_id"])
                if key in geometries:
                    raise ValueError(f"geometría duplicada en {path.name}:{line_number}: {key}")
                coordinates = record.get("geometry", {}).get("coordinates")
                if not isinstance(coordinates, list) or len(coordinates) < 2:
                    raise ValueError(f"geometría inválida en {path.name}:{line_number}: {key}")
                geometries[key] = [(float(point[0]), float(point[1])) for point in coordinates]
    if len(geometries) != 47 * 46:
        raise ValueError(f"se esperaban 2.162 geometrías únicas; se encontraron {len(geometries)}")
    return geometries


def _run_aco(problem, seed: int, budget: int):
    original = aco_module.RunEvaluator
    recorder = None

    class Factory(_RecordingEvaluator):
        def __init__(self, *args, **kwargs):
            nonlocal recorder
            super().__init__(*args, **kwargs)
            recorder = self

    aco_module.RunEvaluator = Factory
    try:
        started = perf_counter()
        result = AntSystem().run(
            problem, seed=seed, budget=budget, n_ants=10,
            alpha=1.0, beta=2.0, rho=0.5, q=1.0, tau0=1.0,
        )
        elapsed = perf_counter() - started
    finally:
        aco_module.RunEvaluator = original
    if recorder is None:
        raise RuntimeError("no se capturó el evaluador ACO")
    return result, recorder.best_route_states, elapsed


def _run_baseline(algorithm, problem, seed: int, budget: int, *, two_opt: bool = False):
    original = baselines_module.RunEvaluator
    recorder = None

    class Factory(_RecordingEvaluator):
        def __init__(self, *args, **kwargs):
            nonlocal recorder
            super().__init__(*args, **kwargs)
            recorder = self

    baselines_module.RunEvaluator = Factory
    try:
        started = perf_counter()
        if two_opt:
            result = algorithm.run(
                problem, seed=seed, budget=budget,
                start_cities=tuple(range(problem.size)), policy="best_improvement",
            )
        else:
            result = algorithm.run(
                problem, seed=seed, budget=budget,
                start_cities=tuple(range(problem.size)),
            )
        elapsed = perf_counter() - started
    finally:
        baselines_module.RunEvaluator = original
    if recorder is None:
        raise RuntimeError("no se capturó el evaluador de línea base")
    return result, recorder.best_route_states, elapsed


def _validate_result(name: str, result, city_count: int, budget: int) -> None:
    if len(result.best_route) != city_count or set(result.best_route) != set(range(city_count)):
        raise ValueError(f"{name}: recorrido no es una permutación de las ciudades")
    if result.objective_evaluations > budget:
        raise ValueError(f"{name}: excedió el presupuesto de evaluaciones")
    if result.best_breakdown.closed_route != result.best_route + (result.best_route[0],):
        raise ValueError(f"{name}: el recorrido no retorna a su ciudad inicial")


def _describe(name: str, result, cities, elapsed: float) -> dict:
    city_ids = [cities[index].city_id for index in result.best_route]
    city_names = [cities[index].name for index in result.best_route]
    closed_names = city_names + [city_names[0]]
    breakdown = result.best_breakdown
    print(f"\n{name}")
    print(f"  Mejor costo Modelo A experimental: {result.best_cost_eur:,.2f} EUR")
    print(f"  Distancia: {breakdown.total_distance_km:,.1f} km | Tiempo: {breakdown.total_time_hours:,.2f} h")
    print(f"  Combustible: {breakdown.fuel_cost_eur:,.2f} EUR | Peajes supuestos/estimados: {breakdown.toll_cost_eur:,.2f} EUR")
    print(f"  Evaluaciones completas: {result.objective_evaluations} | Tiempo: {elapsed:.3f} s | Parada: {result.stop_reason}")
    print("  Tour cerrado:")
    # ASCII arrow keeps the console report usable in legacy Windows code pages.
    print("   " + " -> ".join(closed_names))
    return {
        "algorithm": name,
        "model": "Modelo A experimental; peajes con supuestos documentados, no matriz tarifaria verificada",
        "hour_value_eur_per_hour": 25,
        "seed": result.seed,
        "objective_evaluations": result.objective_evaluations,
        "stop_reason": result.stop_reason,
        "best_cost_eur": result.best_cost_eur,
        "distance_km": breakdown.total_distance_km,
        "duration_hours": breakdown.total_time_hours,
        "fuel_eur": breakdown.fuel_cost_eur,
        "toll_eur": breakdown.toll_cost_eur,
        "runtime_seconds": elapsed,
        "tour_city_ids_open": city_ids,
        "tour_city_names_closed": closed_names,
        "convergence": [
            {"evaluations": point.evaluations, "best_cost_eur": point.best_cost_eur}
            for point in result.history
        ],
    }


def _normalize_to_anchor(route: tuple[int, ...], anchor: int) -> tuple[int, ...]:
    position = route.index(anchor)
    return route[position:] + route[:position]


def _sample_best_states(states, evaluations: list[int]):
    if not states:
        raise ValueError("un método no registró estados de ruta para animar")
    current_index = 0
    current = states[0]
    sampled = []
    for evaluation in evaluations:
        while current_index + 1 < len(states) and states[current_index + 1]["evaluations"] <= evaluation:
            current_index += 1
            current = states[current_index]
        sampled.append(current)
    return sampled


def _make_animation(cities, geometries, method_states, budget: int, output: Path, anchor_index: int) -> None:
    if any(not states for states in method_states.values()):
        raise ValueError("algún método no registró estados de ruta para animar")
    output.parent.mkdir(parents=True, exist_ok=True)
    city_by_id = {city.city_id: city for city in cities}

    # Thin local ORS route network supplies geographic context without any map API.
    backdrop = []
    for coordinates in geometries.values():
        step = max(1, len(coordinates) // 14)
        sampled = coordinates[::step]
        if sampled[-1] != coordinates[-1]:
            sampled.append(coordinates[-1])
        backdrop.append(sampled)

    figure, axes = plt.subplots(figsize=(8.4, 7.4), dpi=75)
    axes.add_collection(LineCollection(backdrop, colors="#d7dce2", linewidths=0.34, alpha=0.62, zorder=1))
    longitudes = [city.longitude for city in cities]
    latitudes = [city.latitude for city in cities]
    axes.scatter(longitudes, latitudes, s=13, c="#263746", edgecolors="white", linewidths=0.4, zorder=4)
    axes.set_xlim(min(longitudes) - 1.1, max(longitudes) + 1.1)
    axes.set_ylim(min(latitudes) - 0.8, max(latitudes) + 0.8)
    axes.set_aspect(np.cos(np.deg2rad(np.mean(latitudes))))
    axes.set_xlabel("Longitud (°)")
    axes.set_ylabel("Latitud (°)")
    axes.grid(True, linewidth=0.35, color="#e7eaee", zorder=0)
    axes.set_title(
        f"Evolución comparativa de rutas — salida común desde {cities[anchor_index].name}\n"
        "Modelo A experimental, valor del tiempo = 25 EUR/h",
        loc="left", weight="bold",
    )
    axes.text(
        0.01, 0.015,
        "Geometrías ORS en gris · ciclos rotados visualmente al mismo origen · peajes experimentales",
        transform=axes.transAxes, fontsize=7, color="#46515c",
    )
    axes.legend(handles=[
        Line2D([0], [0], color="#d7dce2", lw=1.5, label="Red de rutas ORS adquiridas"),
        Line2D([0], [0], color="#c23b5a", lw=2.2, label="ACO: mejor tour actual"),
        Line2D([0], [0], color="#2878b5", lw=2.0, label="Vecino más cercano: mejor actual"),
        Line2D([0], [0], color="#27966f", lw=2.0, label="Vecino más cercano + 2-opt"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#263746", markeredgecolor="white",
               markersize=6, label="Capital provincial"),
    ], loc="lower right", frameon=False, fontsize=8)

    styles = {
        "ACO": ("#c23b5a", 2.2, 0.9, "solid"),
        "Vecino más cercano": ("#2878b5", 2.0, 0.88, "dashed"),
        "Vecino más cercano + 2-opt": ("#27966f", 1.7, 0.92, "dotted"),
    }
    collections = {}
    for method, (color, width, alpha, linestyle) in styles.items():
        collection = LineCollection([], colors=color, linewidths=width, alpha=alpha,
                                    linestyles=linestyle, zorder=3)
        axes.add_collection(collection)
        collections[method] = collection
    progress = axes.text(0.01, 0.97, "", transform=axes.transAxes, va="top", fontsize=10, weight="bold")
    start_marker = axes.scatter([], [], marker="*", s=90, c="#f2b134", edgecolors="#263746", zorder=5)

    # Sample the common evaluation axis. Each line is the best-so-far route
    # at the corresponding point in that method's own run.
    displayed_evaluations = sorted(set(
        int(round(value)) for value in np.linspace(1, budget, min(32, budget))
    ))
    sampled_states = {
        method: _sample_best_states(states, displayed_evaluations)
        for method, states in method_states.items()
    }

    def draw(frame: int):
        evaluation = displayed_evaluations[frame]
        for method, states in sampled_states.items():
            route = _normalize_to_anchor(tuple(states[frame]["route"]), anchor_index)
            route_ids = [cities[index].city_id for index in route]
            closed_ids = route_ids + [route_ids[0]]
            segments = [geometries[(origin, destination)]
                        for origin, destination in zip(closed_ids[:-1], closed_ids[1:])]
            collections[method].set_segments(segments)
        start = cities[anchor_index]
        start_marker.set_offsets([[start.longitude, start.latitude]])
        progress.set_text(
            f"Evaluación {evaluation}/{budget} | ACO {sampled_states['ACO'][frame]['best_cost_eur']:,.0f} EUR | "
            f"NN {sampled_states['Vecino más cercano'][frame]['best_cost_eur']:,.0f} EUR | "
            f"NN + 2-opt {sampled_states['Vecino más cercano + 2-opt'][frame]['best_cost_eur']:,.0f} EUR"
        )
        return (*collections.values(), start_marker, progress)

    animation = FuncAnimation(figure, draw, frames=len(displayed_evaluations), interval=1000 / 6,
                              blit=False, repeat=False)
    animation.save(output, writer=PillowWriter(fps=6), dpi=75)
    plt.close(figure)


def run(*, hour_value: float = 25.0, seed: int = 20261013, budget: int = 100,
        bundle_dir: Path = DEFAULT_BUNDLE, dataset_dir: Path = DEFAULT_DATASET,
        output_dir: Path = DEFAULT_OUTPUT) -> dict:
    if hour_value != 25.0:
        # Keep this demonstrative output aligned with the recommended central matrix.
        raise ValueError("esta visualización está configurada para la matriz recomendada v=25 EUR/h")
    problem, cities = load_model_a_problem(bundle_dir, dataset_dir, hour_value)
    if len(cities) != 47:
        raise ValueError("se requieren exactamente 47 ciudades")
    geometries = _load_route_geometries(dataset_dir / "routes" / "ors_enriched")
    print("Escenario: Modelo A experimental v=25 EUR/h; no equivale a peajes verificados.")
    print(f"Ciudades: {len(cities)} | Arcos dirigidos/geométricos: {len(geometries)} | Semilla: {seed} | Presupuesto máximo: {budget}")

    aco, states, aco_time = _run_aco(problem, seed, budget)
    nearest, nearest_states, nn_time = _run_baseline(
        NearestNeighbor(), problem, seed, budget,
    )
    nearest_2opt, nearest_2opt_states, nn_2opt_time = _run_baseline(
        NearestNeighborTwoOpt(), problem, seed, budget, two_opt=True,
    )

    results = {"ACO": aco, "Vecino más cercano (47 inicios)": nearest,
               "Vecino más cercano + 2-opt dirigido": nearest_2opt}
    for name, result in results.items():
        _validate_result(name, result, problem.size, budget)
    rows = [
        _describe("Ant System (ACO)", aco, cities, aco_time),
        _describe("Vecino más cercano (47 ciudades iniciales; máximo un tour por inicio)", nearest, cities, nn_time),
        _describe("Vecino más cercano + 2-opt dirigido", nearest_2opt, cities, nn_2opt_time),
    ]
    winner = min(rows, key=lambda row: row["best_cost_eur"])
    print(f"\nMejor costo entre estas ejecuciones: {winner['algorithm']} — {winner['best_cost_eur']:,.2f} EUR")

    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "scenario": "Modelo A experimental (matriz publicada, v=25 EUR/h); no peajes oficialmente completos",
        "seed": seed, "budget_max_per_algorithm": budget,
        "dataset_matrix": str((bundle_dir / "model_a_v25_eur.csv").relative_to(ROOT)),
        "city_order_source": str((dataset_dir / "cities.csv").relative_to(ROOT)),
        "route_geometry_source": str((dataset_dir / "routes/ors_enriched").relative_to(ROOT)),
        "animation_common_start_city": "madrid (rotación visual del tour cerrado; sin cambiar arcos ni costo)",
        "results": rows,
        "warning": "La matriz combina ceros asumidos e importes inferidos/proxy; resultados experimentales, no costos económicos verificados.",
    }
    json_path = output_dir / "model_a_v25_aco_baselines.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history_path = output_dir / "model_a_v25_aco_convergence.csv"
    with history_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("evaluations", "best_cost_eur"))
        writer.writeheader()
        writer.writerows({"evaluations": point.evaluations, "best_cost_eur": point.best_cost_eur}
                         for point in aco.history)
    anchor_index = next(index for index, city in enumerate(cities) if city.city_id == "madrid")
    # Use a shared output file for the three algorithms; the snapshots and
    # metrics all come from these same measured runs.
    gif_path = output_dir / "model_a_v25_aco_nn_2opt_comparison.gif"
    method_states = {
        "ACO": states,
        "Vecino más cercano": nearest_states,
        "Vecino más cercano + 2-opt": nearest_2opt_states,
    }
    _make_animation(cities, geometries, method_states, budget, gif_path, anchor_index)
    print(f"\nArchivos generados:\n  {json_path}\n  {history_path}\n  {gif_path}")
    return summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(seed=args.seed, budget=args.budget, bundle_dir=args.bundle,
        dataset_dir=args.dataset, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
