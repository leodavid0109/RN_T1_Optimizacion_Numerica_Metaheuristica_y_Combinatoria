"""Contador aislado por corrida para presupuestar evaluaciones completas de rutas."""

from __future__ import annotations

from numbers import Integral
from typing import Sequence

from .contracts import ConvergencePoint, TSPObjective, TSPRunResult
from .problem import RouteCost


class EvaluationBudgetExceeded(RuntimeError):
    """Se intentó evaluar una ruta completa después de agotar el presupuesto."""


class RunEvaluator:
    """Evalúa rutas completas y mantiene el contador/historial de una sola corrida.

    Los algoritmos deben usar este wrapper para puntuar candidatos completos.
    Los cálculos de arcos y rutas parciales se hacen fuera de él y no consumen el
    presupuesto, que mide únicamente llamadas completas a la función objetivo.
    """

    def __init__(self, problem: TSPObjective, budget: int) -> None:
        if not isinstance(budget, Integral) or isinstance(budget, bool) or budget < 1:
            raise ValueError("budget debe ser un entero positivo de evaluaciones completas")
        self.problem = problem
        self.budget = int(budget)
        self.objective_evaluations = 0
        self.best_route: tuple[int, ...] | None = None
        self.best_breakdown: RouteCost | None = None
        self.history: list[ConvergencePoint] = []

    def evaluate(self, route: Sequence[int]) -> RouteCost:
        """Evalúa una ruta válida; intentos tras el límite se rechazan sin contar."""
        if self.objective_evaluations >= self.budget:
            raise EvaluationBudgetExceeded("se agotó el presupuesto de evaluaciones completas")
        breakdown = self.problem.evaluate_route(route)
        self.objective_evaluations += 1
        if self.best_breakdown is None or breakdown.total_cost_eur < self.best_breakdown.total_cost_eur:
            self.best_route = breakdown.closed_route[:-1]
            self.best_breakdown = breakdown
            self.history.append(ConvergencePoint(self.objective_evaluations, breakdown.total_cost_eur))
        return breakdown

    def finish(self, seed: int, stop_reason: str) -> TSPRunResult:
        """Construye el resultado contractual con los datos acumulados por el wrapper."""
        if self.best_route is None or self.best_breakdown is None:
            raise ValueError("no se puede finalizar una corrida sin evaluar una ruta completa")
        return TSPRunResult(
            best_route=self.best_route,
            best_cost_eur=self.best_breakdown.total_cost_eur,
            best_breakdown=self.best_breakdown,
            history=tuple(self.history),
            objective_evaluations=self.objective_evaluations,
            seed=seed,
            stop_reason=stop_reason,
        )
