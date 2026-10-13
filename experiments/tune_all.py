"""Barrido y validación unificados de hiperparámetros para GD, EA, PSO y DE.

Modo de prueba rápida:
    python -m experiments.tune_all --sweep-seeds 1 --validation-seeds 2

Genera results/tuning/{sweep_runs,sweep_summary,validation_runs,validation_summary}.csv
"""
from __future__ import annotations
import argparse
import itertools
import json
from pathlib import Path
import pandas as pd
from src.counter import CountedProblem
from src.functions import make
from src.methods import METHODS


def build_grids():
    grids = {}
    if "gd" in METHODS:
        grids["gd"] = [
            {"lr": lr, "numeric": numeric}
            for lr, numeric in itertools.product(
                [1e-4, 5e-4, 1e-3, 3e-3], [False, True]
            )
        ]
    if "ea" in METHODS:
        grids["ea"] = [
            {"population_size": pop, "crossover_rate": cr,
             "mutation_scale": mut, "tournament_size": 3}
            for pop, cr, mut in itertools.product(
                [20, 30, 50], [0.7, 0.9], [0.05, 0.1]
            )
        ]
    if "pso" in METHODS:
        grids["pso"] = [
            {"n_particles": particles, "c1": c1, "c2": c2, "w": inertia}
            for particles, (c1, c2), inertia in itertools.product(
                [30, 50], [(0.5, 0.5), (0.8, 0.4), (0.8, 0.8)], [0.1, 0.7]
            )
        ]
    if "de" in METHODS:
        values = [
            (20, .4, .3), (20, .5, .6), (20, .7, .9),
            (30, .5, .3), (30, .7, .6), (30, .4, .9),
            (50, .7, .3), (50, .4, .6), (50, .5, .9),
        ]
        grids["de"] = [
            {"population_size": pop, "F": scale, "CR": cr}
            for pop, scale, cr in values
        ]
    missing = set(METHODS) - set(grids)
    if missing:
        raise RuntimeError(
            f"Métodos registrados sin cuadrícula: {sorted(missing)}. "
            "Añade sus parámetros a build_grids()."
        )
    return grids


def get_best_f(result):
    if hasattr(result, "best_f"):
        return float(result.best_f)
    if isinstance(result, dict):
        for key in ("best_f", "f_best", "best_value", "fun"):
            if key in result:
                return float(result[key])
    raise ValueError("El resultado no contiene best_f; revisa src/result.py.")


def run_one(method, function, dimension, params, seed, budget, grad_cost):
    problem = CountedProblem(make(function, dimension))
    try:
        result = METHODS[method](
            problem, seed=seed, budget=budget, grad_cost=grad_cost, **params
        )
    except Exception as exc:
        raise RuntimeError(
            f"Falló {method}/{function}/{dimension}D, semilla={seed}, "
            f"parámetros={params}: {type(exc).__name__}: {exc}"
        ) from exc
    best_f = get_best_f(result)
    gap = max(best_f - problem.f_opt, 0.0)
    equiv = float(problem.equivalent_evals(grad_cost))
    return {
        "method": method, "function": function, "dimension": dimension,
        "seed": seed, "params": json.dumps(params, sort_keys=True),
        "best_f": best_f, "gap": gap,
        "f_evals": problem.f_evals, "grad_evals": problem.grad_evals,
        "equiv_evals": equiv, "budget": budget,
        "budget_overshoot": max(0.0, equiv - budget),
        "stop_reason": getattr(result, "stop_reason", "unknown"),
    }


def summarize(runs):
    if runs.empty:
        raise RuntimeError("No se generaron resultados.")
    keys = ["method", "function", "dimension", "params"]
    summary = runs.groupby(keys, as_index=False).agg(
        n_runs=("gap", "count"), gap_mean=("gap", "mean"),
        gap_median=("gap", "median"), gap_std=("gap", "std"),
        gap_min=("gap", "min"), gap_max=("gap", "max"),
        best_f_mean=("best_f", "mean"), f_evals_mean=("f_evals", "mean"),
        grad_evals_mean=("grad_evals", "mean"),
        equiv_evals_mean=("equiv_evals", "mean"),
        budget_overshoot_max=("budget_overshoot", "max"),
    )
    for threshold, label in [(1e-4, "1e4"), (1e-2, "1e2")]:
        rates = (runs.assign(success=runs.gap <= threshold)
                 .groupby(keys)["success"].mean()
                 .rename(f"success_rate_{label}").reset_index())
        summary = summary.merge(rates, on=keys, how="left")
        summary[f"success_rate_{label}_pct"] = 100 * summary[f"success_rate_{label}"]
    return summary.sort_values(["function", "dimension", "gap_mean", "method"])


def main():
    parser = argparse.ArgumentParser(description="Barrido + validación de hiperparámetros.")
    parser.add_argument("--functions", nargs="+", default=["rosenbrock", "rastrigin"])
    parser.add_argument("--dimensions", nargs="+", type=int, default=[2, 3])
    parser.add_argument("--budget-2d", type=int, default=2000)
    parser.add_argument("--budget-3d", type=int, default=3000)
    parser.add_argument("--sweep-seeds", type=int, default=3)
    parser.add_argument("--validation-seeds", type=int, default=10)
    parser.add_argument("--grad-cost", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("results/tuning"))
    args = parser.parse_args()
    if args.sweep_seeds < 1 or args.validation_seeds < 1:
        parser.error("El número de semillas debe ser al menos 1.")
    if any(n not in (2, 3) for n in args.dimensions):
        parser.error("Este programa define presupuestos para dimensiones 2 y 3.")
    if args.budget_2d <= 0 or args.budget_3d <= 0:
        parser.error("Los presupuestos deben ser positivos.")
    unknown = set(args.functions) - {"rosenbrock", "rastrigin"}
    if unknown:
        parser.error(f"Funciones desconocidas: {sorted(unknown)}")

    grids = build_grids()
    print("Cuadrículas:", ", ".join(f"{k}={len(v)}" for k, v in grids.items()))
    budgets = {2: args.budget_2d, 3: args.budget_3d}
    sweep_seeds = range(args.sweep_seeds)
    validation_seeds = range(1000, 1000 + args.validation_seeds)
    args.output.mkdir(parents=True, exist_ok=True)

    # Fase 1: barrido. Cada configuración usa las mismas semillas de prueba.
    rows = []
    total = sum(len(g) for g in grids.values()) * len(args.functions) * len(args.dimensions) * len(sweep_seeds)
    done = 0
    print(f"\nFASE 1 — {total} ejecuciones del barrido")
    for method, configs in grids.items():
        for function, dimension, params, seed in itertools.product(
            args.functions, args.dimensions, configs, sweep_seeds
        ):
            rows.append(run_one(method, function, dimension, params, seed,
                                budgets[dimension], args.grad_cost))
            done += 1
            if done % 50 == 0 or done == total:
                print(f"Barrido: {done}/{total}")
    sweep_runs = pd.DataFrame(rows)
    sweep_summary = summarize(sweep_runs)
    sweep_runs.to_csv(args.output / "sweep_runs.csv", index=False)
    sweep_summary.to_csv(args.output / "sweep_summary.csv", index=False)

    # Fase 2: elige por menor gap promedio y valida con semillas no usadas antes.
    best = (sweep_summary.sort_values("gap_mean")
            .groupby(["method", "function", "dimension"], as_index=False).first())
    rows = []
    total = len(best) * args.validation_seeds
    done = 0
    print(f"\nFASE 2 — validación de {len(best)} configuraciones con {args.validation_seeds} semillas nuevas")
    for _, cfg in best.iterrows():
        method, function, dimension = str(cfg.method), str(cfg.function), int(cfg.dimension)
        params = json.loads(str(cfg.params))
        for seed in validation_seeds:
            row = run_one(method, function, dimension, params, seed,
                          budgets[dimension], args.grad_cost)
            row["sweep_gap_mean"] = float(cfg.gap_mean)
            rows.append(row)
            done += 1
            if done % 25 == 0 or done == total:
                print(f"Validación: {done}/{total}")
    validation_runs = pd.DataFrame(rows)
    validation_summary = summarize(validation_runs)
    validation_runs.to_csv(args.output / "validation_runs.csv", index=False)
    validation_summary.to_csv(args.output / "validation_summary.csv", index=False)

    cols = ["method", "function", "dimension", "n_runs", "gap_mean", "gap_std",
            "success_rate_1e4_pct", "success_rate_1e2_pct", "equiv_evals_mean",
            "budget_overshoot_max"]
    print("\nRESUMEN DE VALIDACIÓN")
    print(validation_summary[cols].to_string(index=False, float_format=lambda x: f"{x:.6g}"))
    print(f"\nArchivos guardados en: {args.output.resolve()}")
    print("Revisa budget_overshoot_max: GD puede exceder ligeramente el presupuesto con la implementación actual.")

if __name__ == "__main__":
    main()
