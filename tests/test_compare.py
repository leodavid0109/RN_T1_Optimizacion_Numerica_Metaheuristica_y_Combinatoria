import pandas as pd
import pytest

from experiments.compare import run_comparison
from experiments.gd_experiment import run_experiment

CFG = {
    "funciones": ["rosenbrock", "rastrigin"], "dimensiones": [2, 3], "n_runs": 4,
    "presupuesto": {2: 200, 3: 300}, "grad_cost": 1.0,
    "umbrales_exito": [1e-4, 1e-2], "puntos_curva": 20,
    "metodos": {"gd": {"rosenbrock": {"lr": 1e-4}, "rastrigin": {"lr": 1e-3}}},
}


def test_estructura(tmp_path):
    s = run_comparison(CFG, tmp_path)
    runs = pd.read_csv(tmp_path / "runs.csv")
    assert len(runs) == 1 * 2 * 2 * 4               # métodos x funciones x dimensiones x semillas
    assert len(s) == 1 * 2 * 2
    assert {"metodo", "media", "desv", "mejor", "peor", "evals_f_medias", "evals_grad_medias",
            "evals_equiv_medias", "evals_equiv_2n_medias", "tasa_exito_0.0001"} <= set(s.columns)


def test_gd_coincide_con_su_experimento(tmp_path):
    """La comparación debe dar exactamente lo mismo que el experimento propio del método."""
    run_comparison(CFG, tmp_path / "c")
    run_experiment({**CFG, "tasas_aprendizaje": {"rosenbrock": [1e-4], "rastrigin": [1e-3]}}, tmp_path / "g")
    c = pd.read_csv(tmp_path / "c" / "runs.csv").drop(columns="metodo")
    g = pd.read_csv(tmp_path / "g" / "runs.csv").drop(columns="lr")
    pd.testing.assert_frame_equal(c[g.columns], g)


def test_reproducible(tmp_path):
    run_comparison(CFG, tmp_path / "a"); run_comparison(CFG, tmp_path / "b")
    pd.testing.assert_frame_equal(pd.read_csv(tmp_path / "a" / "runs.csv"), pd.read_csv(tmp_path / "b" / "runs.csv"))


def test_metodo_sin_registrar_da_error_claro(tmp_path):
    with pytest.raises(ValueError, match="pso"):
        run_comparison({**CFG, "metodos": {**CFG["metodos"], "pso": {}}}, tmp_path)


def test_figuras(tmp_path):
    run_comparison(CFG, tmp_path / "r", tmp_path / "f")
    assert {"compare_convergencia.png", "compare_cajas.png"} <= {p.name for p in (tmp_path / "f").iterdir()}
