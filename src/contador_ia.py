"""Envoltorio de función objetivo con contadores de evaluaciones separados."""
import numpy as np


class CountedObjective:
    """Envuelve una función objetivo f y cuenta evaluaciones de f y de gradiente.

    Parámetros
    ----------
    f : callable
        Si ``vectorized=False`` (por defecto): f(x) con x de forma (n,) -> escalar.
        Si ``vectorized=True``: f(X) con X de forma (m, n) -> array (m,).
    grad : callable, opcional
        Gradiente analítico con la misma convención que f
        ((n,) -> (n,)  o  (m, n) -> (m, n) si vectorized). Si es None se usa
        el gradiente numérico por diferencias centrales.
    vectorized : bool
        Indica si f (y grad) aceptan lotes directamente. Si es False, los
        lotes se evalúan punto por punto.
    h : float o None
        Paso del gradiente numérico. None -> h_i = eps**(1/3) * max(1, |x_i|)
        (relativo). Un float -> paso absoluto constante.

    Contadores
    ----------
    n_f       : evaluaciones de f pedidas directamente (un lote de m suma m).
    n_grad    : evaluaciones de gradiente (un lote de m suma m).
    n_f_grad  : evaluaciones de f consumidas internamente por el gradiente
                numérico (2*n por punto). Con gradiente analítico se queda en 0.
    n_f_total : n_f + n_f_grad (costo real en llamadas a f).
    """

    def __init__(self, f, grad=None, vectorized=False, h=None):
        self._f = f
        self._grad = grad
        self.vectorized = bool(vectorized)
        self.h = h
        self.reset()

    # ------------------------------------------------------------------ util
    def reset(self):
        self.n_f = 0
        self.n_grad = 0
        self.n_f_grad = 0

    @property
    def n_f_total(self):
        return self.n_f + self.n_f_grad

    @staticmethod
    def _as_batch(x):
        X = np.asarray(x, dtype=float)
        if X.ndim == 1:
            return X[None, :], True
        if X.ndim == 2:
            return X, False
        raise ValueError(f"x debe tener forma (n,) o (m, n); recibí {X.shape}")

    def _raw_f(self, X):
        """Evalúa f sobre un lote (k, n) -> (k,) SIN contar."""
        if self.vectorized:
            y = np.asarray(self._f(X), dtype=float)
            if y.shape != (X.shape[0],):
                raise ValueError(
                    f"f vectorizada debe devolver forma {(X.shape[0],)}; "
                    f"devolvió {y.shape}"
                )
            return y
        return np.array([float(self._f(x)) for x in X], dtype=float)

    # ------------------------------------------------------------------- API
    def f(self, x):
        """Evalúa f en un punto (n,) -> float, o en un lote (m, n) -> (m,)."""
        X, single = self._as_batch(x)
        y = self._raw_f(X)
        self.n_f += X.shape[0]
        return float(y[0]) if single else y

    __call__ = f

    def grad(self, x):
        """Gradiente en un punto (n,) -> (n,), o en un lote (m, n) -> (m, n)."""
        X, single = self._as_batch(x)
        m, n = X.shape
        if self._grad is not None:
            g = self._analytic_grad(X)
        else:
            g = self._central_diff_grad(X)
        self.n_grad += m
        return g[0] if single else g

    # ------------------------------------------------------------- internals
    def _analytic_grad(self, X):
        m, n = X.shape
        if self.vectorized:
            g = np.asarray(self._grad(X), dtype=float)
        else:
            g = np.array([np.asarray(self._grad(x), dtype=float) for x in X])
            g = g.reshape(m, n)
        if g.shape != (m, n):
            raise ValueError(f"grad debe devolver forma {(m, n)}; devolvió {g.shape}")
        return g

    def _central_diff_grad(self, X):
        """Diferencias centrales: g_i = (f(x + h_i e_i) - f(x - h_i e_i)) / (2 h_i).

        Cuesta 2*n evaluaciones de f por punto. Construye los 2*m*n puntos
        perturbados de una vez (memoria O(m * n^2)), útil si f está vectorizada.
        """
        m, n = X.shape
        if m == 0:
            return np.empty((0, n))
        if self.h is None:
            H = np.cbrt(np.finfo(float).eps) * np.maximum(1.0, np.abs(X))  # (m, n)
        else:
            H = np.full((m, n), float(self.h))

        idx = np.arange(n)
        plus = np.repeat(X[:, None, :], n, axis=1)   # (m, n, n)
        minus = plus.copy()
        plus[:, idx, idx] += H
        minus[:, idx, idx] -= H

        fp = self._raw_f(plus.reshape(-1, n)).reshape(m, n)
        fm = self._raw_f(minus.reshape(-1, n)).reshape(m, n)
        self.n_f_grad += 2 * m * n
        return (fp - fm) / (2.0 * H)

    def __repr__(self):
        return (f"CountedObjective(n_f={self.n_f}, n_grad={self.n_grad}, "
                f"n_f_grad={self.n_f_grad}, n_f_total={self.n_f_total})")


if __name__ == "__main__":
    A = 10.0

    def rastrigin(x):
        return A * x.size + np.sum(x**2 - A * np.cos(2 * np.pi * x))

    def rastrigin_grad(x):
        return 2 * x + 2 * np.pi * A * np.sin(2 * np.pi * x)

    obj = CountedObjective(rastrigin)                       # gradiente numérico
    obj_a = CountedObjective(rastrigin, rastrigin_grad)     # gradiente analítico

    p = np.array([1.0, 1.0])
    print("f(1,1)        =", obj.f(p))
    print("grad numérico =", obj.grad(p))
    print("grad analít.  =", obj_a.grad(p))

    lote = np.random.default_rng(0).uniform(-5.12, 5.12, size=(5, 3))
    obj.reset()
    obj.f(lote)
    obj.grad(lote)
    print(obj)   # esperado: n_f=5, n_grad=5, n_f_grad=2*5*3=30, n_f_total=35