"""Contrato de resultados e interfaz que compartirán ACO y GA."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral
from typing import Protocol, Sequence

from .problem import RouteCost, TSPProblem


@dataclass(frozen=True)
class ConvergencePoint:
    """Mejor costo conocido después de este número de evaluaciones completas."""

    evaluations: int
    best_cost_eur: float

    def __post_init__(self) -> None:
        if not isinstance(self.evaluations, Integral) or self.evaluations < 1:
            raise ValueError("evaluations debe ser un entero positivo")
        if not isfinite(self.best_cost_eur) or self.best_cost_eur < 0:
            raise ValueError("best_cost_eur debe ser finito y no negativo")


@dataclass(frozen=True)
class TSPRunResult:
    """Resultado común de una corrida de un algoritmo TSP."""

    best_route: tuple[int, ...]
    best_cost_eur: float
    best_breakdown: RouteCost
    history: tuple[ConvergencePoint, ...]
    objective_evaluations: int
    seed: int
    stop_reason: str

    def __post_init__(self) -> None:
        if not self.best_route or len(set(self.best_route)) != len(self.best_route):
            raise ValueError("best_route debe ser una permutación no vacía")
        if not isfinite(self.best_cost_eur) or self.best_cost_eur < 0:
            raise ValueError("best_cost_eur debe ser finito y no negativo")
        if not isinstance(self.objective_evaluations, Integral) or self.objective_evaluations < 1:
            raise ValueError("objective_evaluations debe ser un entero positivo")
        if not isinstance(self.seed, Integral) or isinstance(self.seed, bool):
            raise ValueError("seed debe ser entero")
        if not self.stop_reason:
            raise ValueError("stop_reason no puede estar vacío")
        if not self.history:
            raise ValueError("history debe registrar al menos una evaluación")
        counts = [point.evaluations for point in self.history]
        costs = [point.best_cost_eur for point in self.history]
        if counts != sorted(set(counts)):
            raise ValueError("el historial debe ordenar evaluaciones crecientes y únicas")
        if any(next_cost > cost for cost, next_cost in zip(costs, costs[1:])):
            raise ValueError("el mejor costo del historial no puede aumentar")
        if counts[-1] > self.objective_evaluations:
            raise ValueError("el historial supera el contador de evaluaciones")
        if abs(costs[-1] - self.best_cost_eur) > 1e-9:
            raise ValueError("el último costo del historial debe coincidir con best_cost_eur")
        if abs(self.best_breakdown.total_cost_eur - self.best_cost_eur) > 1e-9:
            raise ValueError("best_breakdown y best_cost_eur no coinciden")


class TSPAlgorithm(Protocol):
    """Interfaz común que implementarán ACO, GA y futuros baselines."""

    def run(
        self,
        problem: TSPProblem,
        seed: int,
        budget: int,
        **params,
    ) -> TSPRunResult:
        """Optimiza una misma instancia hasta el presupuesto de rutas completas."""
        ...
