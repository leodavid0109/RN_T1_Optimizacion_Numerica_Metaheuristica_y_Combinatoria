
import numpy as np
import pytest

from src.particle_swarm import run_pso
from src.result import RunResult


class DummyProblem:
    """Problema sencillo para probar PSO."""

    def __init__(self, n=2):
        self.n = n
        self.bounds = (-5.0, 5.0)
        self.f_evals = 0
        self.grad_evals = 0

    def f(self, x):
        x = np.asarray(x, dtype=float)
        self.f_evals += len(x)
        return np.sum(x**2, axis=-1)

    def equivalent_evals(self, grad_cost=1.0):
        return self.f_evals + grad_cost * self.grad_evals


def test_pso_devuelve_resultado_correcto():
    problem = DummyProblem()

    result = run_pso(
        problem, seed=42, budget=50, n_particles=10
    )

    assert isinstance(result, RunResult)
    assert result.best_x.shape == (problem.n,)
    assert np.isfinite(result.best_f)
    assert result.f_evals == 50
    assert result.grad_evals == 0


def test_pso_respeta_el_presupuesto():
    problem = DummyProblem()

    result = run_pso(
        problem, seed=42, budget=17, n_particles=5
    )

    assert result.f_evals == 17
    assert result.f_evals <= 17
    assert result.stop_reason == "budget"


def test_pso_es_reproducible():
    problem1 = DummyProblem()
    problem2 = DummyProblem()

    result1 = run_pso(
        problem1, seed=123, budget=50, n_particles=10
    )
    result2 = run_pso(
        problem2, seed=123, budget=50, n_particles=10
    )

    assert result1.best_f == result2.best_f
    np.testing.assert_array_equal(
        result1.best_x, result2.best_x
    )


def test_el_mejor_resultado_no_empeora():
    problem = DummyProblem()

    result = run_pso(
        problem, seed=42, budget=50, n_particles=10
    )

    history = np.asarray(result.history_f)

    assert len(history) > 0
    assert np.all(np.diff(history) <= 0)


def test_pso_rechaza_presupuesto_invalido():
    with pytest.raises(ValueError):
        run_pso(DummyProblem(), seed=42, budget=0)


def test_pso_rechaza_pocas_particulas():
    with pytest.raises(ValueError):
        run_pso(
            DummyProblem(),
            seed=42,
            budget=20,
            n_particles=1,
        )


def test_pso_rechaza_parametros_negativos():
    with pytest.raises(ValueError):
        run_pso(
            DummyProblem(),
            seed=42,
            budget=20,
            c1=-1,
        )
