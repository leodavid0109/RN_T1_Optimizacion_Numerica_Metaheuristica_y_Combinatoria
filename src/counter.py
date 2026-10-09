"""Envoltorio que cuenta por separado evaluaciones de f y de grad f.

Convención (a justificar en el reporte):
  - Una evaluación de f cuenta 1 por cada punto evaluado (un lote de m puntos cuenta m).
  - grad analítico: se cuenta aparte en `grad_evals` (1 por punto).
  - grad numérico por diferencias centrales: 2n evaluaciones de f por punto.
  - `equivalent_evals(grad_cost)` suma f + grad_cost * grad, con grad_cost configurable
    (p. ej. 1, 2 o n+1) para comparar métodos con distinto presupuesto.
"""
from __future__ import annotations

import numpy as np

from .functions import TestFunction


class CountedProblem:
    def __init__(self, fn: TestFunction):
        self.fn = fn
        self.f_evals = 0
        self.grad_evals = 0

    # --- propiedades de solo lectura del problema
    @property
    def n(self) -> int:
        return self.fn.n

    @property
    def bounds(self):
        return self.fn.bounds

    @property
    def f_opt(self) -> float:
        return self.fn.f_opt

    @property
    def x_opt(self):
        return self.fn.x_opt

    # --- evaluaciones contadas
    def f(self, x):
        x = np.asarray(x, dtype=float)
        self.f_evals += 1 if x.ndim == 1 else x.shape[0]
        return self.fn.f(x)

    def grad(self, x):
        x = np.asarray(x, dtype=float)
        self.grad_evals += 1 if x.ndim == 1 else x.shape[0]
        return self.fn.grad(x)

    def grad_numeric(self, x, h: float = 1e-6):
        """Diferencias centrales: cuesta 2n evaluaciones de f (se cuentan en f_evals)."""
        x = np.asarray(x, dtype=float)
        if x.ndim != 1:
            raise ValueError("grad_numeric admite un solo punto")
        g = np.empty_like(x)
        for i in range(x.size):
            e = np.zeros_like(x)
            e[i] = h
            g[i] = (self.f(x + e) - self.f(x - e)) / (2.0 * h)
        return g

    # --- utilidades
    def equivalent_evals(self, grad_cost: float = 1.0) -> float:
        return self.f_evals + grad_cost * self.grad_evals

    def reset(self) -> None:
        self.f_evals = 0
        self.grad_evals = 0
