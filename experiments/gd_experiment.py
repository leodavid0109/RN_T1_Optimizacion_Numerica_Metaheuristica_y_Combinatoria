"""Experimento de la Parte 1 para el descenso por gradiente.

Uso (desde la raíz del repositorio):
    python -m experiments.gd_experiment --config configs/gd_demo.yaml
    python -m experiments.gd_experiment --config configs/gd.yaml

Salidas:
    results/gd/runs.csv       una fila por (función, dimensión, tasa, semilla)
    results/gd/summary.csv    estadísticas por (función, dimensión, tasa)
    figures/gd/*.png, *.gif   convergencia, cajas, curvas de nivel y GIF (2D)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.counter import CountedProblem
from src.functions import make
from src.gradient_descent import gradient_descent, initial_point
from src.seeds import SEEDS

FLOOR = 1e-16  # para poder dibujar f - f_opt = 0 en escala logarítmica


def _grid(budget: float, n: int) -> np.ndarray:
    return np.unique(np.geomspace(1, budget, n))


def _on_grid(history_evals, history_f, grid):
    """Mejor f alcanzado con a lo sumo `g` evaluaciones (función escalón)."""
    idx = np.searchsorted(history_evals, grid, side="right") - 1
    hf = np.asarray(history_f)
    out = np.where(idx >= 0, hf[np.clip(idx, 0, None)], np.nan)
    return out


def run_experiment(cfg: dict, results_dir: Path, figures_dir: Path | None = None) -> pd.DataFrame:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    seeds = SEEDS[: int(cfg["n_runs"])]
    gc = float(cfg.get("grad_cost", 1.0))
    umbrales = list(cfg["umbrales_exito"])
    rows, curves = [], {}

    for name in cfg["funciones"]:
        for n in cfg["dimensiones"]:
            budget = float(cfg["presupuesto"][n])
            grid = _grid(budget, int(cfg.get("puntos_curva", 200)))
            for lr in cfg["tasas_aprendizaje"][name]:
                mat = []
                for seed in seeds:
                    p = CountedProblem(make(name, n))
                    r = gradient_descent(
                        p, initial_point(p, seed), lr=float(lr), max_iters=10**9,
                        budget=budget, grad_cost=gc, grad_tol=1e-12,
                    )
                    gap = max(r.best_f - p.f_opt, 0.0)
                    row = dict(funcion=name, dim=n, lr=lr, seed=seed, best_f=r.best_f, gap=gap,
                               f_evals=r.f_evals, grad_evals=r.grad_evals,
                               equiv_evals=p.equivalent_evals(gc), stop=r.stop_reason)
                    for u in umbrales:
                        row[f"exito_{u:g}"] = bool(gap < u)
                    rows.append(row)
                    mat.append(_on_grid(r.history_evals, [max(f - p.f_opt, 0.0) for f in r.history_f], grid))
                curves[(name, n, lr)] = (grid, np.array(mat))

    runs = pd.DataFrame(rows)
    runs.to_csv(results_dir / "runs.csv", index=False)

    ex_cols = [f"exito_{u:g}" for u in umbrales]
    agg = {"best_f": ["mean", "std", "min", "max", "median"], "equiv_evals": "mean"}
    agg.update({c: "mean" for c in ex_cols})
    summ = runs.groupby(["funcion", "dim", "lr"]).agg(agg)
    summ.columns = ["_".join(c) if c[1] else c[0] for c in summ.columns]
    summ = summ.rename(columns={
        "best_f_mean": "media", "best_f_std": "desv", "best_f_min": "mejor", "best_f_max": "peor",
        "best_f_median": "mediana", "equiv_evals_mean": "evals_equiv_medias",
        **{f"{c}_mean": f"tasa_{c}" for c in ex_cols}}).reset_index()
    # tasa seleccionada por (función, dimensión): menor mediana de f final (4 cifras significativas);
    # en empate, la que gasta menos evaluaciones y, si persiste, la menor tasa
    summ["seleccionada"] = False
    summ["_clave"] = summ["mediana"].map(lambda v: float(f"{v:.4g}"))
    for (f_, d_), g in summ.groupby(["funcion", "dim"]):
        i = g.sort_values(["_clave", "evals_equiv_medias", "lr"]).index[0]
        summ.loc[i, "seleccionada"] = True
    summ = summ.drop(columns="_clave")
    summ.to_csv(results_dir / "summary.csv", index=False)

    if figures_dir is not None:
        make_figures(cfg, runs, summ, curves, Path(figures_dir))
    return summ


def make_figures(cfg, runs, summ, curves, figures_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    cases = [(f, d) for f in cfg["funciones"] for d in cfg["dimensiones"]]
    sel = {(r.funcion, r.dim): r.lr for r in summ[summ.seleccionada].itertuples()}

    # 1) Convergencia: mediana de f - f* frente a evaluaciones, una curva por tasa
    fig, axes = plt.subplots(len(cfg["funciones"]), len(cfg["dimensiones"]),
                             figsize=(6 * len(cfg["dimensiones"]), 4 * len(cfg["funciones"])), squeeze=False)
    for (name, n) in cases:
        ax = axes[cfg["funciones"].index(name)][cfg["dimensiones"].index(n)]
        for lr in cfg["tasas_aprendizaje"][name]:
            grid, mat = curves[(name, n, lr)]
            med = np.nanmedian(mat, axis=0)
            lw = 2.4 if lr == sel[(name, n)] else 1.2
            ax.plot(grid, np.maximum(med, FLOOR), lw=lw, label=f"lr={lr:g}" + (" (elegida)" if lr == sel[(name, n)] else ""))
            if lr == sel[(name, n)]:
                ax.fill_between(grid, np.maximum(np.nanpercentile(mat, 25, axis=0), FLOOR),
                                np.maximum(np.nanpercentile(mat, 75, axis=0), FLOOR), alpha=0.2)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_title(f"{name} {n}D"); ax.set_xlabel("evaluaciones equivalentes"); ax.set_ylabel("f - f*")
        ax.legend(fontsize=8)
    fig.suptitle(f"Descenso por gradiente: mediana de {cfg['n_runs']} corridas (banda: cuartiles de la tasa elegida)")
    fig.tight_layout(); fig.savefig(figures_dir / "gd_convergencia.png", dpi=140); plt.close(fig)

    # 2) Cajas del valor final por tasa
    fig, axes = plt.subplots(len(cfg["funciones"]), len(cfg["dimensiones"]),
                             figsize=(6 * len(cfg["dimensiones"]), 4 * len(cfg["funciones"])), squeeze=False)
    for (name, n) in cases:
        ax = axes[cfg["funciones"].index(name)][cfg["dimensiones"].index(n)]
        lrs = cfg["tasas_aprendizaje"][name]
        data = [np.maximum(runs[(runs.funcion == name) & (runs.dim == n) & (runs.lr == lr)].gap.values, FLOOR) for lr in lrs]
        ax.boxplot(data, tick_labels=[f"{lr:g}" for lr in lrs]); ax.set_yscale("log")
        ax.set_title(f"{name} {n}D"); ax.set_xlabel("tasa de aprendizaje"); ax.set_ylabel("f final - f*")
    fig.suptitle("Descenso por gradiente: valor final por tasa de aprendizaje")
    fig.tight_layout(); fig.savefig(figures_dir / "gd_cajas.png", dpi=140); plt.close(fig)

    # 3) Curvas de nivel + trayectorias (2D) y GIF
    import imageio.v2 as imageio
    for name in cfg["funciones"]:
        if 2 not in cfg["dimensiones"]:
            continue
        fn = make(name, 2); lr = float(sel[(name, 2)]); budget = float(cfg["presupuesto"][2])
        lo, hi = fn.bounds
        xs = np.linspace(lo[0], hi[0], 300); ys = np.linspace(lo[1], hi[1], 300)
        X, Y = np.meshgrid(xs, ys)
        Z = fn.f(np.stack([X, Y], axis=-1))
        levels = np.geomspace(max(Z.min() + 1e-2, 1e-2), Z.max(), 25)

        def base(ax):
            ax.contour(X, Y, Z, levels=levels, cmap="viridis", linewidths=0.6)
            ax.plot(*fn.x_opt, "r*", ms=12, label="mínimo global")
            ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_xlabel("x1"); ax.set_ylabel("x2")

        trajs = {}
        for s in SEEDS[:3]:
            p = CountedProblem(make(name, 2))
            trajs[s] = gradient_descent(p, initial_point(p, s), lr=lr, max_iters=10**9, budget=budget,
                                        grad_cost=float(cfg.get("grad_cost", 1.0)), grad_tol=1e-12)
        fig, ax = plt.subplots(figsize=(6, 5)); base(ax)
        for s, r in trajs.items():
            xy = np.array(r.history_x); ax.plot(xy[:, 0], xy[:, 1], lw=1, label=f"semilla {s}"); ax.plot(*xy[0], "ko", ms=4)
        ax.set_title(f"{name} 2D: trayectorias del descenso (lr={lr:g})"); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(figures_dir / f"gd_{name}_niveles.png", dpi=140); plt.close(fig)

        r = trajs.get(int(cfg.get("gif_semilla", 0)), next(iter(trajs.values())))
        xy = np.array(r.history_x)
        frames_idx = np.unique(np.geomspace(1, len(xy), 60).astype(int)) - 1
        frames = []
        for k in frames_idx:
            fig, ax = plt.subplots(figsize=(5, 4.2)); base(ax)
            ax.plot(xy[: k + 1, 0], xy[: k + 1, 1], "-", color="tab:orange", lw=1)
            ax.plot(*xy[k], "o", color="tab:red", ms=6)
            ax.set_title(f"{name} 2D · iteración {k}")
            fig.tight_layout(); fig.canvas.draw()
            frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()); plt.close(fig)
        imageio.mimsave(figures_dir / f"gd_{name}.gif", frames, duration=0.12, loop=0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/gd_demo.yaml")
    ap.add_argument("--results", default="results/gd")
    ap.add_argument("--figures", default="figures/gd")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    summ = run_experiment(cfg, Path(a.results), None if a.no_figures else Path(a.figures))
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(summ.to_string(index=False, float_format=lambda v: f"{v:.3g}"))
    print(f"\nResultados en {a.results}/ y figuras en {a.figures}/")


if __name__ == "__main__":
    main()
