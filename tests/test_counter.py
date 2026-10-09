import numpy as np

from src.counter import CountedProblem
from src.functions import Rosenbrock


def test_cuenta_f_y_grad_por_separado():
    p = CountedProblem(Rosenbrock(2))
    p.f(np.zeros(2)); p.f(np.ones(2)); p.grad(np.zeros(2))
    assert (p.f_evals, p.grad_evals) == (2, 1)


def test_lote_cuenta_un_f_por_punto():
    p = CountedProblem(Rosenbrock(3))
    p.f(np.zeros((7, 3)))
    assert p.f_evals == 7


def test_gradiente_numerico_cuesta_2n():
    for n in (2, 3):
        p = CountedProblem(Rosenbrock(n))
        p.grad_numeric(np.full(n, 0.5))
        assert p.f_evals == 2 * n and p.grad_evals == 0


def test_equivalentes_y_reset():
    p = CountedProblem(Rosenbrock(2))
    p.f(np.zeros(2)); p.grad(np.zeros(2)); p.grad(np.zeros(2))
    assert p.equivalent_evals(1) == 3
    assert p.equivalent_evals(3) == 7
    p.reset()
    assert (p.f_evals, p.grad_evals) == (0, 0)
