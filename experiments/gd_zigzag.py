"""Mide si el descenso por gradiente zigzaguea (evidencia del hallazgo H-04 de docs/alucinaciones.md).

Para cada corrida 2D cuenta la fracción de pasos que «se devuelven» respecto al paso anterior
(coseno del ángulo entre pasos consecutivos < 0). Usa las mismas semillas y presupuesto que configs/gd.yaml.

Uso (desde la raíz del repositorio):
    python -m experiments.gd_zigzag
"""
from __future__ import annotations

import numpy as np

from src.counter import CountedProblem
from src.functions import make
from src.gradient_descent import gradient_descent, initial_point
from src.seeds import SEEDS


def fraccion_zigzag(history_x) -> float:
    d = np.diff(np.asarray(history_x), axis=0)
    n = np.linalg.norm(d, axis=1)
    ok = (n[:-1] > 0) & (n[1:] > 0)
    if not ok.any():
        return 0.0
    cos = (d[:-1] * d[1:]).sum(axis=1)[ok] / (n[:-1] * n[1:])[ok]
    return float((cos < 0).mean())


def main() -> None:
    for name, lr in [("rosenbrock", 2e-4), ("rosenbrock", 1e-3), ("rastrigin", 3e-3)]:
        fr = []
        for seed in SEEDS[:30]:
            p = CountedProblem(make(name, 2))
            r = gradient_descent(p, initial_point(p, seed), lr=lr, max_iters=10**9, budget=20000,
                                 grad_cost=1.0, grad_tol=1e-12)
            fr.append(fraccion_zigzag(r.history_x))
        print(f"{name} 2D, lr={lr:g}: pasos que se devuelven, mediana {np.median(fr):.2%}, máximo {np.max(fr):.2%}")
    # Sobre el fondo del valle (x2 = x1²) Rosenbrock vale (1 - x1)²: el valle sigue más allá de (1, 1)
    x1 = np.array([-2.0, 0.0, 1.0, 2.0, 3.0])
    print("f en el fondo del valle, x1 =", x1, "->", make("rosenbrock", 2).f(np.stack([x1, x1**2], axis=-1)))


if __name__ == "__main__":
    main()
