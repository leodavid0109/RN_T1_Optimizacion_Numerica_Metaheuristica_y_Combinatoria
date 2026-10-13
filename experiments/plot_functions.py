"""Curvas de nivel de las funciones de prueba de la Parte 1 en 2D (figura del informe).

Uso (desde la raíz del repositorio):
    python -m experiments.plot_functions
    python -m experiments.plot_functions --salida figures/funciones

Salida: <salida>/funciones_niveles.png (Rosenbrock y Rastrigin lado a lado, sin trayectorias).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from src.functions import make


def main() -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", default="figures/funciones")
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for ax, name in zip(axes, ["rosenbrock", "rastrigin"]):
        fn = make(name, 2)
        lo, hi = fn.bounds
        xs = np.linspace(lo[0], hi[0], 400); ys = np.linspace(lo[1], hi[1], 400)
        X, Y = np.meshgrid(xs, ys)
        Z = fn.f(np.stack([X, Y], axis=-1))
        # Rosenbrock varía en muchos órdenes de magnitud: niveles logarítmicos; Rastrigin, lineales
        levels = np.geomspace(1e-1, Z.max(), 30) if name == "rosenbrock" else np.linspace(0, Z.max(), 30)
        cs = ax.contour(X, Y, Z, levels=levels, cmap="viridis", linewidths=0.6)
        ax.plot(*fn.x_opt, "r*", ms=12, label="mínimo global")
        ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_xlabel("x1"); ax.set_ylabel("x2")
        ax.set_title(f"{name.capitalize()} 2D"); ax.legend(fontsize=8, loc="upper left")
        fig.colorbar(cs, ax=ax, shrink=0.85, label="f(x)")
    fig.tight_layout(); fig.savefig(salida / "funciones_niveles.png", dpi=140); plt.close(fig)
    print("ok", salida / "funciones_niveles.png")


if __name__ == "__main__":
    main()
