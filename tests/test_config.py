import pandas as pd
import pytest

from experiments import gd_experiment
from src.config import apply_override, load_config


def test_cambios_desde_la_linea_de_comandos():
    cfg = {"n_runs": 30, "presupuesto": {2: 20000, 3: 40000}, "tasas_aprendizaje": {"rosenbrock": [1e-4]}}
    apply_override(cfg, "n_runs=5")
    apply_override(cfg, "presupuesto.2=500")            # la clave numérica sigue siendo int
    apply_override(cfg, "tasas_aprendizaje.rosenbrock=[0.0001, 0.0004]")
    apply_override(cfg, "metodos.gd.rastrigin.lr=0.003")  # crea las claves que faltan
    assert cfg["n_runs"] == 5
    assert cfg["presupuesto"] == {2: 500, 3: 40000}
    assert cfg["tasas_aprendizaje"]["rosenbrock"] == [1e-4, 4e-4]
    assert cfg["metodos"] == {"gd": {"rastrigin": {"lr": 0.003}}}


def test_cambio_sin_igual_es_un_error():
    with pytest.raises(ValueError):
        apply_override({}, "n_runs")


def test_demo_y_completa_no_comparten_carpetas():
    demo, full = load_config("configs/gd_demo.yaml"), load_config("configs/gd.yaml")
    assert demo["salidas"]["resultados"] != full["salidas"]["resultados"]
    assert demo["salidas"]["figuras"] != full["salidas"]["figuras"]
    cdemo, cfull = load_config("configs/compare_demo.yaml"), load_config("configs/compare.yaml")
    assert cdemo["salidas"]["resultados"] != cfull["salidas"]["resultados"]


def test_main_gd_con_set_y_carpeta_del_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "mini.yaml").write_text(
        "funciones: [rastrigin]\ndimensiones: [2]\nn_runs: 30\npresupuesto: {2: 2000}\n"
        "tasas_aprendizaje: {rastrigin: [0.003]}\numbrales_exito: [0.0001, 0.01]\n"
        "salidas: {resultados: salida/res, figuras: salida/fig}\n", encoding="utf-8")
    gd_experiment.main(["--config", "configs/mini.yaml", "--no-figures",
                        "--set", "n_runs=3", "--set", "presupuesto.2=100"])
    runs = pd.read_csv(tmp_path / "salida" / "res" / "runs.csv")
    assert len(runs) == 3 and (runs.equiv_evals <= 102).all()
