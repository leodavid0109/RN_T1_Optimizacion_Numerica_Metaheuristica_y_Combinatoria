"""GIF animados del proceso de optimización (Parte 1, punto 4): GD, PSO y evolución diferencial.

Uso (desde la raíz del repositorio):
    python -m experiments.animate --config configs/anim.yaml
    python -m experiments.animate --config configs/anim.yaml --set semilla=3 --set metodos.de.rastrigin.F=0.8

Salida (carpeta `salidas.figuras` del YAML), un GIF por método y función en 2D:
    anim_<metodo>_<funcion>.gif   curvas de nivel + población (o trayectoria de GD) + mejor punto
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from src.config import load_config
from src.counter import CountedProblem
from src.functions import make
from src.methods import METHODS

ETIQUETA = {"gd": "descenso por gradiente", "pso": "PSO", "de": "evolución diferencial", "ea": "algoritmo evolutivo"}
CON_POBLACION = {"pso", "de"}  # métodos que pueden registrar su población (record_population)


def _frames_idx(n: int, max_cuadros: int) -> np.ndarray:
    """Índices de cuadros: todos si caben; si no, más densos al inicio (donde pasa la acción)."""
    if n <= max_cuadros:
        return np.arange(n)
    return np.unique(np.geomspace(1, n, max_cuadros).astype(int)) - 1


def run_animated(metodo: str, name: str, seed: int, budget: float, grad_cost: float, hp: dict):
    """Corre el método en 2D registrando lo necesario para animar. Devuelve (problema, resultado)."""
    p = CountedProblem(make(name, 2))
    kw = dict(hp)
    if metodo in CON_POBLACION:
        kw["record_population"] = True
    return p, METHODS[metodo](p, seed, budget, grad_cost, **kw)


def make_gif(metodo: str, name: str, p: CountedProblem, r, path: Path, max_cuadros: int, duracion: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import imageio.v2 as imageio
    import matplotlib.pyplot as plt

    fn = p.fn
    lo, hi = fn.bounds
    xs = np.linspace(lo[0], hi[0], 300)
    ys = np.linspace(lo[1], hi[1], 300)
    X, Y = np.meshgrid(xs, ys)
    Z = fn.f(np.stack([X, Y], axis=-1))
    levels = np.geomspace(max(Z.min() + 1e-2, 1e-2), Z.max(), 25)

    best = np.array(r.history_x)  # mejor punto (GD: posición actual) por iteración
    pops = r.history_pop if metodo in CON_POBLACION else None
    n = len(best)
    frames = []
    for k in _frames_idx(n, max_cuadros):
        fig, ax = plt.subplots(figsize=(5, 4.2))
        ax.contour(X, Y, Z, levels=levels, cmap="viridis", linewidths=0.6)
        ax.plot(*fn.x_opt, "r*", ms=12, label="mínimo global")
        if pops is not None:
            pts = pops[k]
            ax.plot(pts[:, 0], pts[:, 1], "o", color="tab:orange", ms=4, alpha=0.8, label="población")
            ax.plot(*best[k], "o", color="tab:red", mec="k", ms=7, label="mejor")
        else:
            ax.plot(best[: k + 1, 0], best[: k + 1, 1], "-", color="tab:orange", lw=1)
            ax.plot(*best[k], "o", color="tab:red", ms=6)
        ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_xlabel("x1"); ax.set_ylabel("x2")
        ax.set_title(f"{name} 2D · {ETIQUETA[metodo]}\niteración {k} · {int(r.history_evals[k])} evals · "
                     f"f-f*={max(r.history_f[k] - p.f_opt, 0):.2e}", fontsize=9)
        if k == 0:
            ax.legend(fontsize=7, loc="upper right")
        fig.tight_layout(); fig.canvas.draw()
        frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()); plt.close(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    imageio.mimsave(path, frames, duration=duracion, loop=0)


def run_animations(cfg: dict, figures_dir: Path) -> list[Path]:
    desconocidos = set(cfg["metodos"]) - set(METHODS)
    if desconocidos:
        raise ValueError(f"métodos sin registrar en src/methods.py: {sorted(desconocidos)}")
    out = []
    for metodo, por_funcion in cfg["metodos"].items():
        for name in cfg["funciones"]:
            hp = dict((por_funcion or {}).get(name) or {})
            p, r = run_animated(metodo, name, int(cfg.get("semilla", 0)), float(cfg["presupuesto"]),
                                float(cfg.get("grad_cost", 1.0)), hp)
            path = Path(figures_dir) / f"anim_{metodo}_{name}.gif"
            make_gif(metodo, name, p, r, path, int(cfg.get("max_cuadros", 60)), float(cfg.get("duracion_cuadro", 0.15)))
            out.append(path)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/anim.yaml")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR",
                    help="cambia un parámetro del YAML, p. ej. --set semilla=3 (se puede repetir)")
    ap.add_argument("--figures", help="carpeta de salida (por defecto, salidas.figuras del YAML)")
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.set)
    figures = Path(a.figures or cfg.get("salidas", {}).get("figuras", "figures/anim"))
    for path in run_animations(cfg, figures):
        print("GIF:", path)


if __name__ == "__main__":
    main()
