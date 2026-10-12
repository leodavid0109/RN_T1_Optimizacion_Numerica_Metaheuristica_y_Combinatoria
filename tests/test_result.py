import numpy as np
import pytest

from src.counter import CountedProblem
from src.functions import make
from src.gradient_descent import RunResult as RunResultGD, run_gd
from src.methods import METHODS
from src.result import RunResult, check_result


@pytest.mark.parametrize("name", ["rosenbrock", "rastrigin"])
@pytest.mark.parametrize("n", [2, 3])
def test_gd_cumple_el_formato_comun(name, n):
    p = CountedProblem(make(name, n))
    r = run_gd(p, seed=7, budget=500, grad_cost=1.0, lr=1e-4)
    check_result(r, p, budget=500, grad_cost=1.0, slack=2)   # una iteración = 1 f + 1 grad


def test_runresult_se_reexporta_desde_gradient_descent():
    assert RunResultGD is RunResult


@pytest.mark.parametrize("nombre", sorted(METHODS))
def test_todos_los_metodos_registrados_cumplen_el_formato(nombre):
    p = CountedProblem(make("rastrigin", 2))
    r = METHODS[nombre](p, 0, 300, 1.0)
    # holgura: lo que cuesta una iteración o generación con los hiperparámetros por defecto
    check_result(r, p, budget=300, grad_cost=1.0, slack=100)


def test_check_result_detecta_contadores_inconsistentes():
    p = CountedProblem(make("rosenbrock", 2))
    r = run_gd(p, seed=0, budget=100, grad_cost=1.0, lr=1e-4)
    p.f(np.zeros(2))                       # una evaluación que el resultado no registró
    with pytest.raises(AssertionError, match="contadores"):
        check_result(r, p, budget=100, slack=2)


def test_check_result_detecta_historial_no_monotono():
    p = CountedProblem(make("rosenbrock", 2))
    r = run_gd(p, seed=0, budget=100, grad_cost=1.0, lr=1e-4)
    r.history_f = list(r.history_f) + [r.history_f[-1] + 1.0]
    r.history_evals = list(r.history_evals) + [r.history_evals[-1]]
    with pytest.raises(AssertionError, match="mejor valor acumulado"):
        check_result(r, p, budget=100, slack=2)
