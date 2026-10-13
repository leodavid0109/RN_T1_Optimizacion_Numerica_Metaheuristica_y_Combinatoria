"""Modelo y contratos comunes para la Parte 2 (TSP)."""

from .cities import City, load_city_catalog, validate_city_catalog
from .alternatives import RouteAlternative, TollStatus, remove_dominated_alternatives
from .contracts import ConvergencePoint, TSPAlgorithm, TSPObjective, TSPRunResult
from .evaluation import EvaluationBudgetExceeded, RunEvaluator
from .models import AlternativeTSPProblem, SelectedAlternative, UnverifiableCostError
from .problem import RouteCost, TSPProblem
from .aco import AntSystem
from .baselines import NearestNeighbor, NearestNeighborTwoOpt, TwoOpt
from .exact import ExactTSPResult, MAX_EXACT_CITIES, solve_exact_small

__all__ = [
    "City",
    "AlternativeTSPProblem",
    "AntSystem",
    "ExactTSPResult",
    "ConvergencePoint",
    "EvaluationBudgetExceeded",
    "RouteCost",
    "RouteAlternative",
    "RunEvaluator",
    "TSPAlgorithm",
    "TSPObjective",
    "TSPProblem",
    "TSPRunResult",
    "NearestNeighbor",
    "NearestNeighborTwoOpt",
    "TwoOpt",
    "MAX_EXACT_CITIES",
    "load_city_catalog",
    "remove_dominated_alternatives",
    "SelectedAlternative",
    "TollStatus",
    "UnverifiableCostError",
    "validate_city_catalog",
    "solve_exact_small",
]
