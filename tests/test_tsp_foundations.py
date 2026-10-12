"""Pruebas del núcleo TSP. Todos los datos de prueba son sintéticos salvo el catálogo."""

import numpy as np
import pytest

from src.tsp.cities import City, load_city_catalog, validate_city_catalog
from src.tsp.evaluation import EvaluationBudgetExceeded, RunEvaluator
from src.tsp.matrices import validate_matrix
from src.tsp.problem import TSPProblem


def synthetic_problem():
    """Instancia sintética de tres nodos; no representa distancias de España."""
    cities = [City(f"test-{i}", f"Ciudad {i}", f"Provincia {i}", 40.0, -3.0,
                   "synthetic://test-fixture", "2026-10-12", "verificada", "fixture sintético")
              for i in range(3)]
    distance = [[0, 10, 20], [11, 0, 30], [31, 12, 0]]
    time = [[0, 1, 2], [1.5, 0, 3], [0.5, 2.5, 0]]
    tolls = [[0, 2, 4], [3, 0, 5], [6, 7, 0]]
    fuel = [[0, 4, 8], [5, 0, 6], [7, 9, 0]]
    return TSPProblem(cities, distance, time, tolls, fuel, hour_value_eur_per_hour=8)


def test_catalogo_tiene_47_capitales_y_procedencia():
    cities = load_city_catalog()
    assert len(cities) == 47
    assert all(city.source_url and city.consulted_on == "2026-10-12" for city in cities)


def test_catalogo_no_tiene_identificadores_duplicados():
    cities = load_city_catalog()
    assert len({city.city_id for city in cities}) == 47


def test_catalogo_no_tiene_ciudades_duplicadas():
    cities = load_city_catalog()
    assert len({city.name.casefold() for city in cities}) == 47


def test_coordenadas_presentes_en_rango_y_pendientes_explicitas():
    cities = load_city_catalog()
    for city in cities:
        assert (city.latitude is None) == (city.longitude is None)
        if city.latitude is None:
            assert city.coordinate_status == "pendiente"
        else:
            assert -90 <= city.latitude <= 90
            assert -180 <= city.longitude <= 180
            assert city.coordinate_status == "verificada"


def test_catalogo_rechaza_latitud_o_longitud_incompleta():
    cities = list(load_city_catalog())
    # Mantener este caso independiente de que el catálogo real ya tenga ambas coordenadas.
    cities[0] = City(**{**cities[0].__dict__, "longitude": None})
    with pytest.raises(ValueError, match="incompletas"):
        validate_city_catalog(cities)


def test_catalogo_rechaza_coordenadas_fuera_de_rango():
    cities = list(load_city_catalog())
    cities[0] = City(**{**cities[0].__dict__, "latitude": 95.0, "longitude": -3.0,
                        "coordinate_status": "verificada"})
    with pytest.raises(ValueError, match="fuera de rango"):
        validate_city_catalog(cities)


def test_matrices_tienen_dimensiones_compatibles():
    problem = synthetic_problem()
    assert all(matrix.shape == (3, 3) for matrix in (
        problem.distance_km, problem.time_hours, problem.toll_cost_eur, problem.fuel_cost_eur
    ))
    with pytest.raises(ValueError, match="dimensión"):
        validate_matrix(np.zeros((2, 3)), 3, "distancias")


@pytest.mark.parametrize("bad", [
    [[0, -1], [1, 0]],
    [[0, float("nan")], [1, 0]],
    [[0, float("inf")], [1, 0]],
])
def test_matrices_rechazan_valores_negativos_o_no_finitos(bad):
    with pytest.raises(ValueError):
        validate_matrix(bad, 2, "matriz sintética")


def test_matrices_rechazan_diagonal_no_nula_sin_corregirla():
    with pytest.raises(ValueError, match="diagonal"):
        validate_matrix([[1, 2], [3, 0]], 2, "matriz sintética")


def test_permutacion_valida_visita_cada_ciudad_exactamente_una_vez():
    assert synthetic_problem().validate_route([2, 0, 1]) == (2, 0, 1)


@pytest.mark.parametrize("route", [[0, 1], [0, 1, 1], [0, 1, 3], [0, 1, 1.5]])
def test_permutacion_invalida_es_rechazada(route):
    with pytest.raises(ValueError):
        synthetic_problem().evaluate_route(route)


def test_recorrido_cerrado_incluye_regreso_al_origen():
    cost = synthetic_problem().evaluate_route([0, 1, 2])
    assert cost.closed_route == (0, 1, 2, 0)
    assert cost.total_distance_km == 71


def test_costo_sintetico_coincide_con_calculo_manual():
    cost = synthetic_problem().evaluate_route([0, 1, 2])
    # Arcos 0->1, 1->2, 2->0: tiempo 4.5 h; peajes 13 EUR; combustible 17 EUR.
    assert cost.total_time_hours == pytest.approx(4.5)
    assert cost.toll_cost_eur == pytest.approx(13)
    assert cost.fuel_cost_eur == pytest.approx(17)
    assert cost.seller_time_cost_eur == pytest.approx(36)
    assert cost.total_cost_eur == pytest.approx(66)


def test_modelo_admite_matrices_asimetricas():
    problem = synthetic_problem()
    assert problem.distance_km[0, 1] != problem.distance_km[1, 0]
    assert problem.evaluate_route([0, 1, 2]).total_distance_km != problem.evaluate_route([0, 2, 1]).total_distance_km


def test_cambiar_valor_hora_cambia_costo_sin_modificar_matrices():
    problem = synthetic_problem()
    distances_before = problem.distance_km.copy()
    base = problem.evaluate_route([0, 1, 2], hour_value_eur_per_hour=8)
    changed = problem.evaluate_route([0, 1, 2], hour_value_eur_per_hour=10)
    assert changed.total_cost_eur - base.total_cost_eur == pytest.approx(9)
    np.testing.assert_array_equal(problem.distance_km, distances_before)


def test_matrices_del_problema_son_inmutables():
    with pytest.raises(ValueError):
        synthetic_problem().distance_km[0, 1] = 99


def test_run_evaluator_cuenta_rutas_completas_y_guarda_mejoras_por_evaluacion():
    evaluator = RunEvaluator(synthetic_problem(), budget=3)
    evaluator.evaluate([0, 1, 2])
    evaluator.evaluate([0, 2, 1])
    result = evaluator.finish(seed=7, stop_reason="budget")
    assert result.objective_evaluations == 2
    assert [point.evaluations for point in result.history] == [1]
    assert result.history[-1].best_cost_eur == result.best_cost_eur


def test_run_evaluator_no_sobrepasa_el_presupuesto_y_no_cuenta_ruta_rechazada():
    evaluator = RunEvaluator(synthetic_problem(), budget=1)
    evaluator.evaluate([0, 1, 2])
    with pytest.raises(EvaluationBudgetExceeded):
        evaluator.evaluate([0, 2, 1])
    assert evaluator.objective_evaluations == 1


def test_run_evaluator_rechaza_presupuesto_no_positivo_o_no_entero():
    with pytest.raises(ValueError, match="entero positivo"):
        RunEvaluator(synthetic_problem(), budget=0)
    with pytest.raises(ValueError, match="entero positivo"):
        RunEvaluator(synthetic_problem(), budget=1.5)
