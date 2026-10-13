"""Enumeración exacta restringida para validar objetivos TSP pequeños."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from math import factorial, isclose
from numbers import Integral

from .contracts import TSPObjective
from .evaluation import RunEvaluator


MAX_EXACT_CITIES = 9


@dataclass(frozen=True)
class ExactTSPResult:
    """Óptimo global de una instancia pequeña y todas sus rutas empatadas."""

    best_route: tuple[int, ...]
    best_cost_eur: float
    optimal_routes: tuple[tuple[int, ...], ...]
    objective_evaluations: int


def solve_exact_small(problem: TSPObjective) -> ExactTSPResult:
    """Enumera ciclos dirigidos fijando la ciudad 0; rechaza N mayor que nueve.

    El costo se evalúa mediante el objetivo existente y `RunEvaluator`. Por eso
    ``objective_evaluations`` informa exactamente las `(N-1)!` rutas evaluadas.
    Este validador no debe emplearse en la instancia española de 47 ciudades.
    """
    size = problem.size
    if not isinstance(size, Integral) or isinstance(size, bool) or size < 2:
        raise ValueError("el problema exacto necesita al menos dos ciudades")
    if size > MAX_EXACT_CITIES:
        raise ValueError(f"la enumeración exacta está limitada a {MAX_EXACT_CITIES} ciudades")
    budget = factorial(int(size) - 1)
    evaluator = RunEvaluator(problem, budget)
    optimum = float("inf")
    optimal_routes: list[tuple[int, ...]] = []
    for tail in permutations(range(1, int(size))):
        route = (0, *tail)
        breakdown = evaluator.evaluate(route)
        cost = breakdown.total_cost_eur
        if not optimal_routes:
            optimum = cost
            optimal_routes = [route]
        elif isclose(cost, optimum, rel_tol=1e-12, abs_tol=1e-12):
            optimal_routes.append(route)
            optimum = min(optimum, cost)
        elif cost < optimum:
            # Una mejora que no se considera empate reemplaza la frontera óptima.
            optimum = cost
            optimal_routes = [route]
    run = evaluator.finish(seed=0, stop_reason="enumeracion_completa")
    return ExactTSPResult(
        best_route=run.best_route,
        best_cost_eur=run.best_cost_eur,
        optimal_routes=tuple(sorted(set(optimal_routes))),
        objective_evaluations=evaluator.objective_evaluations,
    )
