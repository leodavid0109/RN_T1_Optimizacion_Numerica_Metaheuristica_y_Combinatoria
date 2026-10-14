"""Particle Swarm Optimization (PSO), siguiendo la regla del notebook del profesor.

Compatible con el contrato del proyecto:
    run_pso(problem, seed, budget, grad_cost=1.0, **hyperparameters) -> RunResult

La función minimiza el objetivo y respeta el presupuesto de evaluaciones.
"""
from __future__ import annotations

import numpy as np

from .result import RunResult


def run_pso(
    problem,
    seed: int,
    budget: float,
    grad_cost: float = 1.0,
    n_particles: int = 30,
    c1: float = 0.8,
    c2: float = 0.4,
    w: float = 0.1,
    record_population: bool = False,
) -> RunResult:
    """Minimiza `problem.f` usando Global-Best PSO.

    r1 y r2 se generan independientemente por partícula y coordenada.
    Las posiciones se recortan a los límites del problema.
    """
    if budget < 1:
        raise ValueError("budget debe ser al menos 1")
    if n_particles < 2:
        raise ValueError("n_particles debe ser al menos 2")
    if c1 < 0 or c2 < 0 or w < 0:
        raise ValueError("c1, c2 y w deben ser no negativos")

    rng = np.random.default_rng(seed)
    lo, hi = (np.asarray(v, dtype=float) for v in problem.bounds)
    if lo.ndim == 0:
        lo = np.full(problem.n, lo.item())
    if hi.ndim == 0:
        hi = np.full(problem.n, hi.item())

    # El tamaño inicial nunca puede exceder el presupuesto disponible.
    n0 = min(n_particles, int(budget))
    x = rng.uniform(lo, hi, size=(n0, problem.n))
    span = hi - lo
    # Velocidades iniciales moderadas.
    v = rng.uniform(-0.1 * span, 0.1 * span, size=(n0, problem.n))

    fx = np.asarray(problem.f(x), dtype=float).reshape(-1)
    pbest_x = x.copy()
    pbest_f = fx.copy()
    best_i = int(np.argmin(pbest_f))
    gbest_x = pbest_x[best_i].copy()
    gbest_f = float(pbest_f[best_i])

    result = RunResult(best_x=gbest_x.copy(), best_f=gbest_f, f_evals=0, grad_evals=0)
    result.history_f.append(gbest_f)
    result.history_x.append(gbest_x.copy())
    result.history_evals.append(problem.equivalent_evals(grad_cost))
    if record_population:  # solo para animaciones: no cambia la ejecución
        result.history_pop.append(x.copy())

    # Cada paso actualiza todas las partículas; si queda un presupuesto parcial,
    # solo se evalúa ese número de partículas para no excederlo.
    while problem.equivalent_evals(grad_cost) < budget:
        remaining = int(budget - problem.equivalent_evals(grad_cost))
        if remaining <= 0:
            break

        r1 = rng.random(size=x.shape)
        r2 = rng.random(size=x.shape)
        v = w * v + c1 * r1 * (pbest_x - x) + c2 * r2 * (gbest_x - x)
        x = np.clip(x + v, lo, hi)

        n_eval = min(len(x), remaining)
        current_f = np.asarray(problem.f(x[:n_eval]), dtype=float).reshape(-1)
        improved = current_f < pbest_f[:n_eval]
        pbest_x[:n_eval][improved] = x[:n_eval][improved]
        pbest_f[:n_eval][improved] = current_f[improved]

        best_i = int(np.argmin(pbest_f))
        if pbest_f[best_i] < gbest_f:
            gbest_f = float(pbest_f[best_i])
            gbest_x = pbest_x[best_i].copy()

        result.best_x = gbest_x.copy()
        result.best_f = gbest_f
        result.history_f.append(gbest_f)
        result.history_x.append(gbest_x.copy())
        result.history_evals.append(problem.equivalent_evals(grad_cost))
        if record_population:
            result.history_pop.append(x.copy())

    result.f_evals = problem.f_evals
    result.grad_evals = problem.grad_evals
    result.stop_reason = "budget"
    return result