"""Pruebas matemáticas con rutas sintéticas; no representan carreteras españolas."""

from dataclasses import replace

import numpy as np
import pytest

from src.tsp import (
    AlternativeTSPProblem,
    City,
    RouteAlternative,
    TollStatus,
    TSPProblem,
    UnverifiableCostError,
    remove_dominated_alternatives,
)


def synthetic_cities():
    return tuple(
        City(f"test-{i}", f"Ciudad {i}", f"Provincia {i}", 1.0, 2.0,
             "synthetic://cities", "2026-10-12", "verificada", "fixture sintético")
        for i in range(3)
    )


def synthetic_alternatives(*, unknown_arc=None, tied=False):
    """Catálogo completo sintético de 3 nodos, con rutas rápidas y lentas."""
    result = []
    for i in range(3):
        for j in range(3):
            if i == j:
                continue
            fast_id = f"fast-{i}-{j}"
            fast_distance = 100.0 + i * 10.0 + j
            fast_time = 1.0 + i * 0.1 + j * 0.01
            for alternative_id, distance, duration in (
                (fast_id, fast_distance, fast_time),
                (f"slow-{i}-{j}", fast_distance - 10.0, fast_time + 1.0),
            ):
                is_unknown = unknown_arc == (i, j) and alternative_id.startswith("slow")
                toll = None if is_unknown else (2.0 if i > j else 0.0)
                status = TollStatus.UNKNOWN if is_unknown else (
                    TollStatus.VERIFIED_WITH_TOLL if toll else TollStatus.VERIFIED_WITHOUT_TOLL
                )
                result.append(RouteAlternative(
                    origin_id=f"test-{i}", destination_id=f"test-{j}",
                    alternative_id=alternative_id, fastest_route_id=fast_id,
                    distance_km=distance, duration_hours=duration,
                    toll_status=status, toll_cost_eur=toll,
                    routing_engine="synthetic", routing_engine_version="1",
                    profile="synthetic-car", source="synthetic://route-fixture",
                    acquired_on="2026-10-12",
                    toll_source=None if is_unknown else "synthetic://toll-fixture",
                    toll_checked_on=None if is_unknown else "2026-10-12",
                    fuel_consumption_l_per_100km=5.0, fuel_price_eur_per_l=1.0,
                    fuel_consumption_source="synthetic://consumption-fixture",
                    fuel_price_reference="synthetic://fuel-fixture",
                    vehicle_configuration="synthetic vehicle",
                    geometry_lon_lat=((2.0, 1.0), (2.1, 1.1)),
                    limitations=("datos sintéticos de prueba",),
                ))
            if tied and (i, j) == (0, 1):
                result.append(replace(
                    result[-2], alternative_id="aaa-tie", distance_km=fast_distance,
                    duration_hours=fast_time,
                ))
    return tuple(result)


def make_model(value=0.0, mode="economic", alternatives=None):
    return AlternativeTSPProblem(
        synthetic_cities(), alternatives or synthetic_alternatives(), value, mode=mode,
        metadata={"fixture": "synthetic"},
    )


def make_legacy_problem(value=8.0):
    cities = synthetic_cities()
    return TSPProblem(
        cities,
        [[0, 10, 20], [11, 0, 30], [31, 12, 0]],
        [[0, 1, 2], [1.5, 0, 3], [0.5, 2.5, 0]],
        [[0, 2, 4], [3, 0, 5], [6, 7, 0]],
        [[0, 4, 8], [5, 0, 6], [7, 9, 0]],
        value,
    )


def test_modelo_a_matriz_fija_conserva_evaluacion_existente():
    old = make_legacy_problem()
    result = old.evaluate_route((0, 1, 2))
    assert result.closed_route == (0, 1, 2, 0)
    assert result.total_cost_eur == pytest.approx(66.0)
    np.testing.assert_array_equal(old.cost_matrix_eur, 8 * old.time_hours + old.toll_cost_eur + old.fuel_cost_eur)


def test_modelo_a_de_alternativas_siempre_utiliza_ruta_rapida():
    model = make_model(value=0.0, mode="fastest")
    result = model.evaluate_route((0, 1, 2))
    assert result.selected_alternative_ids == ("fast-0-1", "fast-1-2", "fast-2-0")


def test_modelo_b_selecciona_la_alternativa_mas_economica():
    model = make_model(value=0.0, mode="economic")
    result = model.evaluate_route((0, 1, 2))
    assert result.selected_alternative_ids == ("slow-0-1", "slow-1-2", "slow-2-0")


def test_seleccion_economica_cambia_al_variar_valor_horario_sin_mutar_datos():
    alternatives = synthetic_alternatives()
    low = make_model(value=0.0, alternatives=alternatives)
    high = low.with_hour_value(10.0)
    before = tuple((item.alternative_id, item.distance_km, item.duration_hours) for item in alternatives)
    assert low.evaluate_route((0, 1, 2)).selected_alternative_ids != high.evaluate_route((0, 1, 2)).selected_alternative_ids
    assert tuple((item.alternative_id, item.distance_km, item.duration_hours) for item in alternatives) == before
    assert low.hour_value_eur_per_hour == 0.0
    assert high.hour_value_eur_per_hour == 10.0


@pytest.mark.parametrize("hour_value", [0.0, 0.5, 10.0])
def test_modelo_b_contiene_el_rapido_y_no_supera_a_en_la_misma_ruta(hour_value):
    routes = synthetic_alternatives()
    model_a = make_model(hour_value, "fastest", routes)
    model_b = make_model(hour_value, "economic", routes)
    route = (0, 1, 2)
    a = model_a.evaluate_route(route)
    b = model_b.evaluate_route(route)
    assert all(any(record.alternative_id == record.fastest_route_id for record in records)
               for records in model_b.alternatives_by_arc.values())
    assert b.total_cost_eur <= a.total_cost_eur + 1e-12


def test_modelos_conservan_asimetria_y_cierre_del_ciclo():
    model = make_model(value=3.0)
    matrix = model.cost_matrix_eur
    assert matrix[0, 1] != matrix[1, 0]
    result = model.evaluate_route((0, 1, 2))
    assert result.closed_route == (0, 1, 2, 0)
    assert len(result.selected_alternative_ids) == 3
    assert model.cost_matrix_eur[0, 1] + model.cost_matrix_eur[1, 2] + model.cost_matrix_eur[2, 0] == pytest.approx(
        result.total_cost_eur
    )


def test_peaje_desconocido_no_se_trata_como_cero():
    records = synthetic_alternatives(unknown_arc=(0, 1))
    assert next(item for item in records if item.alternative_id == "slow-0-1").toll_cost_eur is None
    model = make_model(alternatives=records)
    with pytest.raises(UnverifiableCostError, match="costo no verificable"):
        model.evaluate_route((0, 1, 2))
    with pytest.raises(ValueError, match="importe None"):
        replace(records[-1], toll_status=TollStatus.UNKNOWN, toll_cost_eur=0.0)


def test_detecta_alternativas_dominadas_sin_eliminar_frontera_relevante():
    records = list(synthetic_alternatives())
    fast = next(item for item in records if item.alternative_id == "fast-0-1")
    dominated = replace(fast, alternative_id="dominated", distance_km=fast.distance_km + 5,
                        duration_hours=fast.duration_hours + 1, fastest_route_id=fast.fastest_route_id)
    relevant = replace(fast, alternative_id="short-slow", duration_hours=fast.duration_hours - 0.2,
                       distance_km=fast.distance_km - 5, toll_cost_eur=8.0,
                       toll_status=TollStatus.VERIFIED_WITH_TOLL,
                       toll_source="synthetic://toll-fixture", toll_checked_on="2026-10-12")
    kept = remove_dominated_alternatives((fast, dominated, relevant))
    assert {item.alternative_id for item in kept} == {fast.alternative_id, relevant.alternative_id}


def test_poda_preserva_ruta_rapida_y_compara_solo_alternativas_del_mismo_arco():
    records = synthetic_alternatives()
    fast_01 = next(item for item in records if item.alternative_id == "fast-0-1")
    same_time_more_expensive = replace(
        fast_01, alternative_id="more-expensive-equal-time", distance_km=fast_01.distance_km + 1,
    )
    slow_01 = next(item for item in records if item.alternative_id == "slow-0-1")
    other_arc = next(item for item in records if item.alternative_id == "fast-0-2")
    very_good_other_arc = replace(other_arc, alternative_id="very-good-0-2", distance_km=1.0,
                                   duration_hours=0.01)
    kept = remove_dominated_alternatives((fast_01, same_time_more_expensive, slow_01,
                                          other_arc, very_good_other_arc))
    assert fast_01 in kept
    assert same_time_more_expensive not in kept
    assert slow_01 in kept
    assert other_arc in kept


def test_empate_se_resuelve_por_identificador_lexicografico():
    model = make_model(value=4.0, alternatives=synthetic_alternatives(tied=True))
    selected = model.selected_alternatives_for_route((0, 1, 2), 4.0)
    first_arc = selected[0]
    assert first_arc.alternative_id == "aaa-tie"
    assert model.get_alternative(first_arc.origin_id, first_arc.destination_id,
                                 first_arc.alternative_id).alternative_id == "aaa-tie"


def test_datos_y_matriz_de_costos_son_inmutables_y_se_puede_reconstruir_la_seleccion():
    model = make_model(value=0.0)
    result = model.evaluate_route((0, 1, 2))
    for origin, destination, alt_id in zip(result.closed_route[:-1], result.closed_route[1:],
                                            result.selected_alternative_ids):
        route_record = model.get_alternative(model.cities[origin].city_id,
                                             model.cities[destination].city_id, alt_id)
        assert route_record.alternative_id == alt_id
    with pytest.raises(ValueError):
        model.cost_matrix_eur[0, 1] = 0


def test_run_evaluator_acepta_modelo_dual_por_el_protocolo_comun():
    from src.tsp import RunEvaluator

    evaluator = RunEvaluator(make_model(value=2.0), budget=2)
    evaluator.evaluate((0, 1, 2))
    result = evaluator.finish(seed=7, stop_reason="budget")
    assert result.objective_evaluations == 1
    assert result.best_breakdown.selected_alternative_ids
