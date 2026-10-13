"""Ant System (AS) para problemas TSP dirigidos y objetivos del contrato común."""

from __future__ import annotations

import random
from math import isfinite
from numbers import Integral
from typing import Sequence

import numpy as np

from .contracts import TSPObjective, TSPRunResult
from .evaluation import RunEvaluator


class AntSystem:
    """Implementación clásica de Ant System con feromonas dirigidas.

    Parámetros específicos de ``run``: ``n_ants``, ``alpha``, ``beta``, ``rho``,
    ``q`` y ``tau0``. No mantiene estado entre ejecuciones.
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
        n_ants = _positive_integer(params.pop("n_ants", 10), "n_ants")
        alpha = _nonnegative_finite(params.pop("alpha", 1.0), "alpha")
        beta = _nonnegative_finite(params.pop("beta", 2.0), "beta")
        rho = _positive_finite(params.pop("rho", 0.5), "rho")
        if rho > 1.0:
            raise ValueError("rho debe cumplir 0 < rho <= 1")
        q = _positive_finite(params.pop("q", 1.0), "q")
        tau0 = _positive_finite(params.pop("tau0", 1.0), "tau0")
        if params:
            raise TypeError(f"parámetros ACO desconocidos: {', '.join(sorted(params))}")

        size = problem.size
        if isinstance(size, (bool, np.bool_)) or not isinstance(size, Integral) or size < 2:
            raise ValueError("problem.size debe ser un entero de al menos dos ciudades")
        costs = np.asarray(problem.cost_matrix_eur, dtype=float)
        if costs.shape != (size, size):
            raise ValueError(f"cost_matrix_eur debe tener dimensión {(size, size)}")
        if not np.all(np.isfinite(costs)) or np.any(costs < 0):
            raise ValueError("la matriz de costos debe contener valores finitos y no negativos")
        if float(np.max(costs)) > np.finfo(float).max / int(size):
            raise ValueError("la matriz permite ciclos cuyo costo podría desbordar float64")
        if not np.allclose(np.diag(costs), 0.0, rtol=0.0, atol=1e-12):
            raise ValueError("la diagonal de la matriz de costos debe ser cero")

        evaluator = RunEvaluator(problem, budget)
        rng = random.Random(int(seed))
        cap = np.finfo(float).max / 4.0
        floor = np.finfo(float).tiny
        pheromones = np.full((size, size), min(max(tau0, floor), cap), dtype=float)
        np.fill_diagonal(pheromones, floor)

        while evaluator.objective_evaluations < evaluator.budget:
            remaining = evaluator.budget - evaluator.objective_evaluations
            colony_size = min(n_ants, remaining)
            colony: list[tuple[tuple[int, ...], float]] = []

            for _ in range(colony_size):
                route = self._construct_route(costs, pheromones, rng, alpha, beta)
                # Una ruta se evalúa inmediatamente; no se construyen candidatos
                # sobrantes que pudieran quedar fuera del presupuesto.
                breakdown = evaluator.evaluate(route)
                colony.append((breakdown.closed_route, breakdown.total_cost_eur))

            pheromones = self._update_pheromones(pheromones, colony, rho, q)

        return evaluator.finish(int(seed), stop_reason="presupuesto_agotado")

    @staticmethod
    def _construct_route(
        costs: np.ndarray,
        pheromones: np.ndarray,
        rng: random.Random,
        alpha: float,
        beta: float,
    ) -> tuple[int, ...]:
        size = costs.shape[0]
        start = rng.randrange(size)
        route = [start]
        unvisited = set(range(size))
        unvisited.remove(start)

        while unvisited:
            current = route[-1]
            candidates = sorted(unvisited)
            probabilities = AntSystem._transition_probabilities(
                pheromones[current], costs[current], candidates, alpha, beta
            )
            selected_position = _weighted_choice(probabilities, rng)
            selected = candidates[selected_position]
            route.append(selected)
            unvisited.remove(selected)
        return tuple(route)

    @staticmethod
    def _transition_probabilities(
        pheromone_row: Sequence[float],
        cost_row: Sequence[float],
        candidates: Sequence[int],
        alpha: float,
        beta: float,
    ) -> np.ndarray:
        """Normaliza pesos en espacio logarítmico para evitar overflow/underflow.

        Si ``beta > 0`` y hay arcos de costo cero, el límite de ``1/costo`` hace
        que solo esos arcos tengan probabilidad positiva; entre ellos decide la
        feromona. Con ``beta == 0`` la heurística se ignora por definición.
        """
        if not candidates:
            raise ValueError("se requiere al menos un destino candidato")
        tau = np.asarray([pheromone_row[index] for index in candidates], dtype=float)
        arc_cost = np.asarray([cost_row[index] for index in candidates], dtype=float)
        if (not np.all(np.isfinite(tau)) or np.any(tau <= 0)
                or not np.all(np.isfinite(arc_cost)) or np.any(arc_cost < 0)):
            raise ValueError("feromonas y costos candidatos deben ser válidos")

        log_tau = np.log(tau)
        if beta > 0 and np.any(arc_cost == 0):
            eligible = arc_cost == 0
            return _weighted_log_probabilities(
                log_tau[eligible], np.zeros(int(eligible.sum())), alpha, 0.0,
                len(candidates), eligible,
            )

        log_eta = -np.log(arc_cost) if beta > 0 else np.zeros_like(arc_cost)
        return _weighted_log_probabilities(
            log_tau, log_eta, alpha, beta, len(candidates), None
        )

    @staticmethod
    def _update_pheromones(
        pheromones: np.ndarray,
        colony: Sequence[tuple[Sequence[int], float]],
        rho: float,
        q: float,
    ) -> np.ndarray:
        """Aplica evaporación y depósitos sobre arcos dirigidos, incluido el cierre."""
        size = pheromones.shape[0]
        cap = np.finfo(float).max / 4.0
        floor = np.finfo(float).tiny
        updated = np.asarray(pheromones, dtype=float).copy()
        updated *= 1.0 - rho
        np.maximum(updated, floor, out=updated)
        deposits = np.zeros_like(updated)
        per_edge_cap = cap / max(len(colony), 1)
        for closed_route, route_cost in colony:
            # El costo cero es válido en una instancia sintética; como Q/C
            # no está definido allí, se deposita Q como límite finito.
            if route_cost == 0.0:
                deposit = min(q, per_edge_cap)
            elif route_cost < q / per_edge_cap:
                deposit = per_edge_cap
            else:
                deposit = min(q / route_cost, per_edge_cap)
            for origin, destination in zip(closed_route[:-1], closed_route[1:]):
                current = deposits[origin, destination]
                deposits[origin, destination] = min(per_edge_cap, current + deposit)

        # Saturar antes de sumar evita desbordamientos con entradas extremas.
        for origin in range(size):
            for destination in range(size):
                addition = deposits[origin, destination]
                if addition and updated[origin, destination] >= cap - addition:
                    updated[origin, destination] = cap
                else:
                    updated[origin, destination] += addition
        np.maximum(updated, floor, out=updated)
        return updated


def _weighted_log_probabilities(
    log_tau: np.ndarray,
    log_eta: np.ndarray,
    alpha: float,
    beta: float,
    size: int,
    eligible: np.ndarray | None,
) -> np.ndarray:
    """Softmax ponderado que evita multiplicar parámetros extremos por logaritmos."""
    scale = max(alpha, beta)
    if scale == 0.0:
        logits = np.zeros_like(log_tau)
    else:
        # Separar la magnitud común conserva el orden matemático sin calcular
        # alpha*log(tau) directamente cuando alpha se acerca al máximo float.
        base = (alpha / scale) * log_tau + (beta / scale) * log_eta
        centered = base - np.max(base)
        threshold = (
            -np.inf if scale < 745.0 / np.finfo(float).max else -745.0 / scale
        )
        logits = np.full_like(centered, -np.inf)
        representable = centered >= threshold
        with np.errstate(under="ignore", over="ignore", invalid="ignore"):
            logits[representable] = centered[representable] * scale
    weights = np.exp(logits)
    denominator = float(weights.sum())
    if not isfinite(denominator) or denominator <= 0:
        # Salvaguarda para plataformas que redondeen todos los pesos a cero.
        winners = logits == np.max(logits)
        local = winners.astype(float) / int(winners.sum())
    else:
        local = weights / denominator
    probabilities = np.zeros(size, dtype=float)
    if eligible is None:
        probabilities[:] = local
    else:
        probabilities[eligible] = local
    # Corrige únicamente el error de redondeo de la suma sin cambiar el orden.
    probabilities /= probabilities.sum()
    return probabilities


def _weighted_choice(probabilities: np.ndarray, rng: random.Random) -> int:
    draw = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += float(probability)
        if draw < cumulative:
            return index
    return len(probabilities) - 1


def _positive_integer(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} debe ser un entero positivo")
    return int(value)


def _positive_finite(value, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} debe ser finito y positivo")
    return number


def _nonnegative_finite(value, name: str) -> float:
    number = _finite(value, name)
    if number < 0:
        raise ValueError(f"{name} debe ser finito y no negativo")
    return number


def _finite(value, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} debe ser numérico")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser numérico") from exc
    if not isfinite(number):
        raise ValueError(f"{name} debe ser finito")
    return number
