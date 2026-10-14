"""Algoritmo genético (GA) para problemas TSP dirigidos y objetivos del contrato común.

Representación: permutación de índices de ciudades (el cierre del ciclo lo añade el objetivo).
Esquema generacional con elitismo:

    1. Población inicial: permutaciones aleatorias.
    2. Selección de padres por torneo de tamaño ``tournament_size``.
    3. Cruce (con probabilidad ``crossover_rate``): OX (order crossover) o PMX.
       Si no hay cruce, el hijo es copia del primer padre.
    4. Mutación (con probabilidad ``mutation_rate`` por hijo): intercambio (swap) o inversión de un tramo.
    5. Reemplazo: los ``elite_size`` mejores individuos pasan intactos (sin reevaluar) y el resto de
       la población son los hijos nuevos.

Presupuesto: cada hijo cuesta exactamente una evaluación completa de ruta (``RunEvaluator``). Los
élites no se reevalúan. Una generación parcial al final solo evalúa los hijos que el presupuesto permite.
"""
from __future__ import annotations

from numbers import Integral
from math import isfinite

import numpy as np

from .contracts import TSPObjective, TSPRunResult
from .evaluation import RunEvaluator

CROSSOVERS = ("ox", "pmx")
MUTATIONS = ("swap", "inversion")


class GeneticAlgorithm:
    """GA generacional con selección por torneo, cruce de permutaciones y elitismo.

    Parámetros específicos de ``run``: ``population_size``, ``crossover_rate``, ``mutation_rate``,
    ``tournament_size``, ``elite_size``, ``crossover`` ("ox" o "pmx") y ``mutation``
    ("swap" o "inversion"). No mantiene estado entre ejecuciones.
    """

    def run(
        self,
        problem: TSPObjective,
        seed: int,
        budget: int,
        **params,
    ) -> TSPRunResult:
        if not isinstance(seed, Integral) or isinstance(seed, (bool, np.bool_)):
            raise ValueError("seed debe ser un entero")
        population_size = _integer(params.pop("population_size", 100), "population_size", minimum=2)
        crossover_rate = _probability(params.pop("crossover_rate", 0.9), "crossover_rate")
        mutation_rate = _probability(params.pop("mutation_rate", 0.2), "mutation_rate")
        tournament_size = _integer(params.pop("tournament_size", 3), "tournament_size", minimum=1)
        elite_size = _integer(params.pop("elite_size", 2), "elite_size", minimum=0)
        crossover = params.pop("crossover", "ox")
        mutation = params.pop("mutation", "inversion")
        if params:
            raise TypeError(f"parámetros GA desconocidos: {', '.join(sorted(params))}")
        if crossover not in CROSSOVERS:
            raise ValueError(f"crossover debe ser uno de {CROSSOVERS}")
        if mutation not in MUTATIONS:
            raise ValueError(f"mutation debe ser uno de {MUTATIONS}")
        if elite_size >= population_size:
            raise ValueError("elite_size debe ser menor que population_size")

        size = problem.size
        if isinstance(size, (bool, np.bool_)) or not isinstance(size, Integral) or size < 2:
            raise ValueError("problem.size debe ser un entero de al menos dos ciudades")
        size = int(size)

        evaluator = RunEvaluator(problem, budget)
        rng = np.random.default_rng(int(seed))
        cross = _order_crossover if crossover == "ox" else _pmx_crossover
        mutate = _swap_mutation if mutation == "swap" else _inversion_mutation

        # 1. Población inicial (nunca más grande que el presupuesto disponible)
        n0 = min(population_size, evaluator.budget)
        population = np.array([rng.permutation(size) for _ in range(n0)], dtype=np.int64)
        costs = np.array([evaluator.evaluate(tuple(map(int, route))).total_cost_eur for route in population])

        # 2. Generaciones. Si n0 < population_size el presupuesto ya se agotó y el ciclo no corre.
        while evaluator.objective_evaluations < evaluator.budget:
            remaining = evaluator.budget - evaluator.objective_evaluations
            n_children = min(population_size - elite_size, remaining)
            elite_idx = np.argsort(costs, kind="stable")[:elite_size]
            children = np.empty((n_children, size), dtype=np.int64)
            child_costs = np.empty(n_children, dtype=float)

            for k in range(n_children):
                parent_a = population[_tournament(costs, tournament_size, rng)]
                parent_b = population[_tournament(costs, tournament_size, rng)]
                child = cross(parent_a, parent_b, rng) if rng.random() < crossover_rate else parent_a.copy()
                if rng.random() < mutation_rate:
                    child = mutate(child, rng)
                children[k] = child
                child_costs[k] = evaluator.evaluate(tuple(map(int, child))).total_cost_eur

            population = np.vstack([population[elite_idx], children])
            costs = np.concatenate([costs[elite_idx], child_costs])

        return evaluator.finish(int(seed), stop_reason="presupuesto_agotado")


# ---------------------------------------------------------------- operadores
def _tournament(costs: np.ndarray, k: int, rng: np.random.Generator) -> int:
    """Índice del mejor (menor costo) entre k individuos elegidos con reemplazo."""
    contenders = rng.integers(0, len(costs), size=k)
    return int(contenders[np.argmin(costs[contenders])])


def _cut_points(n: int, rng: np.random.Generator) -> tuple[int, int]:
    i, j = sorted(int(v) for v in rng.integers(0, n, size=2))
    return i, j  # tramo inclusivo [i, j]


def _order_crossover(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """OX: copia un tramo de ``a`` y completa con las ciudades restantes en el orden de ``b``."""
    n = len(a)
    i, j = _cut_points(n, rng)
    child = np.full(n, -1, dtype=np.int64)
    child[i : j + 1] = a[i : j + 1]
    used = np.zeros(n, dtype=bool)
    used[a[i : j + 1]] = True
    pos = (j + 1) % n
    for k in range(n):
        gene = b[(j + 1 + k) % n]
        if not used[gene]:
            child[pos] = gene
            pos = (pos + 1) % n
    return child


def _pmx_crossover(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """PMX: copia un tramo de ``a`` y resuelve los conflictos con el mapeo de ese tramo hacia ``b``."""
    n = len(a)
    i, j = _cut_points(n, rng)
    child = np.full(n, -1, dtype=np.int64)
    child[i : j + 1] = a[i : j + 1]
    in_segment = np.zeros(n, dtype=bool)
    in_segment[a[i : j + 1]] = True
    position_in_b = np.empty(n, dtype=np.int64)
    position_in_b[b] = np.arange(n)
    for k in range(i, j + 1):
        gene = b[k]
        if in_segment[gene]:
            continue
        pos = k
        while i <= pos <= j:  # sigue el mapeo a[pos] -> posición de ese gen en b
            pos = position_in_b[a[pos]]
        child[pos] = gene
    free = child == -1
    child[free] = b[free]
    return child


def _swap_mutation(route: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    mutated = route.copy()
    n = len(mutated)
    if n < 2:
        return mutated
    i, j = rng.choice(n, size=2, replace=False)
    mutated[i], mutated[j] = mutated[j], mutated[i]
    return mutated


def _inversion_mutation(route: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    mutated = route.copy()
    i, j = _cut_points(len(mutated), rng)
    mutated[i : j + 1] = mutated[i : j + 1][::-1]
    return mutated


# ---------------------------------------------------------------- validación
def _integer(value, name: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} debe ser un entero mayor o igual que {minimum}")
    return int(value)


def _probability(value, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} debe ser numérico")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser numérico") from exc
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} debe estar entre 0 y 1")
    return number
