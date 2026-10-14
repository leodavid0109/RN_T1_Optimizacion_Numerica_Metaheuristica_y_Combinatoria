import numpy as np
import pytest

from src.tsp.economic_dataset import (DEFAULT_DATASET, PUBLISHED_HOUR_VALUES, load_economic_problem,
                                      load_published_matrix)


@pytest.mark.parametrize("hour_value", PUBLISHED_HOUR_VALUES)
def test_los_componentes_reproducen_las_matrices_publicadas(hour_value):
    problem = load_economic_problem(hour_value=hour_value)
    ids = [city.city_id for city in problem.cities]
    published = load_published_matrix(f"{DEFAULT_DATASET}/model_a_v{hour_value}_eur.csv", ids)
    assert np.allclose(problem.cost_matrix_for_hour(hour_value), published, atol=1e-6)
    assert np.allclose(np.diag(published), 0.0)


def test_cualquier_valor_de_hora_se_reconstruye_con_los_mismos_componentes():
    a, b = load_economic_problem(hour_value=25.0), load_economic_problem(hour_value=40.0)
    expected = a.cost_matrix_for_hour(25.0) + 15.0 * a.time_hours
    assert np.allclose(b.cost_matrix_for_hour(40.0), expected)


def test_baseline_sin_peajes_no_tiene_peajes_y_lo_declara():
    problem = load_economic_problem(hour_value=25.0, include_tolls=False)
    assert float(problem.toll_cost_eur.sum()) == 0.0 and "SIN PEAJES" in problem.scope


def test_evaluar_una_ruta_suma_los_arcos_publicados_incluido_el_cierre():
    problem = load_economic_problem(hour_value=25.0)
    published = problem.cost_matrix_for_hour(25.0)
    route = tuple(range(47))
    cost = problem.evaluate_route(route)
    assert cost.total_cost_eur == pytest.approx(sum(published[a, b] for a, b in zip(route, route[1:] + route[:1])))
