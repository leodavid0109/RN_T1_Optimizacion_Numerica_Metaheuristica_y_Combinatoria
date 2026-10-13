"""Líneas base y validación exacta sobre instancias sintéticas."""

import random

import numpy as np
import pytest

from src.tsp import (
    AntSystem,
    City,
    MAX_EXACT_CITIES,
    NearestNeighbor,
    NearestNeighborTwoOpt,
    TSPProblem,
    TwoOpt,
    solve_exact_small,
)


def make_problem(costs):
    matrix = np.asarray(costs, dtype=float)
    size = len(matrix)
    cities = tuple(
        City(f"synthetic-{i}", f"Ciudad sintética {i}", f"Provincia {i}",
             40.0, -3.0, "synthetic://baseline-test", "2026-10-12", "verificada",
             "fixture sintético de línea base")
        for i in range(size)
    )
    zeros = np.zeros_like(matrix)
    return TSPProblem(cities, zeros, zeros, matrix, zeros, 0.0)


def test_vecino_mas_cercano_construye_ciclos_cerrados_y_evalua_todos_los_inicios():
    problem = make_problem([
        [0, 1, 20, 20], [20, 0, 1, 20], [20, 20, 0, 1], [1, 20, 20, 0],
    ])
    result = NearestNeighbor().run(problem, seed=5, budget=10)
    assert result.objective_evaluations == problem.size
    assert result.stop_reason == "inicios_agotados"
    assert sorted(result.best_route) == list(range(problem.size))
    assert result.best_breakdown.closed_route == result.best_route + (result.best_route[0],)
    assert result.best_cost_eur == pytest.approx(4.0)


def test_vecino_mas_cercano_respeta_costos_dirigidos():
    problem = make_problem([[0, 1, 9], [8, 0, 1], [1, 7, 0]])
    route = NearestNeighbor().run(problem, seed=2, budget=1, start_cities=[0])
    assert route.best_route == (0, 1, 2)
    assert route.best_cost_eur == pytest.approx(3.0)
    assert problem.cost_matrix_eur[0, 1] != problem.cost_matrix_eur[1, 0]


def test_empates_del_vecino_mas_cercano_se_resuelven_por_indice():
    problem = make_problem(np.ones((4, 4)) - np.eye(4))
    route = NearestNeighbor().run(problem, seed=7, budget=1, start_cities=[0])
    assert route.best_route == (0, 1, 2, 3)


def test_vecino_mas_cercano_respeta_presupuesto_y_no_rellena_evaluaciones():
    problem = make_problem(np.ones((5, 5)) - np.eye(5))
    result = NearestNeighbor().run(problem, seed=3, budget=2)
    assert result.objective_evaluations == 2
    assert result.stop_reason == "presupuesto_agotado"


def _asymmetric_two_opt_case(reverse_internal_cost):
    matrix = np.full((4, 4), 100.0)
    np.fill_diagonal(matrix, 0.0)
    matrix[0, 1] = matrix[1, 2] = matrix[2, 3] = matrix[3, 0] = 10.0
    # Una fórmula simétrica miraría solo los cuatro arcos de frontera y vería
    # una mejora de 0->1,2->3 a 0->2,1->3: 20 frente a 2.
    matrix[0, 2] = 1.0
    matrix[1, 3] = 1.0
    # Pero al invertir [1,2], el arco interno cambia de 1->2 a 2->1.
    matrix[2, 1] = reverse_internal_cost
    return make_problem(matrix)


def test_dos_opt_dirigido_incluye_cambio_de_sentido_de_arcos_internos():
    problem = _asymmetric_two_opt_case(reverse_internal_cost=100.0)
    initial = problem.evaluate_route((0, 1, 2, 3)).total_cost_eur
    false_symmetric_candidate = problem.evaluate_route((0, 2, 1, 3)).total_cost_eur
    assert initial == pytest.approx(40.0)
    assert false_symmetric_candidate == pytest.approx(112.0)

    result = TwoOpt().run(
        problem, seed=4, budget=30, initial_route=(0, 1, 2, 3), policy="best_improvement"
    )
    assert result.best_cost_eur == pytest.approx(initial)
    assert result.best_route == (0, 1, 2, 3)
    assert result.objective_evaluations > 1


def test_dos_opt_acepta_mejoras_reales_y_no_empeora():
    problem = _asymmetric_two_opt_case(reverse_internal_cost=1.0)
    result = TwoOpt().run(
        problem, seed=4, budget=30, initial_route=(0, 1, 2, 3), policy="best_improvement"
    )
    assert result.best_cost_eur < 40.0
    assert result.best_cost_eur == pytest.approx(problem.evaluate_route(result.best_route).total_cost_eur)
    assert sorted(result.best_route) == [0, 1, 2, 3]


@pytest.mark.parametrize("policy", ["first_improvement", "best_improvement"])
def test_dos_opt_cumple_presupuesto_y_es_reproducible(policy):
    problem = _asymmetric_two_opt_case(reverse_internal_cost=1.0)
    first = TwoOpt().run(problem, seed=20, budget=3, initial_route=(0, 1, 2, 3), policy=policy)
    second = TwoOpt().run(problem, seed=20, budget=3, initial_route=(0, 1, 2, 3), policy=policy)
    assert first.objective_evaluations == 3
    assert (first.best_route, first.best_cost_eur, first.history) == (
        second.best_route, second.best_cost_eur, second.history
    )


def test_vecino_mas_cercano_mas_dos_opt_comparte_un_solo_presupuesto():
    problem = _asymmetric_two_opt_case(reverse_internal_cost=1.0)
    result = NearestNeighborTwoOpt().run(problem, seed=9, budget=7, policy="first_improvement")
    assert result.objective_evaluations == 7
    assert result.best_cost_eur <= min(
        problem.evaluate_route((0, 1, 2, 3)).total_cost_eur,
        problem.evaluate_route((0, 2, 1, 3)).total_cost_eur,
    )


def test_inicios_explicitos_y_validacion_de_parametros():
    problem = make_problem(np.ones((4, 4)) - np.eye(4))
    with pytest.raises(ValueError, match="duplicados"):
        NearestNeighbor().run(problem, seed=1, budget=2, start_cities=[0, 0])
    with pytest.raises(ValueError, match="policy"):
        TwoOpt().run(problem, seed=1, budget=2, policy="random")
    with pytest.raises(ValueError, match="seed"):
        NearestNeighbor().run(problem, seed=True, budget=1)


def test_optimo_exhaustivo_asimetrico_fija_origen_y_cuenta_permutaciones():
    problem = make_problem([[0, 1, 20], [20, 0, 1], [1, 20, 0]])
    result = solve_exact_small(problem)
    assert result.best_route == (0, 1, 2)
    assert result.best_cost_eur == pytest.approx(3.0)
    assert result.optimal_routes == ((0, 1, 2),)
    assert result.objective_evaluations == 2  # (N-1)!


def test_optimo_exhaustivo_identifica_todos_los_empates_simetrico_y_costo_cero():
    problem = make_problem(np.zeros((5, 5)))
    result = solve_exact_small(problem)
    assert result.best_cost_eur == 0.0
    assert len(result.optimal_routes) == 24
    assert all(route[0] == 0 for route in result.optimal_routes)
    assert result.objective_evaluations == 24


def test_optimo_exhaustivo_rechaza_tamanos_fuera_del_limite():
    problem = make_problem(np.zeros((MAX_EXACT_CITIES + 1, MAX_EXACT_CITIES + 1)))
    with pytest.raises(ValueError, match="limitada"):
        solve_exact_small(problem)


def test_exactitud_de_lineas_base_no_modifica_rng_global_ni_usa_red():
    import inspect
    import src.tsp.baselines as baseline_module
    import src.tsp.exact as exact_module

    state = random.getstate()
    problem = make_problem([[0, 2, 3], [1, 0, 4], [5, 2, 0]])
    NearestNeighbor().run(problem, seed=88, budget=3)
    assert random.getstate() == state
    assert "requests" not in inspect.getsource(baseline_module)
    assert "urllib" not in inspect.getsource(baseline_module)
    assert "requests" not in inspect.getsource(exact_module)


def test_evaluaciones_de_vecino_mas_cercano_mas_dos_opt_coinciden_con_llamadas():
    class CountingObjective:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def evaluate_route(self, route, hour_value_eur_per_hour=None):
            self.calls += 1
            return self.wrapped.evaluate_route(route, hour_value_eur_per_hour)

    problem = CountingObjective(_asymmetric_two_opt_case(reverse_internal_cost=1.0))
    result = NearestNeighborTwoOpt().run(problem, seed=9, budget=7, policy="best_improvement")
    assert problem.calls == result.objective_evaluations <= 7


def test_aco_y_lineas_base_comparten_objetivo_y_evaluador():
    problem = make_problem([[0, 3, 6, 5], [4, 0, 2, 6], [3, 5, 0, 1], [2, 4, 5, 0]])
    exact = solve_exact_small(problem)
    aco = AntSystem().run(problem, seed=10, budget=24, n_ants=5)
    nearest = NearestNeighbor().run(problem, seed=10, budget=24)
    assert aco.objective_evaluations == 24
    assert nearest.objective_evaluations == problem.size
    assert aco.best_cost_eur >= exact.best_cost_eur
    assert nearest.best_cost_eur >= exact.best_cost_eur
