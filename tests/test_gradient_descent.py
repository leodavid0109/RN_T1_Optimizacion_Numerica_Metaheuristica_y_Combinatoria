import numpy as np

from src.counter import CountedProblem
from src.functions import Rastrigin, Rosenbrock
from src.gradient_descent import gradient_descent, initial_point


def run(fn, seed, **kw):
    p = CountedProblem(fn)
    return p, gradient_descent(p, initial_point(p, seed), **kw)


def test_reproducible_con_la_misma_semilla():
    _, a = run(Rosenbrock(2), 7, lr=1e-3, max_iters=500)
    _, b = run(Rosenbrock(2), 7, lr=1e-3, max_iters=500)
    assert np.array_equal(a.best_x, b.best_x) and a.history_f == b.history_f


def test_semillas_distintas_dan_puntos_distintos():
    p = CountedProblem(Rosenbrock(2))
    assert not np.array_equal(initial_point(p, 0), initial_point(p, 1))


def test_baja_f_en_rosenbrock():
    p, r = run(Rosenbrock(2), 0, lr=1e-3, max_iters=2000)
    assert r.best_f < r.history_f[0]
    assert all(b <= a + 1e-15 for a, b in zip(r.history_f, r.history_f[1:]))


def test_converge_en_paraboloide_local_de_rastrigin():
    fn = Rastrigin(2)
    p = CountedProblem(fn)
    # Hessiano en 0: 2 + 40*pi^2 ~ 397 -> el paso debe ser < 2/397 ~ 0.005
    r = gradient_descent(p, np.array([0.1, -0.1]), lr=1e-3, max_iters=2000)
    assert r.best_f < 1e-8


def test_paso_demasiado_grande_no_converge_en_rastrigin():
    p = CountedProblem(Rastrigin(2))
    r = gradient_descent(p, np.array([0.1, -0.1]), lr=1e-2, max_iters=2000)
    assert r.best_f > 1e-8


def test_respeta_el_dominio():
    fn = Rosenbrock(2)
    p = CountedProblem(fn)
    r = gradient_descent(p, np.array([9.9, 9.9]), lr=1e-2, max_iters=200)
    lo, hi = fn.bounds
    assert all(np.all(x >= lo) and np.all(x <= hi) for x in r.history_x)


def test_contador_coincide_con_iteraciones():
    p, r = run(Rosenbrock(2), 0, lr=1e-3, max_iters=100, grad_tol=0.0)
    # 1 f inicial + 100 iteraciones con 1 f y 1 grad cada una
    assert r.f_evals == 101 and r.grad_evals == 100


def test_presupuesto_se_respeta():
    p, r = run(Rosenbrock(2), 0, lr=1e-3, max_iters=10**6, budget=200, grad_tol=0.0)
    assert r.stop_reason == "budget"
    assert 200 <= p.equivalent_evals() <= 202


def test_grad_numerico_cuesta_2n_por_iteracion():
    p, r = run(Rosenbrock(2), 0, lr=1e-3, max_iters=10, grad_tol=0.0, numeric=True)
    assert r.grad_evals == 0
    assert r.f_evals == 1 + 10 * (1 + 2 * 2)
