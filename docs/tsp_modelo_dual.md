# Fase 3B — Modelo dual de rutas del TSP

## Estado y alcance

Esta fase implementa el evaluador de rutas rápidas fijas (Modelo A), el evaluador de alternativas conocidas (Modelo B), su catálogo tipado y pruebas matemáticas sintéticas. No contiene la matriz real de 2.162 arcos, no adquiere rutas, y no implementa ACO ni GA. El catálogo del piloto OSRM no se transforma en matrices definitivas.

Las ciudades conservan el orden e identificadores del catálogo canónico de `data/processed/capitales_peninsulares.csv`. Las fuentes y limitaciones de datos reales siguen registradas en [`data/fuentes.md`](../data/fuentes.md).

## Formulación

Para cada arco dirigido `i -> j`, una alternativa `r` tiene distancia `D_ijr`, tiempo `T_ijr`, peaje `P_ijr` y combustible `F_ijr`. Para valor horario `v >= 0`:

```text
c_A(i,j,v) = v*T_ijf + P_ijf + F_ijf
c_B(i,j,v) = min_r (v*T_ijr + P_ijr + F_ijr)
```

`f` es la alternativa rápida fija. Una secuencia `pi` de N ciudades se cierra con `pi_N = pi_0` y su costo es la suma de los N arcos dirigidos, incluido el regreso. El desglose de ruta acumula distancia, duración, peajes, combustible, costo laboral `v*T` y costo total. La dirección se conserva: no se refleja ni promedia una matriz.

La elección económica local del Modelo B es válida cuando el costo total es aditivo y la elección vial de un arco no restringe ni cambia las opciones de otro arco. En esas condiciones:

```text
min_(r_0,...,r_(N-1)) sum_k g_k(r_k;v) = sum_k min_(r_k) g_k(r_k;v)
```

Por ello, los genes de ACO/GA representan únicamente el orden de ciudades; las elecciones viales se calculan por arco para el valor `v` de la evaluación. Si hay efectos de hora de salida/tiempo real, descuentos conjuntos, o restricciones que enlazan arcos, el supuesto deja de ser suficiente y el estado del problema debe ampliarse.

El Modelo B optimiza **solo entre las alternativas almacenadas**. No demuestra que se hayan encontrado todas las rutas posibles. Como el catálogo debe incluir la alternativa rápida de cada arco, para una misma secuencia completa y con costos verificables se cumple `C_B <= C_A`. Esto no afirma que la solución heurística encontrada por ACO/GA en dos ejecuciones independientes satisfaga esa desigualdad: para la comparación controlada se evaluará también una misma secuencia bajo ambos modelos.

## Arquitectura

- `src/tsp/alternatives.py`: `RouteAlternative`, estados de peaje y poda segura de alternativas dominadas.
- `src/tsp/models.py`: `AlternativeTSPProblem`, que actúa en modo `fastest` (Modelo A basado en alternativas) o `economic` (Modelo B); devuelve matriz dirigida y evaluación cerrada con identificadores elegidos.
- `src/tsp/problem.py`: mantiene `TSPProblem` y amplía `RouteCost` con una lista opcional de identificadores de alternativas. Para problemas antiguos la lista queda vacía.
- `src/tsp/contracts.py`: define `TSPObjective`, un protocolo estructural con tamaño, matriz efectiva y evaluación. `TSPAlgorithm.run(problem, seed, budget, **params)` conserva sus argumentos y permite cualquiera de los dos objetivos.
- `src/tsp/evaluation.py`: `RunEvaluator` acepta ese protocolo; sigue contando invocaciones exitosas de rutas completas. Cálculos parciales de arcos no consumen presupuesto.

`cost_matrix_for_hour(v)` crea una matriz de costos nueva e inmutable. La instancia y los registros de alternativa no cambian al variar `v`; `with_hour_value(v)` crea otra vista evaluadora. ACO podrá consultar la matriz efectiva y ambos algoritmos podrán usar el mismo `evaluate_route` y el mismo contador.

## Registro de alternativa y procedencia

`RouteAlternative` incluye ciudades dirigidas, ID de alternativa, ID de la ruta rápida del arco, distancia km, duración h, geometría opcional en pares `(longitud, latitud)`, referencias de vía, motor/versión/perfil, fuente y fecha de adquisición, versión del conjunto de red, parámetros de enrutamiento, tarifa y vigencia, datos del vehículo/combustible y limitaciones. Los campos `*_eur` expresan euros; el precio de combustible es EUR/l y el consumo L/100 km. La matriz es de solo lectura y las secuencias de geometría/referencias se congelan como tuplas.

Ejemplo exclusivamente sintético (no describe una ruta española):

```python
RouteAlternative(
    origin_id="test-a", destination_id="test-b",
    alternative_id="fast-test-a-b", fastest_route_id="fast-test-a-b",
    distance_km=10.0, duration_hours=0.2,
    toll_status=TollStatus.VERIFIED_WITHOUT_TOLL, toll_cost_eur=0.0,
    toll_source="synthetic://fixture", toll_checked_on="2026-10-12",
    routing_engine="fixture", routing_engine_version="1", profile="fixture-car",
    source="synthetic://fixture", acquired_on="2026-10-12",
    fuel_consumption_l_per_100km=5.0,
    fuel_consumption_source="synthetic://fixture",
    fuel_price_eur_per_l=1.0, fuel_price_reference="synthetic://fixture",
    vehicle_configuration="vehículo sintético",
)
```

El combustible se calcula como `D/100 * q * p`. Consumo y precio deben aparecer juntos, con sus fuentes/configuración; si falta uno, el costo de combustible es desconocido. El conjunto completo debe utilizar la misma configuración y referencia de precio para que las alternativas sean comparables. La matriz real aún no incluye esos datos.

## Peajes desconocidos y verificabilidad

`TollStatus` distingue `verificado_con_peaje`, `verificado_sin_peaje` y `desconocido`. Un peaje desconocido exige `toll_cost_eur=None`; cero solo es válido con estado verificado sin peaje y fuente/fecha de verificación. La moneda monetaria del objetivo es EUR.

En Modelo A, una ruta rápida con peaje o combustible incompleto no se puede evaluar económicamente. En Modelo B, basta una alternativa incompleta en un arco para que el mínimo de ese arco no pueda verificarse: podría resultar más barata que las conocidas. `UnverifiableCostError` informa ese bloqueo. No se rellenan huecos con cero. La matriz de costos también falla si no puede definir todos sus arcos, lo cual evita que una heurística obtenga prioridades ficticias.

## Dominancia y desempate

Sea `B_ijr = P_ijr + F_ijr`. Para `v >= 0`, una alternativa `a` domina a `b` si `T_a <= T_b` y `B_a <= B_b`, y al menos una desigualdad es estricta. `remove_dominated_alternatives` conserva la frontera no dominada y siempre retiene la ruta rápida marcada para mantener disponible el Modelo A. Solo compara alternativas del mismo arco. Alternativas con costos incompletos se conservan: no se infiere dominancia a partir de un peaje desconocido.

Si dos alternativas tienen exactamente el mismo costo para el valor horario evaluado, se elige el `alternative_id` lexicográficamente menor. Así el resultado no depende del orden de filas del catálogo. La poda no borra los registros fuente; solo devuelve las alternativas candidatas no dominadas.

## Uso e integración futura

```python
model_b = AlternativeTSPProblem(cities, catalog, hour_value_eur_per_hour=25, mode="economic")
cost = model_b.evaluate_route(route)
for (origin, destination), alternative_id in zip(
    zip(cost.closed_route[:-1], cost.closed_route[1:]), cost.selected_alternative_ids
):
    record = model_b.get_alternative(
        cities[origin].city_id, cities[destination].city_id, alternative_id
    )
```

El modo `fastest` usa el registro cuyo `alternative_id` coincide con `fastest_route_id`; `economic` selecciona el menor `v*T + P + F`. Ambos exponen `size`, `cost_matrix_eur`, `cost_matrix_for_hour(v)` y `evaluate_route`, por lo que satisfacen `TSPObjective` y mantienen la forma del contrato de GA/ACO. `TSPProblem` continúa disponible sin cambios en su constructor ni en su evaluación existente.

El presupuesto sigue siendo el número de evaluaciones completas. Cada `RunEvaluator.evaluate` cuenta una permutación cerrada calculada correctamente, incluso si se repite; cálculo de una matriz o costos parciales no cuenta como corrida evaluada.

## Pruebas y límites

`tests/test_tsp_dual_model.py` usa solo tres ciudades sintéticas para comprobar Modelo A, selección y cambio por `v`, inclusión de ruta rápida, `C_B <= C_A` para una ruta común, asimetría, cierre, inmutabilidad, peaje desconocido, dominancia, desempate, reconstrucción de alternativas y compatibilidad del contador. No son resultados experimentales ni datos de España.

Faltan para el uso empírico: completar alternativas para los 2.162 arcos, elegir y documentar el perfil/versionado del motor, verificar tarifas por puntos de entrada/salida y fijar de forma aprobada el vehículo/precio de combustible. La cobertura de las alternativas conocidas limita el alcance del Modelo B.
