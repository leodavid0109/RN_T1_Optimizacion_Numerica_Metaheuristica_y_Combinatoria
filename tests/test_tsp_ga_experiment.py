import pandas as pd

from experiments import tsp_ga_experiment, tsp_ga_sweep


def test_experimento_escribe_resultados_y_el_arrepentimiento_no_es_negativo(tmp_path):
    tsp_ga_experiment.main(["--config", "configs/tsp_ga_demo_exp.yaml", "--results", str(tmp_path / "r"),
                            "--figures", str(tmp_path / "f"), "--set", "n_runs=2", "--set", "presupuesto=300",
                            "--set", "valores_hora=[10,50]", "--set", "referencias=[nn]"])
    runs = pd.read_csv(tmp_path / "r" / "corridas.csv")
    assert set(runs.metodo) == {"GA", "nn"} and set(runs[runs.metodo == "GA"].seed) == {0, 1}
    assert (runs[runs.metodo == "GA"].evaluaciones == 300).all()
    cross = pd.read_csv(tmp_path / "r" / "cruzado.csv")
    assert (cross.arrepentimiento_eur >= -1e-9).all()
    assert (tmp_path / "r" / "alcance.txt").read_text(encoding="utf-8").startswith("MODELO A EXPERIMENTAL")
    assert (tmp_path / "f" / "convergencia.png").exists() and (tmp_path / "f" / "mejores_rutas.png").exists()


def test_barrido_ga_uno_a_uno(tmp_path):
    summary = tsp_ga_sweep.run_sweep(
        {"dataset": "data/datasets/spain_tsp_economic_20261013", "valor_hora": 25.0, "n_runs": 2,
         "semilla_base": 1000, "presupuesto": 200, "modo": "uno_a_uno",
         "ga": {"population_size": 20, "elite_size": 1}, "barrido": {"mutation_rate": [0.1, 0.5]}}, tmp_path)
    assert len(summary) == 3 and (tmp_path / "corridas.csv").exists()  # base + 2 valores (0.1 y 0.5)
