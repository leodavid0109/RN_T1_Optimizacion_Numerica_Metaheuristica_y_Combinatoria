"""Pruebas del algoritmo genético sobre objetivos sintéticos y un humo con datos reales (sin peajes)."""

import numpy as np
import pytest

from src.tsp import GeneticAlgorithm, City, TSPProblem, solve_exact_small
from src.tsp.ga import _inversion_mutation, _order_crossover, _pmx_crossover, _swap_mutation


def cities(size):
    return tuple(
        City(f"test-{i}", f"Ciudad {i}", f"Provincia {i}", 40.0, -3.0,
             "synthetic://ga-test", "2026-10-12", "verificada", "fixture sintético")
        for i in range(size)
    )


def random_problem(size, seed=0, hour_value=5.0):
    rng = np.random.default_rng(seed)

    def matrix(low, high):
        m = rng.uniform(low, high, size=(size, size))
        np.fill_diagonal(m, 0.0)
        return m

    return TSPProblem(cities(size), matrix(10, 100), matrix(0.1, 1.0), matrix(0, 20), matrix(1, 10), hour_value)


@pytest.mark.parametrize("crossover", ["ox", "pmx"])
@pytest.mark.parametrize("mutation", ["swap", "inversion"])
@pytest.mark.parametrize("budget", [1, 7, 40, 95])
def test_respeta_contrato_y_presupuesto_exacto(crossover, mutation, budget):
    problem = random_problem(8)
    result = GeneticAlgorithm().run(problem, seed=3, budget=budget, population_size=10, crossover=crossover,
                                    mutation=mutation)
    assert result.objective_evaluations == budget  # ni una evaluación de más ni de menos
    assert sorted(result.best_route) == list(range(8))
    assert result.stop_reason == "presupuesto_agotado"
    assert result.history[-1].best_cost_eur == pytest.approx(result.best_cost_eur)


def test_elites_no_se_reevaluan():
    problem = random_problem(6)
    # población 10, 2 élites: la población inicial cuesta 10 y cada generación completa 8
    result = GeneticAlgorithm().run(problem, seed=1, budget=10 + 8 * 3, population_size=10, elite_size=2)
    assert result.objective_evaluations == 34


def test_es_reproducible_y_la_semilla_importa():
    problem = random_problem(10)
    a = GeneticAlgorithm().run(problem, seed=4, budget=300, population_size=20)
    b = GeneticAlgorithm().run(problem, seed=4, budget=300, population_size=20)
    c = GeneticAlgorithm().run(problem, seed=5, budget=300, population_size=20)
    assert a.best_route == b.best_route and a.history == b.history
    assert a.history != c.history


def test_el_mejor_costo_nunca_empeora():
    result = GeneticAlgorithm().run(random_problem(12), seed=2, budget=500, population_size=30)
    costs = [point.best_cost_eur for point in result.history]
    assert costs == sorted(costs, reverse=True)


def test_encuentra_el_optimo_en_una_instancia_pequena():
    problem = random_problem(7, seed=11)
    exact = solve_exact_small(problem)
    result = GeneticAlgorithm().run(problem, seed=0, budget=4000, population_size=40)
    assert result.best_cost_eur == pytest.approx(exact.best_cost_eur)


def test_el_valor_de_la_hora_cambia_la_ruta_optima():
    # Con v=0 manda el costo monetario; con v muy alto, el tiempo. Rutas distintas en esta instancia.
    low = GeneticAlgorithm().run(random_problem(7, seed=3, hour_value=0.0), seed=0, budget=3000, population_size=40)
    high = GeneticAlgorithm().run(random_problem(7, seed=3, hour_value=1000.0), seed=0, budget=3000, population_size=40)
    assert low.best_breakdown.seller_time_cost_eur == 0.0
    assert high.best_breakdown.total_time_hours <= low.best_breakdown.total_time_hours + 1e-12


@pytest.mark.parametrize("n", [2, 3, 5, 47])
def test_operadores_producen_permutaciones_validas(n):
    rng = np.random.default_rng(0)
    for _ in range(300):
        a, b = rng.permutation(n), rng.permutation(n)
        for op in (_order_crossover, _pmx_crossover):
            assert sorted(op(a, b, rng)) == list(range(n))
        for op in (_swap_mutation, _inversion_mutation):
            assert sorted(op(a, rng)) == list(range(n))


def test_cruce_de_padres_identicos_devuelve_el_mismo_padre():
    rng = np.random.default_rng(1)
    a = rng.permutation(9)
    for op in (_order_crossover, _pmx_crossover):
        assert list(op(a, a.copy(), rng)) == list(a)


@pytest.mark.parametrize("kwargs", [
    {"population_size": 1}, {"crossover_rate": 1.5}, {"mutation_rate": -0.1}, {"tournament_size": 0},
    {"elite_size": -1}, {"elite_size": 10, "population_size": 10}, {"crossover": "cx"}, {"mutation": "scramble"},
])
def test_rechaza_hiperparametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        GeneticAlgorithm().run(random_problem(5), seed=1, budget=20, **kwargs)


def test_rechaza_parametros_desconocidos_y_semilla_invalida():
    with pytest.raises(TypeError):
        GeneticAlgorithm().run(random_problem(5), seed=1, budget=20, alpha=1.0)
    with pytest.raises(ValueError):
        GeneticAlgorithm().run(random_problem(5), seed=1.5, budget=20)


def test_humo_con_la_instancia_economica_real():
    from src.tsp.economic_dataset import load_economic_problem
    problem = load_economic_problem(hour_value=25.0)  # verifica además que reproduce model_a_v25_eur.csv
    assert problem.size == 47 and "EXPERIMENTAL" in problem.scope
    result = GeneticAlgorithm().run(problem, seed=0, budget=300, population_size=30)
    assert result.objective_evaluations == 300 and sorted(result.best_route) == list(range(47))
    assert result.best_breakdown.toll_cost_eur >= 0.0
