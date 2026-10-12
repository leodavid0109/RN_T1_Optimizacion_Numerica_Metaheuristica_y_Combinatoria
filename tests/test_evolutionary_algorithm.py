import numpy as np
import pytest

from src.counter import CountedProblem
from src.evolutionary_algorithm import run_ea
from src.functions import Rastrigin, Rosenbrock
from src.result import check_result


@pytest.mark.parametrize("fn", [Rosenbrock(2), Rastrigin(3)])
def test_ea_respeta_contrato_y_presupuesto(fn):
    problem = CountedProblem(fn)
    budget = 137
    result = run_ea(problem, seed=13, budget=budget, population_size=20)
    check_result(result, problem, budget, grad_cost=1.0)
    assert result.stop_reason == "budget"
    assert problem.f_evals <= budget
    assert problem.grad_evals == 0
    assert len(result.history_x) == len(result.history_f)


def test_ea_es_reproducible():
    a = run_ea(CountedProblem(Rosenbrock(2)), seed=4, budget=100, population_size=12)
    b = run_ea(CountedProblem(Rosenbrock(2)), seed=4, budget=100, population_size=12)
    assert np.array_equal(a.best_x, b.best_x)
    assert a.history_f == b.history_f
    assert a.history_evals == b.history_evals


def test_ea_mejora_o_conserva_el_mejor():
    result = run_ea(CountedProblem(Rastrigin(2)), seed=9, budget=200, population_size=20)
    assert all(b <= a for a, b in zip(result.history_f, result.history_f[1:]))


@pytest.mark.parametrize("kwargs", [
    {"population_size": 1},
    {"crossover_rate": 1.2},
    {"mutation_rate": -0.1},
    {"mutation_scale": -1},
    {"tournament_size": 0},
])
def test_ea_rechaza_hiperparametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        run_ea(CountedProblem(Rosenbrock(2)), seed=1, budget=20, **kwargs)
