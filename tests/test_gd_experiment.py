import pandas as pd

from experiments.gd_experiment import run_experiment

CFG = {
    "funciones": ["rosenbrock", "rastrigin"], "dimensiones": [2, 3], "n_runs": 4,
    "presupuesto": {2: 200, 3: 300}, "grad_cost": 1.0,
    "tasas_aprendizaje": {"rosenbrock": [1e-4, 5e-5], "rastrigin": [1e-3]},
    "umbrales_exito": [1e-4, 1e-2], "puntos_curva": 20,
}


def test_estructura_y_conteo(tmp_path):
    s = run_experiment(CFG, tmp_path)
    runs = pd.read_csv(tmp_path / "runs.csv")
    assert len(runs) == 4 * (2 + 1) * 2          # semillas x tasas x dimensiones
    assert set(runs.seed) == {0, 1, 2, 3}
    # el presupuesto se respeta con un margen de una iteración (2 evaluaciones equivalentes)
    assert (runs.equiv_evals <= runs.dim.map(CFG["presupuesto"]) + 2).all()
    assert s.seleccionada.sum() == 4              # una tasa elegida por (función, dim)
    assert {"media", "desv", "mejor", "peor", "tasa_exito_0.0001"} <= set(s.columns)


def test_reproducible(tmp_path):
    run_experiment(CFG, tmp_path / "a"); run_experiment(CFG, tmp_path / "b")
    a = pd.read_csv(tmp_path / "a" / "runs.csv"); b = pd.read_csv(tmp_path / "b" / "runs.csv")
    pd.testing.assert_frame_equal(a, b)


def test_figuras(tmp_path):
    run_experiment(CFG, tmp_path / "r", tmp_path / "f")
    names = {p.name for p in (tmp_path / "f").iterdir()}
    assert {"gd_convergencia.png", "gd_cajas.png", "gd_rosenbrock.gif", "gd_rastrigin.gif"} <= names
