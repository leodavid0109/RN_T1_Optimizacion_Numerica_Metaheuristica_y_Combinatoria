"""Barrido de hiperparámetros del GA del TSP (un valor de la hora, misma matriz y presupuesto).

Uso (desde la raíz del repositorio):
    python -m experiments.tsp_ga_sweep --config configs/tsp_ga_sweep.yaml
    python -m experiments.tsp_ga_sweep --set n_runs=3 --set presupuesto=5000 --set modo=grilla

Modos: `uno_a_uno` (un hiperparámetro a la vez alrededor de la base) o `grilla` (producto cartesiano).
Salidas en `salidas.resultados`: corridas.csv y resumen.csv (ordenado por costo medio).
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import pandas as pd

from src.config import load_config
from src.tsp import GeneticAlgorithm
from src.tsp.economic_dataset import load_economic_problem


def configuraciones(base: dict, barrido: dict, modo: str) -> list[dict]:
    """Hiperparámetros completos (base + variaciones) de cada configuración a probar."""
    if modo == "uno_a_uno":
        variaciones = [{}]
        for param, valores in barrido.items():
            variaciones += [{param: v} for v in valores if v != base.get(param)]
    elif modo == "grilla":
        claves = list(barrido)
        variaciones = [dict(zip(claves, combo)) for combo in itertools.product(*(barrido[k] for k in claves))]
    else:
        raise ValueError(f"modo desconocido {modo!r}: use 'uno_a_uno' o 'grilla'")
    return [{**base, **v} for v in variaciones]


def run_sweep(cfg: dict, results_dir: Path) -> pd.DataFrame:
    results_dir.mkdir(parents=True, exist_ok=True)
    problem = load_economic_problem(cfg["dataset"], float(cfg["valor_hora"]), include_tolls=bool(cfg.get("incluir_peajes", True)))
    s0 = int(cfg.get("semilla_base", 1000))
    rows = []
    for hp in configuraciones(dict(cfg["ga"]), dict(cfg["barrido"]), cfg.get("modo", "uno_a_uno")):
        for seed in range(s0, s0 + int(cfg["n_runs"])):
            r = GeneticAlgorithm().run(problem, seed, int(cfg["presupuesto"]), **hp)
            rows.append({**{f"hp_{k}": v for k, v in hp.items()}, "seed": seed, "costo_eur": r.best_cost_eur})
    runs = pd.DataFrame(rows)
    runs.to_csv(results_dir / "corridas.csv", index=False)
    cols = [c for c in runs.columns if c.startswith("hp_")]
    summary = (runs.groupby(cols, sort=False, dropna=False)["costo_eur"]
               .agg(media="mean", desviacion="std", mediana="median", mejor="min", peor="max").reset_index()
               .sort_values("media"))
    summary.to_csv(results_dir / "resumen.csv", index=False)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/tsp_ga_sweep.yaml")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.set)
    out = a.results or cfg.get("salidas", {}).get("resultados", "results/tsp_ga_sweep")
    summary = run_sweep(cfg, Path(out))
    pd.set_option("display.width", 220, "display.max_columns", 30)
    print("Configuraciones ordenadas por costo medio (menor es mejor):")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nResultados en {out}/")


if __name__ == "__main__":
    main()
