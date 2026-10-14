import numpy as np
import pytest

from experiments.animate import _frames_idx, main, run_animated
from src.result import check_result


@pytest.mark.parametrize("metodo,hp", [("de", {"population_size": 10}), ("pso", {"n_particles": 10})])
def test_record_population_no_cambia_la_corrida(metodo, hp):
    p1, r1 = run_animated(metodo, "rastrigin", 0, 200, 1.0, hp)
    from src.counter import CountedProblem
    from src.functions import make
    from src.methods import METHODS
    p2 = CountedProblem(make("rastrigin", 2))
    r2 = METHODS[metodo](p2, 0, 200, 1.0, **hp)
    assert r1.history_f == r2.history_f and np.array_equal(r1.best_x, r2.best_x)
    check_result(r1, p1, 200)
    assert len(r1.history_pop) == len(r1.history_f)
    assert r1.history_pop[0].shape == (10, 2)
    assert r2.history_pop == []


def test_frames_idx_limita_cuadros():
    assert len(_frames_idx(10, 60)) == 10
    idx = _frames_idx(500, 60)
    assert len(idx) <= 60 and idx[0] == 0 and idx[-1] == 499


def test_animate_escribe_gifs(tmp_path):
    main(["--config", "configs/anim.yaml", "--figures", str(tmp_path),
          "--set", "presupuesto=200", "--set", "max_cuadros=5", "--set", "funciones=[rastrigin]"])
    nombres = sorted(f.name for f in tmp_path.glob("*.gif"))
    assert nombres == ["anim_de_rastrigin.gif", "anim_ea_rastrigin.gif",
                       "anim_gd_rastrigin.gif", "anim_pso_rastrigin.gif"]
