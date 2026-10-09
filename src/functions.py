"""Funciones de prueba con gradiente analítico.

Todas aceptan x de forma (n,) o (m, n) y devuelven escalar o vector (m,).
Esta clase NO cuenta evaluaciones: para eso se envuelve con src.counter.CountedProblem.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TestFunction:
    name: str
    n: int
    lower: float
    upper: float
    x_opt: np.ndarray
    f_opt: float

    def f(self, x):  # pragma: no cover - lo implementan las subclases
        raise NotImplementedError

    def grad(self, x):  # pragma: no cover
        raise NotImplementedError

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return np.full(self.n, self.lower), np.full(self.n, self.upper)


class Rosenbrock(TestFunction):
    """f(x) = sum_{i=1}^{n-1} [100 (x_{i+1} - x_i^2)^2 + (1 - x_i)^2].

    Mínimo global único: x* = (1, ..., 1), f(x*) = 0 (para n >= 2).
    Valle curvo y estrecho: mal condicionada.
    """

    def __init__(self, n: int = 2, lower: float = -5.0, upper: float = 10.0):
        if n < 2:
            raise ValueError("Rosenbrock necesita n >= 2")
        object.__setattr__(self, "name", "rosenbrock")
        object.__setattr__(self, "n", n)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "x_opt", np.ones(n))
        object.__setattr__(self, "f_opt", 0.0)

    def f(self, x):
        x = np.asarray(x, dtype=float)
        a, b = x[..., :-1], x[..., 1:]
        return np.sum(100.0 * (b - a**2) ** 2 + (1.0 - a) ** 2, axis=-1)

    def grad(self, x):
        x = np.asarray(x, dtype=float)
        g = np.zeros_like(x)
        a, b = x[..., :-1], x[..., 1:]
        g[..., :-1] += -400.0 * a * (b - a**2) - 2.0 * (1.0 - a)
        g[..., 1:] += 200.0 * (b - a**2)
        return g


class Rastrigin(TestFunction):
    """f(x) = A n + sum_i [x_i^2 - A cos(2 pi x_i)], con A = 10.

    Mínimo global único: x* = 0, f(x*) = 0. Muchísimos mínimos locales.
    """

    A = 10.0

    def __init__(self, n: int = 2, lower: float = -5.12, upper: float = 5.12):
        object.__setattr__(self, "name", "rastrigin")
        object.__setattr__(self, "n", n)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "x_opt", np.zeros(n))
        object.__setattr__(self, "f_opt", 0.0)

    def f(self, x):
        x = np.asarray(x, dtype=float)
        A = self.A
        return A * x.shape[-1] + np.sum(x**2 - A * np.cos(2.0 * np.pi * x), axis=-1)

    def grad(self, x):
        x = np.asarray(x, dtype=float)
        return 2.0 * x + 2.0 * np.pi * self.A * np.sin(2.0 * np.pi * x)


REGISTRY = {"rosenbrock": Rosenbrock, "rastrigin": Rastrigin}


def make(name: str, n: int) -> TestFunction:
    return REGISTRY[name](n)
