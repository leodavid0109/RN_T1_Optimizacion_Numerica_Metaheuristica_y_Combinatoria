"""Pruebas del contador generado por IA (src/contador_ia.py).

Verifican, contra el comportamiento esperado, lo que la IA dijo que hacía.
Las escribió Claude: añade al menos una prueba tuya antes de dar la verificación por cerrada.
"""
import numpy as np
import pytest

from src.contador_ia import CountedObjective
from src.functions import Rastrigin, Rosenbrock


def mk(fn, analitico=True, vectorizada=True, h=None):
    return CountedObjective(fn.f, fn.grad if analitico else None,
                            vectorized=vectorizada, h=h)


# --- conteo básico ---------------------------------------------------------
def test_cuenta_f_y_grad_por_separado():
    o = mk(Rosenbrock(2))
    o.f(np.zeros(2)); o.f(np.ones(2)); o.grad(np.zeros(2))
    assert (o.n_f, o.n_grad, o.n_f_grad) == (2, 1, 0)


def test_llamar_al_objeto_equivale_a_f():
    o = mk(Rosenbrock(2))
    o(np.zeros(2))
    assert o.n_f == 1


@pytest.mark.parametrize("vectorizada", [True, False])
def test_lote_de_7_cuenta_7_y_no_1(vectorizada):
    o = mk(Rosenbrock(3), vectorizada=vectorizada)
    o.f(np.zeros((7, 3)))
    assert o.n_f == 7


def test_gradiente_analitico_no_toca_n_f():
    o = mk(Rosenbrock(3))
    o.grad(np.zeros((4, 3)))
    assert (o.n_f, o.n_grad, o.n_f_grad) == (0, 4, 0)


# --- costo del gradiente numérico -----------------------------------------
@pytest.mark.parametrize("n", [2, 3, 5])
@pytest.mark.parametrize("vectorizada", [True, False])
def test_gradiente_numerico_cuesta_2n_por_punto(n, vectorizada):
    o = mk(Rosenbrock(n), analitico=False, vectorizada=vectorizada)
    o.grad(np.full(n, 0.5))
    assert o.n_f_grad == 2 * n
    assert o.n_f == 0 and o.n_grad == 1
    assert o.n_f_total == 2 * n


def test_gradiente_numerico_en_lote():
    o = mk(Rastrigin(3), analitico=False)
    X = np.random.default_rng(0).uniform(-5.12, 5.12, size=(5, 3))
    o.f(X); o.grad(X)
    assert (o.n_f, o.n_grad, o.n_f_grad, o.n_f_total) == (5, 5, 30, 35)


# --- correctitud numérica --------------------------------------------------
@pytest.mark.parametrize("cls", [Rosenbrock, Rastrigin])
@pytest.mark.parametrize("vectorizada", [True, False])
def test_numerico_coincide_con_analitico(cls, vectorizada):
    fn = cls(3)
    a = mk(fn, True, vectorizada)
    b = mk(fn, False, vectorizada)
    X = np.random.default_rng(1).uniform(*fn.bounds, size=(10, 3))
    assert np.allclose(a.grad(X), b.grad(X), rtol=1e-5, atol=1e-4)


def test_numerico_con_paso_absoluto():
    fn = Rastrigin(2)
    g = mk(fn, analitico=False, h=1e-6).grad(np.array([1.0, 1.0]))
    assert np.allclose(g, [2.0, 2.0], atol=1e-4)


def test_valores_hechos_a_mano():
    # Rastrigin f(1,1) = 2 ; Rosenbrock grad(-1,1) = (-4, 0)
    assert mk(Rastrigin(2)).f(np.array([1.0, 1.0])) == pytest.approx(2.0)
    assert np.allclose(mk(Rosenbrock(2)).grad(np.array([-1.0, 1.0])), [-4.0, 0.0])


def test_numerico_no_modifica_el_punto_de_entrada():
    x = np.array([0.3, -0.7, 1.1])
    copia = x.copy()
    mk(Rosenbrock(3), analitico=False).grad(x)
    assert np.array_equal(x, copia)


# --- formas y casos borde --------------------------------------------------
def test_formas_de_salida():
    o = mk(Rosenbrock(2))
    assert np.isscalar(o.f(np.zeros(2))) and o.grad(np.zeros(2)).shape == (2,)
    assert o.f(np.zeros((4, 2))).shape == (4,) and o.grad(np.zeros((4, 2))).shape == (4, 2)


def test_forma_invalida_lanza_error():
    with pytest.raises(ValueError):
        mk(Rosenbrock(2)).f(np.zeros((2, 2, 2)))


def test_f_vectorizada_con_forma_incorrecta_lanza_error():
    o = CountedObjective(lambda X: 1.0, vectorized=True)   # no devuelve (m,)
    with pytest.raises(ValueError):
        o.f(np.zeros((3, 2)))


def test_lote_vacio_no_cuenta_ni_rompe():
    o = mk(Rastrigin(2), analitico=False)
    assert o.grad(np.empty((0, 2))).shape == (0, 2)
    assert (o.n_f, o.n_grad, o.n_f_grad) == (0, 0, 0)


def test_reset():
    o = mk(Rosenbrock(2), analitico=False)
    o.f(np.zeros(2)); o.grad(np.zeros(2)); o.reset()
    assert (o.n_f, o.n_grad, o.n_f_grad, o.n_f_total) == (0, 0, 0, 0)


def test_funcion_escalar_pura_sin_vectorizar():
    A = 10.0
    f = lambda x: A * x.size + np.sum(x**2 - A * np.cos(2 * np.pi * x))
    o = CountedObjective(f)
    assert o.f(np.array([1.0, 1.0])) == pytest.approx(2.0)
    assert np.allclose(o.grad(np.array([1.0, 1.0])), [2.0, 2.0], atol=1e-4)