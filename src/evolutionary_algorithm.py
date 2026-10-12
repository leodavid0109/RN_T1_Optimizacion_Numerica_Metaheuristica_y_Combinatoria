"""Algoritmo evolutivo de codificación real para minimizar funciones continuas.

Contrato del proyecto:
    run_ea(problem, seed, budget, grad_cost=1.0, **hyperparameters) -> RunResult

Usa selección por torneo, cruce aritmético, mutación gaussiana y supervivencia elitista.
Solo evalúa mediante problem.f para que el contador común registre el costo.
"""
from __future__ import annotations

import numpy as np

from .result import RunResult


def run_ea(
    problem,
    seed: int,
    budget: float,
    grad_cost: float = 1.0,
    population_size: int = 30,
    crossover_rate: float = 0.9,
    mutation_rate: float | None = None,
    mutation_scale: float = 0.1,
    tournament_size: int = 3,
) -> RunResult:
    """Minimiza ``problem.f`` con un algoritmo evolutivo de individuos reales.

    ``mutation_scale`` es la desviación estándar de la mutación como fracción
    del ancho del dominio. El presupuesto se respeta incluso en la última
    generación, que puede evaluar menos descendientes que las anteriores.
    """
    if budget < 1:
        raise ValueError("budget debe ser al menos 1")
    if population_size < 2:
        raise ValueError("population_size debe ser al menos 2")
    if not 0.0 <= crossover_rate <= 1.0:
        raise ValueError("crossover_rate debe estar entre 0 y 1")
    if mutation_rate is not None and not 0.0 <= mutation_rate <= 1.0:
        raise ValueError("mutation_rate debe estar entre 0 y 1")
    if mutation_scale < 0:
        raise ValueError("mutation_scale debe ser no negativo")
    if tournament_size < 1:
        raise ValueError("tournament_size debe ser al menos 1")

    rng = np.random.default_rng(seed)
    lo, hi = (np.asarray(v, dtype=float) for v in problem.bounds)
    if lo.ndim == 0:
        lo = np.full(problem.n, lo.item())
    if hi.ndim == 0:
        hi = np.full(problem.n, hi.item())
    span = hi - lo
    pm = 1.0 / problem.n if mutation_rate is None else mutation_rate

    # La población inicial se ajusta al presupuesto disponible.
    n_initial = min(population_size, int(budget))
    population = rng.uniform(lo, hi, size=(n_initial, problem.n))
    fitness = np.asarray(problem.f(population), dtype=float).reshape(-1)

    best_i = int(np.argmin(fitness))
    best_x = population[best_i].copy()
    best_f = float(fitness[best_i])
    result = RunResult(best_x=best_x.copy(), best_f=best_f, f_evals=0, grad_evals=0)
    result.history_f.append(best_f)
    result.history_x.append(best_x.copy())
    result.history_evals.append(problem.equivalent_evals(grad_cost))

    while problem.equivalent_evals(grad_cost) < budget:
        remaining = int(budget - problem.equivalent_evals(grad_cost))
        if remaining <= 0:
            break
        n_children = min(population_size, remaining)

        # Selección por torneo: gana el individuo de menor valor objetivo.
        parents_idx = np.empty(n_children, dtype=int)
        for i in range(n_children):
            candidates = rng.integers(0, len(population), size=tournament_size)
            parents_idx[i] = candidates[np.argmin(fitness[candidates])]
        parents = population[parents_idx]
        mates_idx = rng.integers(0, len(population), size=n_children)
        mates = population[mates_idx]

        # Cruce aritmético entre cada padre y su pareja.
        alpha = rng.random((n_children, 1))
        children = alpha * parents + (1.0 - alpha) * mates
        cross_mask = rng.random(n_children) < crossover_rate
        children[~cross_mask] = parents[~cross_mask]

        # Mutación gaussiana independiente por gen/coordenada.
        mutation_mask = rng.random(children.shape) < pm
        noise = rng.normal(0.0, mutation_scale * span, size=children.shape)
        children = np.clip(children + mutation_mask * noise, lo, hi)

        child_fitness = np.asarray(problem.f(children), dtype=float).reshape(-1)

        # Supervivencia elitista: se conservan los mejores entre padres e hijos.
        combined_x = np.vstack((population, children))
        combined_f = np.concatenate((fitness, child_fitness))
        keep = np.argsort(combined_f)[: min(population_size, len(combined_f))]
        population = combined_x[keep].copy()
        fitness = combined_f[keep].copy()

        best_i = int(np.argmin(fitness))
        if float(fitness[best_i]) < best_f:
            best_f = float(fitness[best_i])
            best_x = population[best_i].copy()

        result.best_x = best_x.copy()
        result.best_f = best_f
        result.history_f.append(best_f)
        result.history_x.append(best_x.copy())
        result.history_evals.append(problem.equivalent_evals(grad_cost))

    result.f_evals = problem.f_evals
    result.grad_evals = problem.grad_evals
    result.stop_reason = "budget"
    return result
