"""Modelo y contratos comunes para la Parte 2 (TSP)."""

from .cities import City, load_city_catalog, validate_city_catalog
from .contracts import ConvergencePoint, TSPAlgorithm, TSPRunResult
from .evaluation import EvaluationBudgetExceeded, RunEvaluator
from .problem import RouteCost, TSPProblem

__all__ = [
    "City",
    "ConvergencePoint",
    "EvaluationBudgetExceeded",
    "RouteCost",
    "RunEvaluator",
    "TSPAlgorithm",
    "TSPProblem",
    "TSPRunResult",
    "load_city_catalog",
    "validate_city_catalog",
]
