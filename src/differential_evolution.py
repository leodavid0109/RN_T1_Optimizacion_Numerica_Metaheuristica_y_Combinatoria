"""Evolución diferencial DE/rand/1/bin para minimizar funciones continuas.

Compatible con el contrato del proyecto (ver src/result.py):
    run_de(problem, seed, budget, grad_cost=1.0, **hiperparametros) -> RunResult

Para cada individuo objetivo x_i de la población (generación sincrónica):
    mutación:   v_i = x_r1 + F * (x_r2 - x_r3),   r1, r2, r3 distintos entre sí y distintos de i
    cruce bin.: u_ij = v_ij  si rand_j < CR  o  j = j_rand;   u_ij = x_ij  en otro caso
    selección:  x_i <- u_i  si f(u_i) <= f(x_i)

Cada hijo cuesta una evaluación de f. Si queda un presupuesto parcial, solo se evalúan
(y compiten) los primeros hijos que alcancen, de modo que nunca se excede el presupuesto.
"""
from __future__ import annotations

import numpy as np

from .result import RunResult


def run_de(
    problem,
    seed: int,
    budget: float,
    grad_cost: float = 1.0,
    population_size: int = 30,
    F: float = 0.5,
    CR: float = 0.9,
) -> RunResult:
    """Minimiza `problem.f` con DE/rand/1/bin. Los límites del dominio se imponen recortando."""
    if budget < 1:
        raise ValueError("budget debe ser al menos 1")
    if population_size < 4:
        raise ValueError("population_size debe ser al menos 4 (DE/rand/1 necesita 3 individuos distintos)")
    if not 0 <= F <= 2:
        raise ValueError("F debe estar entre 0 y 2")
    if not 0 <= CR <= 1:
        raise ValueError("CR debe estar entre 0 y 1")

    rng = np.random.default_rng(seed)
    lo = np.broadcast_to(np.asarray(problem.bounds[0], dtype=float), (problem.n,))
    hi = np.broadcast_to(np.asarray(problem.bounds[1], dtype=float), (problem.n,))

    # 1. Población inicial (nunca más grande que el presupuesto disponible)
    n0 = min(population_size, int(budget))
    pop = rng.uniform(lo, hi, size=(n0, problem.n))
    fit = np.asarray(problem.f(pop), dtype=float).reshape(-1)

    best_i = int(np.argmin(fit))
    best_x = pop[best_i].copy()
    best_f = float(fit[best_i])

    result = RunResult(best_x=best_x.copy(), best_f=best_f, f_evals=0, grad_evals=0)
    result.history_f.append(best_f)
    result.history_x.append(best_x.copy())
    result.history_evals.append(problem.equivalent_evals(grad_cost))

    # 2. Generaciones hasta agotar el presupuesto.
    # Si n0 < population_size el presupuesto ya se agotó y el ciclo no corre.
    while problem.equivalent_evals(grad_cost) < budget:
        remaining = int(budget - problem.equivalent_evals(grad_cost))
        if remaining <= 0:
            break
        np_ = len(pop)

        # r1, r2, r3 distintos entre sí y distintos de i: tres primeros de una permutación
        # aleatoria de los índices con i excluido.
        keys = rng.random((np_, np_))
        np.fill_diagonal(keys, np.inf)
        r1, r2, r3 = np.argsort(keys, axis=1)[:, :3].T

        # 3. Mutación
        mutant = pop[r1] + F * (pop[r2] - pop[r3])

        # 4. Cruce binomial (al menos una coordenada viene del mutante)
        mask = rng.random((np_, problem.n)) < CR
        mask[np.arange(np_), rng.integers(0, problem.n, size=np_)] = True
        trial = np.clip(np.where(mask, mutant, pop), lo, hi)

        # 5. Evaluación (solo lo que alcance el presupuesto) y selección uno a uno
        n_eval = min(np_, remaining)
        trial_f = np.asarray(problem.f(trial[:n_eval]), dtype=float).reshape(-1)
        better = trial_f <= fit[:n_eval]
        pop[:n_eval][better] = trial[:n_eval][better]
        fit[:n_eval][better] = trial_f[better]

        best_i = int(np.argmin(fit))
        if fit[best_i] < best_f:
            best_f = float(fit[best_i])
            best_x = pop[best_i].copy()

        result.best_x = best_x.copy()
        result.best_f = best_f
        result.history_f.append(best_f)
        result.history_x.append(best_x.copy())
        result.history_evals.append(problem.equivalent_evals(grad_cost))

    result.f_evals = problem.f_evals
    result.grad_evals = problem.grad_evals
    result.stop_reason = "budget"
    return result
