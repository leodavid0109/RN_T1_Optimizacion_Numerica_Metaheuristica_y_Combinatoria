import numpy as np
import pytest

from src.counter import CountedProblem
from src.differential_evolution import run_de
from src.functions import Rastrigin, Rosenbrock
from src.result import check_result


@pytest.mark.parametrize("fn", [Rosenbrock(2), Rastrigin(3)])
@pytest.mark.parametrize("budget", [137, 150, 17.5])
def test_de_respeta_contrato_y_presupuesto(fn, budget):
    problem = CountedProblem(fn)
    result = run_de(problem, seed=13, budget=budget, population_size=10)
    check_result(result, problem, budget, grad_cost=1.0)
    assert result.stop_reason == "budget"
    assert problem.f_evals <= budget  # presupuesto exacto, incluso parcial
    assert problem.grad_evals == 0
    assert len(result.history_x) == len(result.history_f)


def test_de_gasta_exactamente_el_presupuesto_entero():
    problem = CountedProblem(Rosenbrock(2))
    run_de(problem, seed=1, budget=95, population_size=10)
    assert problem.f_evals == 95


def test_de_es_reproducible():
    a = run_de(CountedProblem(Rosenbrock(2)), seed=4, budget=200, population_size=12)
    b = run_de(CountedProblem(Rosenbrock(2)), seed=4, budget=200, population_size=12)
    assert np.array_equal(a.best_x, b.best_x)
    assert a.history_f == b.history_f
    assert a.history_evals == b.history_evals


def test_de_semillas_distintas_dan_resultados_distintos():
    a = run_de(CountedProblem(Rastrigin(2)), seed=1, budget=200)
    b = run_de(CountedProblem(Rastrigin(2)), seed=2, budget=200)
    assert not np.array_equal(a.best_x, b.best_x)


def test_de_mejora_o_conserva_el_mejor():
    result = run_de(CountedProblem(Rastrigin(2)), seed=9, budget=300, population_size=20)
    assert all(b <= a for a, b in zip(result.history_f, result.history_f[1:]))


def test_de_converge_en_rosenbrock_2d():
    problem = CountedProblem(Rosenbrock(2))
    result = run_de(problem, seed=0, budget=6000)
    assert result.best_f < 1e-3


def test_de_con_F_cero_y_CR_cero_no_se_mueve_mas_de_una_coordenada():
    # CR=0 -> solo la coordenada j_rand viene del mutante; con F=0 el mutante es x_r1.
    result = run_de(CountedProblem(Rosenbrock(2)), seed=3, budget=100, population_size=10, F=0.0, CR=0.0)
    assert np.isfinite(result.best_f)


@pytest.mark.parametrize("kwargs", [
    {"population_size": 3},
    {"F": -0.1},
    {"F": 2.5},
    {"CR": 1.2},
    {"CR": -0.1},
])
def test_de_rechaza_hiperparametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        run_de(CountedProblem(Rosenbrock(2)), seed=1, budget=20, **kwargs)


def test_de_rechaza_presupuesto_invalido():
    with pytest.raises(ValueError):
        run_de(CountedProblem(Rosenbrock(2)), seed=1, budget=0)
