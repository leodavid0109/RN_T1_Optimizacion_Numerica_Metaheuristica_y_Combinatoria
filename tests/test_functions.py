import numpy as np
import pytest

from src.functions import Rastrigin, Rosenbrock


def central_diff(fn, x, h=1e-6):
    g = np.empty_like(x)
    for i in range(x.size):
        e = np.zeros_like(x)
        e[i] = h
        g[i] = (fn.f(x + e) - fn.f(x - e)) / (2 * h)
    return g


@pytest.mark.parametrize("cls", [Rosenbrock, Rastrigin])
@pytest.mark.parametrize("n", [2, 3])
def test_valor_en_el_optimo(cls, n):
    fn = cls(n)
    assert fn.f(fn.x_opt) == pytest.approx(fn.f_opt, abs=1e-12)


@pytest.mark.parametrize("cls", [Rosenbrock, Rastrigin])
@pytest.mark.parametrize("n", [2, 3])
def test_gradiente_cero_en_el_optimo(cls, n):
    fn = cls(n)
    assert np.allclose(fn.grad(fn.x_opt), 0.0, atol=1e-10)


@pytest.mark.parametrize("cls", [Rosenbrock, Rastrigin])
@pytest.mark.parametrize("n", [2, 3])
def test_gradiente_vs_diferencias_centrales(cls, n):
    fn = cls(n)
    rng = np.random.default_rng(123)
    lo, hi = fn.bounds
    for _ in range(20):
        x = rng.uniform(lo, hi)
        assert np.allclose(fn.grad(x), central_diff(fn, x), rtol=1e-5, atol=1e-4)


def test_rastrigin_valor_conocido():
    # f(1,1) = 20 + (1 - 10) + (1 - 10) = 2 con A = 10
    assert Rastrigin(2).f(np.array([1.0, 1.0])) == pytest.approx(2.0)


def test_rosenbrock_valor_conocido():
    # f(0,0) = 1 ; f(-1,1) = 4
    assert Rosenbrock(2).f(np.array([0.0, 0.0])) == pytest.approx(1.0)
    assert Rosenbrock(2).f(np.array([-1.0, 1.0])) == pytest.approx(4.0)


@pytest.mark.parametrize("cls", [Rosenbrock, Rastrigin])
def test_lote_igual_a_puntos_sueltos(cls):
    fn = cls(3)
    X = np.random.default_rng(0).uniform(*fn.bounds, size=(5, 3))
    assert np.allclose(fn.f(X), [fn.f(x) for x in X])
    assert np.allclose(fn.grad(X), [fn.grad(x) for x in X])
