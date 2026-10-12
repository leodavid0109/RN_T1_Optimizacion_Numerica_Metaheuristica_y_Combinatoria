"""Formato común de los algoritmos de la Parte 1.

Todo método (descenso por gradiente, algoritmo evolutivo, PSO, evolución diferencial)
se expone como una función con esta firma:

    metodo(problem: CountedProblem, seed: int, budget: float, grad_cost: float, **hiperparametros) -> RunResult

  - `problem` cuenta las evaluaciones: el método solo llama a problem.f / problem.grad.
  - `seed` es la única fuente de aleatoriedad (np.random.default_rng(seed)); nada de estado global.
  - `budget` son evaluaciones equivalentes (f + grad_cost * grad); el método se detiene al agotarlo
    y puede pasarse a lo sumo por una iteración (o una generación).
  - Devuelve un RunResult con historiales monótonos: history_f[k] es el mejor f hasta el registro k
    y history_evals[k] las evaluaciones equivalentes acumuladas en ese momento.

`check_result` verifica ese contrato; los tests de cada método deberían llamarlo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class RunResult:
    best_x: np.ndarray
    best_f: float
    f_evals: int
    grad_evals: int
    history_f: list = field(default_factory=list)   # mejor f tras cada iteración
    history_x: list = field(default_factory=list)   # trayectoria o mejor individuo (para GIF)
    history_evals: list = field(default_factory=list)  # evaluaciones equivalentes acumuladas
    stop_reason: str = ""


def check_result(res: RunResult, problem, budget: float, grad_cost: float = 1.0, slack: float = 0.0) -> None:
    """Lanza AssertionError si `res` no cumple el formato común.

    `slack` es lo que el método puede pasarse del presupuesto (p. ej. el costo de una
    iteración o de una generación completa).
    """
    lo, hi = problem.bounds
    assert np.all(res.best_x >= lo) and np.all(res.best_x <= hi), "best_x fuera del dominio"
    assert np.isclose(float(problem.fn.f(res.best_x)), res.best_f), "best_f no corresponde a best_x"
    assert (res.f_evals, res.grad_evals) == (problem.f_evals, problem.grad_evals), \
        "los contadores del resultado no coinciden con los del problema"
    assert len(res.history_f) == len(res.history_evals) > 0, "historiales vacíos o de distinto largo"
    assert np.all(np.diff(res.history_f) <= 0), "history_f debe ser el mejor valor acumulado"
    assert np.all(np.diff(res.history_evals) >= 0), "history_evals debe ser no decreciente"
    assert np.isclose(res.history_f[-1], res.best_f), "el último registro debe ser best_f"
    assert problem.equivalent_evals(grad_cost) <= budget + slack, "se pasó del presupuesto"
