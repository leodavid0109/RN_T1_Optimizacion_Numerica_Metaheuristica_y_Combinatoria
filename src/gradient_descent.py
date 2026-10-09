"""Descenso por gradiente con paso fijo, proyección al dominio y presupuesto de evaluaciones."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .counter import CountedProblem


@dataclass
class RunResult:
    best_x: np.ndarray
    best_f: float
    f_evals: int
    grad_evals: int
    history_f: list = field(default_factory=list)   # mejor f tras cada iteración
    history_x: list = field(default_factory=list)   # trayectoria (para GIF)
    history_evals: list = field(default_factory=list)  # evaluaciones equivalentes acumuladas
    stop_reason: str = ""


def initial_point(problem: CountedProblem, seed: int) -> np.ndarray:
    """Punto inicial uniforme en el dominio, determinista según la semilla."""
    lo, hi = problem.bounds
    return np.random.default_rng(seed).uniform(lo, hi)


def gradient_descent(
    problem: CountedProblem,
    x0: np.ndarray,
    lr: float,
    max_iters: int = 10_000,
    budget: float | None = None,
    grad_cost: float = 1.0,
    grad_tol: float = 1e-10,
    numeric: bool = False,
) -> RunResult:
    """x_{k+1} = clip(x_k - lr * grad f(x_k)).

    Se detiene al agotar `budget` (evaluaciones equivalentes), `max_iters`
    o cuando ||grad|| < grad_tol. Con numeric=True usa diferencias centrales.
    """
    lo, hi = problem.bounds
    x = np.clip(np.asarray(x0, dtype=float), lo, hi)
    fx = float(problem.f(x))
    res = RunResult(x.copy(), fx, 0, 0)
    res.history_f.append(fx)
    res.history_x.append(x.copy())
    res.history_evals.append(problem.equivalent_evals(grad_cost))
    reason = "max_iters"

    for _ in range(max_iters):
        if budget is not None and problem.equivalent_evals(grad_cost) >= budget:
            reason = "budget"
            break
        g = problem.grad_numeric(x) if numeric else problem.grad(x)
        if np.linalg.norm(g) < grad_tol:
            reason = "grad_tol"
            break
        x = np.clip(x - lr * g, lo, hi)
        fx = float(problem.f(x))
        if fx < res.best_f:
            res.best_f, res.best_x = fx, x.copy()
        res.history_f.append(res.best_f)
        res.history_x.append(x.copy())
        res.history_evals.append(problem.equivalent_evals(grad_cost))
    else:
        reason = "max_iters"

    res.f_evals, res.grad_evals = problem.f_evals, problem.grad_evals
    res.stop_reason = reason
    return res
