"""Pruebas de Ant System sobre objetivos sintéticos; no son datos de España."""

from itertools import permutations
import random

import numpy as np
import pytest

from src.tsp import (
    AlternativeTSPProblem,
    AntSystem,
    City,
    RouteAlternative,
    TollStatus,
    TSPProblem,
    UnverifiableCostError,
)


def cities(size):
    return tuple(
        City(f"test-{i}", f"Ciudad {i}", f"Provincia {i}", 40.0, -3.0,
             "synthetic://aco-test", "2026-10-12", "verificada", "fixture sintético")
        for i in range(size)
    )


def fixed_problem(costs):
    costs = np.asarray(costs, dtype=float)
    return TSPProblem(cities(len(costs)), np.zeros_like(costs), np.zeros_like(costs),
                      costs, np.zeros_like(costs), 0.0)


def alternative_problem(mode="economic"):
    city_list = cities(3)
    records = []
    for i in range(3):
        for j in range(3):
            if i == j:
                continue
            fast = f"fast-{i}-{j}"
            for alt_id, duration, toll in ((fast, 1.0, 2.0), (f"slow-{i}-{j}", 2.0, 0.0)):
                records.append(RouteAlternative(
                    origin_id=f"test-{i}", destination_id=f"test-{j}",
                    alternative_id=alt_id, fastest_route_id=fast, distance_km=10.0,
                    duration_hours=duration, toll_status=TollStatus.VERIFIED_WITH_TOLL if toll else
                    TollStatus.VERIFIED_WITHOUT_TOLL, toll_cost_eur=toll,
                    routing_engine="synthetic", routing_engine_version="1", profile="synthetic-car",
                    source="synthetic://route", acquired_on="2026-10-12",
                    toll_source="synthetic://tariff", toll_checked_on="2026-10-12",
                    fuel_consumption_l_per_100km=5.0, fuel_price_eur_per_l=1.0,
                    fuel_consumption_source="synthetic://consumption",
                    fuel_price_reference="synthetic://price", vehicle_configuration="synthetic vehicle",
                ))
    return AlternativeTSPProblem(city_list, records, 0.5, mode=mode)


def test_construye_permutaciones_validas_y_evalua_el_cierre():
    problem = fixed_problem([[0, 3], [5, 0]])
    result = AntSystem().run(problem, seed=5, budget=4, n_ants=3)
    assert sorted(result.best_route) == [0, 1]
    assert result.best_breakdown.closed_route == result.best_route + (result.best_route[0],)
    assert result.best_cost_eur == pytest.approx(8.0)


def test_aco_respeta_matriz_dirigida():
    problem = fixed_problem([[0, 1, 50], [40, 0, 1], [1, 60, 0]])
    result = AntSystem().run(problem, seed=21, budget=20, n_ants=4, beta=5)
    assert result.best_cost_eur == pytest.approx(problem.evaluate_route(result.best_route).total_cost_eur)
    assert result.best_breakdown.closed_route[-1] == result.best_route[0]
    assert problem.cost_matrix_eur[0, 1] != problem.cost_matrix_eur[1, 0]


def test_transiciones_se_normalizan_y_costos_cero_no_generan_nan():
    probs = AntSystem._transition_probabilities(
        [0.5, 2.0, 1.0], [0.0, 0.0, 1e-300], [0, 1, 2], alpha=1.0, beta=2.0
    )
    assert np.all(np.isfinite(probs))
    assert probs.sum() == pytest.approx(1.0)
    assert probs[2] == 0.0
    assert probs[1] > probs[0]


def test_transiciones_resisten_costos_y_feromonas_extremos():
    probs = AntSystem._transition_probabilities(
        [1e300, 1e-300, 3.0], [1e-300, 1e300, 2.0], [0, 1, 2], alpha=2.0, beta=2.0
    )
    assert np.all(np.isfinite(probs))
    assert np.all(probs >= 0)
    assert probs.sum() == pytest.approx(1.0)


def test_transiciones_resisten_exponentes_finitos_extremos():
    probs = AntSystem._transition_probabilities(
        [1e300, 1e-300], [1e-300, 1e300], [0, 1], alpha=1e308, beta=1e308
    )
    assert np.all(np.isfinite(probs))
    assert probs.sum() == pytest.approx(1.0)
    assert probs == pytest.approx([1.0, 0.0])


def test_rechaza_matriz_cuyo_costo_completo_podria_desbordar_float64():
    problem = fixed_problem([[0, 1e308], [1e308, 0]])
    with pytest.raises(ValueError, match="desbordar"):
        AntSystem().run(problem, seed=1, budget=1)


def test_presupuesto_exacto_e_iteracion_final_parcial():
    problem = fixed_problem([[0, 1, 4, 3], [4, 0, 1, 3], [3, 4, 0, 1], [1, 3, 4, 0]])
    result = AntSystem().run(problem, seed=13, budget=7, n_ants=3)
    assert result.objective_evaluations == 7
    assert result.stop_reason == "presupuesto_agotado"
    # Las convergencias se anotan solo cuando mejora el incumbente, con su
    # contador de evaluación real (no por iteración).
    assert result.history[-1].evaluations <= 7
    assert result.history[-1].best_cost_eur == result.best_cost_eur


def test_reproducibilidad_de_solucion_costo_y_historial():
    problem = fixed_problem([[0, 4, 2, 8], [3, 0, 5, 1], [8, 2, 0, 3], [1, 7, 4, 0]])
    first = AntSystem().run(problem, seed=991, budget=29, n_ants=6)
    second = AntSystem().run(problem, seed=991, budget=29, n_ants=6)
    assert (first.best_route, first.best_cost_eur, first.history, first.objective_evaluations) == (
        second.best_route, second.best_cost_eur, second.history, second.objective_evaluations
    )


def test_historial_tiene_costos_monotonicos_y_referencias_a_evaluaciones():
    problem = fixed_problem([[0, 9, 2, 8], [3, 0, 7, 1], [8, 2, 0, 3], [1, 7, 4, 0]])
    result = AntSystem().run(problem, seed=3, budget=20, n_ants=5)
    assert [point.evaluations for point in result.history] == sorted(
        {point.evaluations for point in result.history}
    )
    assert all(a.best_cost_eur >= b.best_cost_eur for a, b in zip(result.history, result.history[1:]))
    assert result.history[0].evaluations == 1


@pytest.mark.parametrize("params", [
    {"n_ants": 0}, {"n_ants": 1.5}, {"alpha": -1}, {"beta": float("inf")},
    {"rho": 0}, {"rho": 1.1}, {"q": 0}, {"tau0": -1}, {"unknown": 1},
])
def test_rechaza_parametros_invalidos(params):
    problem = fixed_problem([[0, 1], [1, 0]])
    with pytest.raises((ValueError, TypeError)):
        AntSystem().run(problem, seed=1, budget=2, **params)


def test_validacion_de_semilla_y_presupuesto():
    algorithm = AntSystem()
    problem = fixed_problem([[0, 1], [1, 0]])
    with pytest.raises(ValueError, match="seed"):
        algorithm.run(problem, seed=True, budget=2)
    with pytest.raises(ValueError, match="budget"):
        algorithm.run(problem, seed=1, budget=0)


def test_evaluacion_completa_se_cuenta_exactamente_una_vez_y_no_usa_rng_global():
    class CountingObjective:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def evaluate_route(self, route, hour_value_eur_per_hour=None):
            self.calls += 1
            return self.wrapped.evaluate_route(route, hour_value_eur_per_hour)

    problem = CountingObjective(fixed_problem([[0, 2, 3], [1, 0, 4], [5, 2, 0]]))
    state_before = random.getstate()
    result = AntSystem().run(problem, seed=88, budget=11, n_ants=4)
    assert problem.calls == result.objective_evaluations == 11
    assert random.getstate() == state_before


def test_evaporacion_deposito_dirigido_y_arco_de_regreso():
    pheromones = np.ones((3, 3), dtype=float)
    result = AntSystem._update_pheromones(pheromones, [((0, 1, 2, 0), 2.0)], rho=0.25, q=4.0)
    assert result[0, 1] == pytest.approx(0.75 + 2.0)
    assert result[1, 2] == pytest.approx(0.75 + 2.0)
    assert result[2, 0] == pytest.approx(0.75 + 2.0)
    assert result[1, 0] == pytest.approx(0.75)
    assert pheromones[0, 1] == 1.0  # la actualización no muta la matriz de entrada


def test_costo_cero_produce_deposito_finito():
    result = AntSystem._update_pheromones(np.ones((2, 2)), [((0, 1, 0), 0.0)], rho=1.0, q=3.0)
    assert np.all(np.isfinite(result))
    assert result[0, 1] == pytest.approx(3.0)
    assert result[1, 0] == pytest.approx(3.0)


def test_instancias_sinteticas_tienen_optimo_conocido_por_enumeracion():
    costs = [[0, 1, 50, 50], [50, 0, 1, 50], [50, 50, 0, 1], [1, 50, 50, 0]]
    problem = fixed_problem(costs)
    tours = [(0,) + order for order in permutations((1, 2, 3))]
    optimum = min(problem.evaluate_route(route).total_cost_eur for route in tours)
    result = AntSystem().run(problem, seed=7, budget=24, n_ants=6, beta=3.0)
    assert optimum == pytest.approx(4.0)
    assert result.best_cost_eur >= optimum
    assert result.best_cost_eur == pytest.approx(
        problem.evaluate_route(result.best_route).total_cost_eur
    )


def test_instancia_con_varios_optimos_y_caso_de_dos_ciudades():
    four = fixed_problem(np.ones((4, 4)) - np.eye(4))
    optimums = [four.evaluate_route((0,) + order).total_cost_eur for order in permutations((1, 2, 3))]
    assert len(set(optimums)) == 1
    two = fixed_problem([[0, 0], [0, 0]])
    result = AntSystem().run(two, seed=2, budget=3, n_ants=2)
    assert result.best_cost_eur == 0.0


@pytest.mark.parametrize("mode", ["fastest", "economic"])
def test_compatibilidad_con_modelo_de_alternativas_en_ambos_modos(mode):
    problem = alternative_problem(mode)
    result = AntSystem().run(problem, seed=7, budget=9, n_ants=4)
    assert result.objective_evaluations == 9
    assert result.best_breakdown.selected_alternative_ids
    assert result.best_cost_eur == pytest.approx(problem.evaluate_route(result.best_route).total_cost_eur)


def test_peajes_desconocidos_interrumpen_evaluacion_economica():
    problem = alternative_problem()
    unknown = RouteAlternative(
        origin_id="test-0", destination_id="test-1", alternative_id="unknown",
        fastest_route_id="fast-0-1", distance_km=9.0, duration_hours=2.0,
        toll_status=TollStatus.UNKNOWN, toll_cost_eur=None, routing_engine="synthetic",
        routing_engine_version="1", profile="synthetic-car", source="synthetic://route",
        acquired_on="2026-10-12", fuel_consumption_l_per_100km=5.0, fuel_price_eur_per_l=1.0,
        fuel_consumption_source="synthetic://consumption", fuel_price_reference="synthetic://price",
        vehicle_configuration="synthetic vehicle",
    )
    alternatives = [record for arc in problem.alternatives_by_arc.values() for record in arc]
    alternatives.append(unknown)
    economic = AlternativeTSPProblem(cities(3), alternatives, 0.5, mode="economic")
    with pytest.raises(UnverifiableCostError):
        AntSystem().run(economic, seed=2, budget=3)


def test_aco_no_importa_clientes_de_red():
    import inspect
    import src.tsp.aco as module

    source = inspect.getsource(module)
    assert "requests" not in source
    assert "urllib" not in source
