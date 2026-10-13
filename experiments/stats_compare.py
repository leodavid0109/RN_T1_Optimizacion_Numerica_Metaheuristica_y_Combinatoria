"""Pruebas estadísticas sobre la comparación de la Parte 1 (lee results/compare/runs.csv).

- Mann-Whitney U bilateral (equivalente a la suma de rangos de Wilcoxon) entre cada par de
  métodos, sobre los 30 valores finales de f - f*, con corrección de Holm dentro de cada
  (función, dimensión): 6 pares por caso.
- Intervalo de confianza de Wilson al 95 % para la tasa de éxito de cada método.

Uso (desde la raíz del repositorio, después de experiments.compare):
    python -m experiments.stats_compare
    python -m experiments.stats_compare --resultados results/compare_demo

Salidas:
    <resultados>/pruebas.csv     una fila por (función, dimensión, par de métodos)
    <resultados>/ic_exito.csv    una fila por (método, función, dimensión, umbral)
"""
from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, norm


def wilson(k: int, n: int, nivel: float = 0.95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción k/n (no se sale de [0, 1] y sirve con k = 0)."""
    if n == 0:
        return 0.0, 1.0
    z = norm.ppf(0.5 + nivel / 2)
    p = k / n
    centro = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    radio = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centro - radio), min(1.0, centro + radio)


def holm(pvals: list[float]) -> list[float]:
    """p-valores ajustados por Holm (1979), en el mismo orden de entrada."""
    m = len(pvals)
    orden = np.argsort(pvals)
    ajust = np.empty(m)
    acum = 0.0
    for rango, i in enumerate(orden):
        acum = max(acum, min(1.0, (m - rango) * pvals[i]))
        ajust[i] = acum
    return ajust.tolist()


def pruebas(runs: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for (funcion, dim), caso in runs.groupby(["funcion", "dim"], sort=False):
        metodos = list(dict.fromkeys(caso["metodo"]))
        pares = list(combinations(metodos, 2))
        bloque = []
        for a, b in pares:
            xa = caso.loc[caso["metodo"] == a, "gap"].to_numpy()
            xb = caso.loc[caso["metodo"] == b, "gap"].to_numpy()
            if np.array_equal(np.sort(xa), np.sort(xb)):
                u, p = len(xa) * len(xb) / 2, 1.0  # muestras idénticas: la prueba no está definida
            else:
                u, p = mannwhitneyu(xa, xb, alternative="two-sided")
            bloque.append(dict(funcion=funcion, dim=dim, metodo_a=a, metodo_b=b,
                               mediana_a=np.median(xa), mediana_b=np.median(xb), U=float(u), p=float(p),
                               # probabilidad de que una corrida de a termine por debajo de una de b
                               prob_a_menor=float(1 - u / (len(xa) * len(xb)))))
        for fila, p_aj in zip(bloque, holm([f["p"] for f in bloque])):
            fila["p_holm"] = p_aj
            fila["significativa_0.05"] = p_aj < 0.05
        filas += bloque
    return pd.DataFrame(filas)


def intervalos(runs: pd.DataFrame) -> pd.DataFrame:
    filas = []
    columnas = [c for c in runs.columns if c.startswith("exito_")]
    for (metodo, funcion, dim), g in runs.groupby(["metodo", "funcion", "dim"], sort=False):
        for c in columnas:
            k, n = int(g[c].sum()), len(g)
            lo, hi = wilson(k, n)
            filas.append(dict(metodo=metodo, funcion=funcion, dim=dim, umbral=c.removeprefix("exito_"),
                              exitos=k, corridas=n, tasa=k / n, ic95_inf=lo, ic95_sup=hi))
    return pd.DataFrame(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resultados", default="results/compare")
    args = ap.parse_args()
    carpeta = Path(args.resultados)
    runs = pd.read_csv(carpeta / "runs.csv")
    pruebas(runs).to_csv(carpeta / "pruebas.csv", index=False)
    intervalos(runs).to_csv(carpeta / "ic_exito.csv", index=False)
    print("ok", carpeta / "pruebas.csv", carpeta / "ic_exito.csv")


if __name__ == "__main__":
    main()
