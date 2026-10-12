"""Comparación de los métodos de la Parte 1 con el mismo presupuesto y las mismas semillas.

Cada método se toma de src/methods.py y debe seguir el formato común de src/result.py.
Por ahora solo está el descenso por gradiente; los demás entran al registrarlos allí
y agregarlos en `metodos:` del YAML.

Uso (desde la raíz del repositorio):
    python -m experiments.compare --config configs/compare_demo.yaml
    python -m experiments.compare --config configs/compare.yaml
    python -m experiments.compare --config configs/compare_demo.yaml --set metodos.gd.rosenbrock.lr=0.0004

Salidas (carpetas en `salidas:` del YAML):
    <resultados>/runs.csv     una fila por (método, función, dimensión, semilla)
    <resultados>/summary.csv  estadísticas por (método, función, dimensión)
    <figuras>/compare_convergencia.png, compare_cajas.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.gd_experiment import FLOOR, _grid, _on_grid
from src.config import load_config
from src.counter import CountedProblem
from src.functions import make
from src.methods import METHODS
from src.seeds import SEEDS


def run_comparison(cfg: dict, results_dir: Path, figures_dir: Path | None = None) -> pd.DataFrame:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    seeds = SEEDS[: int(cfg["n_runs"])]
    gc = float(cfg.get("grad_cost", 1.0))
    umbrales = list(cfg["umbrales_exito"])
    desconocidos = set(cfg["metodos"]) - set(METHODS)
    if desconocidos:
        raise ValueError(f"métodos sin registrar en src/methods.py: {sorted(desconocidos)}")
    rows, curves = [], {}

    for metodo, por_funcion in cfg["metodos"].items():
        run = METHODS[metodo]
        for name in cfg["funciones"]:
            hp = dict((por_funcion or {}).get(name) or {})
            for n in cfg["dimensiones"]:
                budget = float(cfg["presupuesto"][n])
                grid = _grid(budget, int(cfg.get("puntos_curva", 200)))
                mat = []
                for seed in seeds:
                    p = CountedProblem(make(name, n))
                    r = run(p, seed, budget, gc, **hp)
                    gap = max(r.best_f - p.f_opt, 0.0)
                    row = dict(metodo=metodo, funcion=name, dim=n, seed=seed, best_f=r.best_f, gap=gap,
                               f_evals=r.f_evals, grad_evals=r.grad_evals,
                               equiv_evals=p.equivalent_evals(gc),
                               equiv_evals_2n=p.equivalent_evals(2 * n), stop=r.stop_reason)
                    for u in umbrales:
                        row[f"exito_{u:g}"] = bool(gap <= u)
                    rows.append(row)
                    mat.append(_on_grid(r.history_evals, [max(f - p.f_opt, 0.0) for f in r.history_f], grid))
                curves[(metodo, name, n)] = (grid, np.array(mat))

    runs = pd.DataFrame(rows)
    runs.to_csv(results_dir / "runs.csv", index=False)

    ex_cols = [f"exito_{u:g}" for u in umbrales]
    agg = {"best_f": ["mean", "std", "min", "max", "median"], "f_evals": "mean", "grad_evals": "mean",
           "equiv_evals": "mean", "equiv_evals_2n": "mean"}
    agg.update({c: "mean" for c in ex_cols})
    summ = runs.groupby(["metodo", "funcion", "dim"], sort=False).agg(agg)
    summ.columns = ["_".join(c) if c[1] else c[0] for c in summ.columns]
    summ = summ.rename(columns={
        "best_f_mean": "media", "best_f_std": "desv", "best_f_min": "mejor", "best_f_max": "peor",
        "best_f_median": "mediana", "f_evals_mean": "evals_f_medias", "grad_evals_mean": "evals_grad_medias",
        "equiv_evals_mean": "evals_equiv_medias", "equiv_evals_2n_mean": "evals_equiv_2n_medias",
        **{f"{c}_mean": f"tasa_{c}" for c in ex_cols}}).reset_index()
    summ.to_csv(results_dir / "summary.csv", index=False)

    if figures_dir is not None:
        make_figures(cfg, runs, curves, Path(figures_dir))
    return summ


def make_figures(cfg, runs, curves, figures_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    funcs, dims, metodos = cfg["funciones"], cfg["dimensiones"], list(cfg["metodos"])
    size = dict(figsize=(6 * len(dims), 4 * len(funcs)), squeeze=False)

    # 1) Convergencia: mediana de f - f* frente a evaluaciones, una curva por método (banda: cuartiles)
    fig, axes = plt.subplots(len(funcs), len(dims), **size)
    for i, name in enumerate(funcs):
        for j, n in enumerate(dims):
            ax = axes[i][j]
            for m in metodos:
                grid, mat = curves[(m, name, n)]
                line, = ax.plot(grid, np.maximum(np.nanmedian(mat, axis=0), FLOOR), lw=1.8, label=m)
                ax.fill_between(grid, np.maximum(np.nanpercentile(mat, 25, axis=0), FLOOR),
                                np.maximum(np.nanpercentile(mat, 75, axis=0), FLOOR),
                                color=line.get_color(), alpha=0.15)
            ax.set_xscale("log"); ax.set_yscale("log")
            ax.set_title(f"{name} {n}D"); ax.set_xlabel("evaluaciones equivalentes"); ax.set_ylabel("f - f*")
            ax.legend(fontsize=8)
    fig.suptitle(f"Comparación de métodos: mediana de {cfg['n_runs']} corridas (banda: cuartiles)")
    fig.tight_layout(); fig.savefig(figures_dir / "compare_convergencia.png", dpi=140); plt.close(fig)

    # 2) Cajas del valor final por método
    fig, axes = plt.subplots(len(funcs), len(dims), **size)
    for i, name in enumerate(funcs):
        for j, n in enumerate(dims):
            ax = axes[i][j]
            data = [np.maximum(runs[(runs.metodo == m) & (runs.funcion == name) & (runs.dim == n)].gap.values, FLOOR)
                    for m in metodos]
            ax.boxplot(data, tick_labels=metodos); ax.set_yscale("log")
            ax.set_title(f"{name} {n}D"); ax.set_xlabel("método"); ax.set_ylabel("f final - f*")
    fig.suptitle("Comparación de métodos: valor final con el mismo presupuesto")
    fig.tight_layout(); fig.savefig(figures_dir / "compare_cajas.png", dpi=140); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/compare_demo.yaml")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR",
                    help="cambia un parámetro del YAML, p. ej. --set n_runs=5 (se puede repetir)")
    ap.add_argument("--results", help="carpeta de resultados (por defecto, salidas.resultados del YAML)")
    ap.add_argument("--figures", help="carpeta de figuras (por defecto, salidas.figuras del YAML)")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.set)
    salidas = cfg.get("salidas", {})
    results = a.results or salidas.get("resultados", "results/compare")
    figures = a.figures or salidas.get("figuras", "figures/compare")
    summ = run_comparison(cfg, Path(results), None if a.no_figures else Path(figures))
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(summ.to_string(index=False, float_format=lambda v: f"{v:.3g}"))
    print(f"\nResultados en {results}/" + ("" if a.no_figures else f" y figuras en {figures}/"))


if __name__ == "__main__":
    main()
