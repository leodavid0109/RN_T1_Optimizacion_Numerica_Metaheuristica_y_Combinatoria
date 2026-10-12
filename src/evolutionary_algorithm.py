
"""Algoritmo evolutivo sencillo para minimizar funciones continuas."""
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

    # Validar los parámetros principales
    if budget < 1 or population_size < 2:
        raise ValueError("Presupuesto o población inválidos")
    if not 0 <= crossover_rate <= 1:
        raise ValueError("crossover_rate debe estar entre 0 y 1")
    if mutation_rate is not None and not 0 <= mutation_rate <= 1:
        raise ValueError("mutation_rate debe estar entre 0 y 1")
    if mutation_scale < 0 or tournament_size < 1:
        raise ValueError("Parámetros de mutación o torneo inválidos")

    rng = np.random.default_rng(seed)

    # Obtener los límites de las soluciones
    lower, upper = problem.bounds
    lower = np.broadcast_to(np.asarray(lower, dtype=float), (problem.n,))
    upper = np.broadcast_to(np.asarray(upper, dtype=float), (problem.n,))
    span = upper - lower

    if mutation_rate is None:
        mutation_rate = 1 / problem.n

    # 1. Crear la población inicial
    n_initial = min(population_size, int(budget))
    population = rng.uniform(lower, upper, (n_initial, problem.n))
    fitness = np.asarray(problem.f(population)).reshape(-1)

    # Guardar la mejor solución encontrada
    best_i = np.argmin(fitness)
    best_x = population[best_i].copy()
    best_f = float(fitness[best_i])

    result = RunResult(
        best_x=best_x.copy(),
        best_f=best_f,
        f_evals=0,
        grad_evals=0,
    )
    result.history_f.append(best_f)
    result.history_x.append(best_x.copy())
    result.history_evals.append(problem.equivalent_evals(grad_cost))

    # 2. Evolucionar hasta agotar el presupuesto
    while problem.equivalent_evals(grad_cost) < budget:

        remaining = int(budget - problem.equivalent_evals(grad_cost))
        if remaining <= 0:
            break

        n_children = min(population_size, remaining)
        children = []

        for _ in range(n_children):

            # 3. Seleccionar dos padres mediante torneo
            candidates = rng.integers(
                0, len(population), size=tournament_size
            )
            parent1 = population[candidates[np.argmin(fitness[candidates])]]

            candidates = rng.integers(
                0, len(population), size=tournament_size
            )
            parent2 = population[candidates[np.argmin(fitness[candidates])]]

            # 4. Cruzar los padres
            if rng.random() < crossover_rate:
                alpha = rng.random()
                child = alpha * parent1 + (1 - alpha) * parent2
            else:
                child = parent1.copy()

            # 5. Mutar el hijo
            mask = rng.random(problem.n) < mutation_rate
            noise = rng.normal(0, mutation_scale * span)
            child = np.clip(child + mask * noise, lower, upper)

            children.append(child)

        # 6. Evaluar los hijos
        children = np.array(children)
        child_fitness = np.asarray(problem.f(children)).reshape(-1)

        # 7. Conservar los mejores individuos
        population = np.vstack((population, children))
        fitness = np.concatenate((fitness, child_fitness))

        best_indices = np.argsort(fitness)[:population_size]
        population = population[best_indices]
        fitness = fitness[best_indices]

        # Actualizar la mejor solución global
        if fitness[0] < best_f:
            best_f = float(fitness[0])
            best_x = population[0].copy()

        result.best_x = best_x.copy()
        result.best_f = best_f
        result.history_f.append(best_f)
        result.history_x.append(best_x.copy())
        result.history_evals.append(problem.equivalent_evals(grad_cost))

    result.f_evals = problem.f_evals
    result.grad_evals = problem.grad_evals
    result.stop_reason = "budget"

    return result
