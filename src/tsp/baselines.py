"""Líneas base TSP reproducibles: vecino más cercano y 2-opt dirigido."""

from __future__ import annotations

import random
from numbers import Integral
from typing import Iterable, Sequence

import numpy as np

from .contracts import TSPObjective, TSPRunResult
from .evaluation import RunEvaluator


class NearestNeighbor:
    """Vecino más cercano desde varios inicios; los empates favorecen índice menor."""

    def run(
        self,
        problem: TSPObjective,
        seed: int,
        budget: int,
        **params,
    ) -> TSPRunResult:
        costs = _cost_matrix(problem)
        start_cities = params.pop("start_cities", None)
        if params:
            raise TypeError(f"parámetros de vecino más cercano desconocidos: {', '.join(sorted(params))}")
        evaluator = RunEvaluator(problem, budget)
        rng = _rng(seed)
        starts = _start_order(problem.size, rng, start_cities)

        for start in starts:
            if evaluator.objective_evaluations >= evaluator.budget:
                break
            route = _nearest_neighbor_route(costs, start)
            evaluator.evaluate(route)

        stop = "inicios_agotados" if evaluator.objective_evaluations == len(starts) else "presupuesto_agotado"
        return evaluator.finish(int(seed), stop_reason=stop)


class TwoOpt:
    """Búsqueda 2-opt por inversión de segmentos, evaluando costos dirigidos completos.

    Si no se entrega ``initial_route``, genera un vecino más cercano desde la
    ciudad 0. La ruta inicial cuenta como una evaluación completa.
    """

    POLICIES = {"first_improvement", "best_improvement"}

    def run(
        self,
        problem: TSPObjective,
        seed: int,
        budget: int,
        **params,
    ) -> TSPRunResult:
        costs = _cost_matrix(problem)
        initial_route = params.pop("initial_route", None)
        policy = _policy(params.pop("policy", "best_improvement"))
        if params:
            raise TypeError(f"parámetros 2-opt desconocidos: {', '.join(sorted(params))}")
        evaluator = RunEvaluator(problem, budget)
        _rng(seed)  # valida la semilla; el recorrido de 2-opt es determinista.
        route = _nearest_neighbor_route(costs, 0) if initial_route is None else _validate_route(
            initial_route, problem.size
        )
        breakdown = evaluator.evaluate(route)
        stop = _improve_two_opt(evaluator, costs, route, breakdown.total_cost_eur, policy)
        return evaluator.finish(int(seed), stop_reason=stop)


class NearestNeighborTwoOpt:
    """Vecino más cercano mult inicio seguido de 2-opt con un presupuesto compartido."""

    POLICIES = TwoOpt.POLICIES

    def run(
        self,
        problem: TSPObjective,
        seed: int,
        budget: int,
        **params,
    ) -> TSPRunResult:
        costs = _cost_matrix(problem)
        start_cities = params.pop("start_cities", None)
        policy = _policy(params.pop("policy", "best_improvement"))
        if params:
            raise TypeError(f"parámetros vecino más cercano + 2-opt desconocidos: {', '.join(sorted(params))}")
        evaluator = RunEvaluator(problem, budget)
        rng = _rng(seed)
        starts = _start_order(problem.size, rng, start_cities)

        for start in starts:
            if evaluator.objective_evaluations >= evaluator.budget:
                break
            evaluator.evaluate(_nearest_neighbor_route(costs, start))

        if evaluator.objective_evaluations >= evaluator.budget:
            return evaluator.finish(int(seed), stop_reason="presupuesto_agotado")

        assert evaluator.best_route is not None and evaluator.best_breakdown is not None
        stop = _improve_two_opt(
            evaluator, costs, evaluator.best_route,
            evaluator.best_breakdown.total_cost_eur, policy,
        )
        return evaluator.finish(int(seed), stop_reason=stop)


def _improve_two_opt(
    evaluator: RunEvaluator,
    costs: np.ndarray,
    initial_route: tuple[int, ...],
    initial_cost: float,
    policy: str,
) -> str:
    current_route, current_cost = initial_route, initial_cost
    while evaluator.objective_evaluations < evaluator.budget:
        candidates = tuple(_two_opt_neighbors(current_route))
        if not candidates:
            return "optimo_local"

        chosen: tuple[int, ...] | None = None
        chosen_cost = current_cost
        for position, candidate in enumerate(candidates):
            breakdown = evaluator.evaluate(candidate)
            candidate_cost = breakdown.total_cost_eur
            if candidate_cost < current_cost and candidate_cost < chosen_cost:
                chosen, chosen_cost = candidate, candidate_cost
                if policy == "first_improvement":
                    current_route, current_cost = candidate, candidate_cost
                    break
            if evaluator.objective_evaluations == evaluator.budget:
                # Si se inspeccionó todo el vecindario, se conoce el óptimo local;
                # si quedó algún candidato, el motivo de parada es el presupuesto.
                if position < len(candidates) - 1:
                    return "presupuesto_agotado"
                if policy == "best_improvement" and chosen is not None:
                    current_route, current_cost = chosen, chosen_cost
                return "optimo_local" if chosen is None else "presupuesto_agotado"

        if chosen is None:
            return "optimo_local"
        if policy == "best_improvement":
            current_route, current_cost = chosen, chosen_cost

    return "presupuesto_agotado"


def _two_opt_neighbors(route: Sequence[int]) -> Iterable[tuple[int, ...]]:
    """Enumera inversiones cíclicas no degeneradas, normalizadas al mismo origen.

    Para una vuelta dirigida se consideran segmentos cíclicos de longitudes
    2..N-2. Cada candidato invierte también los arcos internos; no se usa una
    fórmula de delta simétrica. El conjunto elimina candidatos duplicados.
    """
    order = tuple(route)
    size = len(order)
    if size < 4:
        return
    anchor = order[0]
    seen: set[tuple[int, ...]] = set()
    for start in range(size):
        for length in range(2, size - 1):
            indices = tuple((start + offset) % size for offset in range(length))
            candidate = list(order)
            segment = [order[index] for index in indices][::-1]
            for index, city in zip(indices, segment):
                candidate[index] = city
            anchor_position = candidate.index(anchor)
            normalized = tuple(candidate[anchor_position:] + candidate[:anchor_position])
            if normalized != order and normalized not in seen:
                seen.add(normalized)
                yield normalized


def _nearest_neighbor_route(costs: np.ndarray, start: int) -> tuple[int, ...]:
    size = costs.shape[0]
    route = [start]
    unvisited = set(range(size))
    unvisited.remove(start)
    while unvisited:
        current = route[-1]
        # Ordenar por costo y luego por índice fija el desempate de manera estable.
        next_city = min(unvisited, key=lambda city: (float(costs[current, city]), city))
        route.append(next_city)
        unvisited.remove(next_city)
    return tuple(route)


def _cost_matrix(problem: TSPObjective) -> np.ndarray:
    costs = np.asarray(problem.cost_matrix_eur, dtype=float)
    if costs.shape != (problem.size, problem.size):
        raise ValueError("cost_matrix_eur tiene dimensiones incompatibles con problem.size")
    if not np.all(np.isfinite(costs)) or np.any(costs < 0):
        raise ValueError("la matriz de costos debe ser finita y no negativa")
    if float(np.max(costs)) > np.finfo(float).max / int(problem.size):
        raise ValueError("la matriz permite ciclos cuyo costo podría desbordar float64")
    if not np.allclose(np.diag(costs), 0.0, rtol=0.0, atol=1e-12):
        raise ValueError("la diagonal de la matriz de costos debe ser cero")
    return costs


def _rng(seed: int) -> random.Random:
    if not isinstance(seed, Integral) or isinstance(seed, (bool, np.bool_)):
        raise ValueError("seed debe ser un entero")
    return random.Random(int(seed))


def _start_order(size: int, rng: random.Random, starts: Sequence[int] | None) -> tuple[int, ...]:
    if starts is None:
        order = list(range(size))
        rng.shuffle(order)
        return tuple(order)
    order = _validate_route(starts, size, require_complete=False)
    if not order:
        raise ValueError("start_cities debe contener al menos una ciudad")
    return order


def _validate_route(route: Sequence[int], size: int, require_complete: bool = True) -> tuple[int, ...]:
    try:
        values = tuple(route)
    except TypeError as exc:
        raise ValueError("la ruta debe ser una secuencia de índices") from exc
    if require_complete and len(values) != size:
        raise ValueError(f"la ruta debe incluir exactamente {size} ciudades")
    if not require_complete and len(values) > size:
        raise ValueError("start_cities no puede exceder el número de ciudades")
    if any(not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)) for value in values):
        raise ValueError("los índices de ruta deben ser enteros")
    normalized = tuple(int(value) for value in values)
    if len(set(normalized)) != len(normalized) or any(not 0 <= value < size for value in normalized):
        raise ValueError("la ruta contiene índices duplicados o fuera de rango")
    if require_complete and set(normalized) != set(range(size)):
        raise ValueError("la ruta debe visitar cada ciudad exactamente una vez")
    return normalized


def _policy(value: str) -> str:
    if value not in TwoOpt.POLICIES:
        raise ValueError("policy debe ser 'first_improvement' o 'best_improvement'")
    return value
