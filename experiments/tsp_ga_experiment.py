"""Experimento del GA sobre la instancia económica nacional: estadísticas, valor de la hora y figuras.

Uso (desde la raíz del repositorio):
    python -m experiments.tsp_ga_experiment --config configs/tsp_ga.yaml            # completo
    python -m experiments.tsp_ga_experiment --config configs/tsp_ga_demo_exp.yaml   # demo (< 2 min)
    python -m experiments.tsp_ga_experiment --set n_runs=10 --set ga.crossover=pmx --set valores_hora=[10,25]

Para cada valor de la hora v se corren `n_runs` semillas independientes del GA y se reportan media,
desviación, mediana, mejor y peor costo. Además:
  * rutas.json / mejores rutas: la mejor ruta hallada por v (es la mejor HALLADA, no un óptimo demostrado).
  * cruzado.csv: costo de la mejor ruta de cada v evaluada bajo cada otro v, y el arrepentimiento
    (cuánto más cuesta usar la ruta de v_i cuando el valor real de la hora es v_j, respecto de la mejor
    ruta conocida para v_j). Solo es interpretable si el GA convergió: con presupuestos pequeños las
    rutas difieren por ruido de la búsqueda y no por el valor de la hora.
  * arcos_compartidos.csv: fracción de arcos dirigidos que comparten las mejores rutas de dos v.

Salidas: `salidas.resultados` (CSV/JSON) y `salidas.figuras` (PNG).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from src.config import load_config
from src.tsp import GeneticAlgorithm, NearestNeighbor, NearestNeighborTwoOpt, TwoOpt
from src.tsp.economic_dataset import load_economic_problem

REFERENCIAS = {"nn": NearestNeighbor, "nn_2opt": NearestNeighborTwoOpt, "two_opt": TwoOpt}


def _arcs(route: tuple[int, ...]) -> set[tuple[int, int]]:
    closed = tuple(route) + (route[0],)
    return set(zip(closed[:-1], closed[1:]))


def run_experiment(cfg: dict, results_dir: Path, figures_dir: Path | None = None) -> pd.DataFrame:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(int(cfg.get("semilla_base", 0)), int(cfg.get("semilla_base", 0)) + int(cfg["n_runs"])))
    budget, params = int(cfg["presupuesto"]), dict(cfg["ga"])
    tolls = bool(cfg.get("incluir_peajes", True))
    valores = [float(v) for v in cfg["valores_hora"]]
    desconocidas = set(cfg.get("referencias", [])) - set(REFERENCIAS)
    if desconocidas:
        raise ValueError(f"referencias desconocidas: {sorted(desconocidas)}; use {sorted(REFERENCIAS)}")

    rows, histories, best_routes, best_cost = [], {}, {}, {}
    problems = {v: load_economic_problem(cfg["dataset"], v, include_tolls=tolls) for v in valores}
    scope = problems[valores[0]].scope
    for v, problem in problems.items():
        for seed in seeds:
            started = perf_counter()
            r = GeneticAlgorithm().run(problem, seed, budget, **params)
            b = r.best_breakdown
            rows.append(dict(metodo="GA", valor_hora=v, seed=seed, costo_eur=r.best_cost_eur,
                             evaluaciones=r.objective_evaluations, distancia_km=b.total_distance_km,
                             tiempo_h=b.total_time_hours, costo_tiempo_eur=b.seller_time_cost_eur,
                             peajes_eur=b.toll_cost_eur, combustible_eur=b.fuel_cost_eur,
                             segundos=perf_counter() - started, ruta=">".join(problem.cities[i].city_id for i in r.best_route)))
            histories.setdefault(v, []).append(r.history)
            if r.best_cost_eur < best_cost.get(v, np.inf):
                best_cost[v], best_routes[v] = r.best_cost_eur, r.best_route
        for name in cfg.get("referencias", []):  # una corrida: son deterministas o casi
            r = REFERENCIAS[name]().run(problem, seeds[0], budget)
            b = r.best_breakdown
            rows.append(dict(metodo=name, valor_hora=v, seed=seeds[0], costo_eur=r.best_cost_eur,
                             evaluaciones=r.objective_evaluations, distancia_km=b.total_distance_km,
                             tiempo_h=b.total_time_hours, costo_tiempo_eur=b.seller_time_cost_eur,
                             peajes_eur=b.toll_cost_eur, combustible_eur=b.fuel_cost_eur, segundos=np.nan,
                             ruta=">".join(problem.cities[i].city_id for i in r.best_route)))

    runs = pd.DataFrame(rows)
    runs.to_csv(results_dir / "corridas.csv", index=False)
    summary = (runs.groupby(["valor_hora", "metodo"], sort=False)["costo_eur"]
               .agg(n="count", media="mean", desviacion="std", mediana="median", mejor="min", peor="max")
               .reset_index())
    summary.to_csv(results_dir / "resumen.csv", index=False)

    # Ruta cruzada y arcos compartidos entre las mejores rutas por valor de la hora
    cross, shared = [], []
    for vi in valores:
        for vj in valores:
            cost_ij = problems[vj].evaluate_route(best_routes[vi]).total_cost_eur
            # Referencia: la mejor ruta CONOCIDA para v_j entre las halladas para todos los v (nunca negativo)
            known = min(problems[vj].evaluate_route(best_routes[vk]).total_cost_eur for vk in valores)
            cross.append(dict(ruta_de_v=vi, evaluada_con_v=vj, costo_eur=cost_ij,
                              arrepentimiento_eur=cost_ij - known, arrepentimiento_pct=100 * (cost_ij - known) / known))
            shared.append(dict(v_a=vi, v_b=vj,
                               fraccion_arcos_compartidos=len(_arcs(best_routes[vi]) & _arcs(best_routes[vj])) / len(best_routes[vi])))
    pd.DataFrame(cross).to_csv(results_dir / "cruzado.csv", index=False)
    pd.DataFrame(shared).to_csv(results_dir / "arcos_compartidos.csv", index=False)
    names = {i: c.name for i, c in enumerate(problems[valores[0]].cities)}
    (results_dir / "mejores_rutas.json").write_text(json.dumps(
        {str(v): {"costo_eur": best_cost[v], "ruta": [names[i] for i in best_routes[v]]} for v in valores},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (results_dir / "alcance.txt").write_text(scope + "\n", encoding="utf-8")

    if figures_dir is not None:
        _figures(cfg, problems, histories, best_routes, best_cost, Path(figures_dir))
    return summary


def _figures(cfg, problems, histories, best_routes, best_cost, figures_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    valores = list(problems)
    budget = int(cfg["presupuesto"])
    grid = np.unique(np.geomspace(1, budget, 200).astype(int))

    fig, axes = plt.subplots(1, len(valores), figsize=(3.6 * len(valores), 3.4), squeeze=False)
    for ax, v in zip(axes[0], valores):
        curves = np.array([[next((p.best_cost_eur for p in reversed(h) if p.evaluations <= g), np.nan) for g in grid]
                           for h in histories[v]])
        q1, med, q3 = np.nanpercentile(curves, [25, 50, 75], axis=0)
        ax.plot(grid, med); ax.fill_between(grid, q1, q3, alpha=0.2); ax.set_xscale("log")
        ax.set_title(f"v = {v:g} EUR/h", fontsize=10); ax.set_xlabel("evaluaciones"); ax.set_ylabel("mejor costo (EUR)")
    fig.suptitle(f"GA: convergencia (mediana y cuartiles, {cfg['n_runs']} corridas)")
    fig.tight_layout(); fig.savefig(figures_dir / "convergencia.png", dpi=130); plt.close(fig)

    fig, axes = plt.subplots(1, len(valores), figsize=(3.6 * len(valores), 4.2), squeeze=False)
    for ax, v in zip(axes[0], valores):
        cities = problems[v].cities
        lon = np.array([c.longitude for c in cities]); lat = np.array([c.latitude for c in cities])
        closed = list(best_routes[v]) + [best_routes[v][0]]
        ax.plot(lon[closed], lat[closed], "-", lw=0.9, color="tab:blue"); ax.plot(lon, lat, "o", ms=3, color="tab:red")
        ax.set_title(f"v = {v:g} EUR/h\n{best_cost[v]:,.0f} EUR", fontsize=10); ax.set_aspect(1.25); ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle("Mejor ruta hallada por el GA (coordenadas IGN; sin mapa base)")
    fig.tight_layout(); fig.savefig(figures_dir / "mejores_rutas.png", dpi=130); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/tsp_ga_demo_exp.yaml")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR")
    ap.add_argument("--results"); ap.add_argument("--figures"); ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.set)
    salidas = cfg.get("salidas", {})
    results, figures = a.results or salidas.get("resultados", "results/tsp_ga"), a.figures or salidas.get("figuras", "figures/tsp_ga")
    summary = run_experiment(cfg, Path(results), None if a.no_figures else Path(figures))
    pd.set_option("display.width", 200)
    print("ALCANCE:", (Path(results) / "alcance.txt").read_text(encoding="utf-8").strip())
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nResultados en {results}/" + ("" if a.no_figures else f" y figuras en {figures}/"))


if __name__ == "__main__":
    main()
