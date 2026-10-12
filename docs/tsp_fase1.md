# Fundamentos del módulo TSP — Fase 1

## Estructura

- `src/tsp/cities.py`: registros inmutables de ciudad, lectura y validación del catálogo.
- `src/tsp/matrices.py`: lectura de matrices CSV y validación de tamaño, finitud y no negatividad.
- `src/tsp/problem.py`: matrices del problema, validación de permutaciones y cálculo de costos cerrados.
- `src/tsp/contracts.py`: resultados e interfaz callable común para ACO, GA y futuros métodos.
- `src/tsp/evaluation.py`: contador de evaluaciones y registro del historial por presupuesto.
- `data/processed/capitales_peninsulares.csv`: catálogo canónico de nombres, procedencia y coordenadas pendientes.

El catálogo incluye 47 capitales. Los nombres de ciudades y provincias se documentan con las fuentes IGN listadas en `data/fuentes.md`. El IGN también publica un nomenclátor con coordenadas, pero no fue posible recuperar o inspeccionar los ficheros desde este entorno; por eso las latitudes y longitudes permanecen vacías. El catálogo hace explícito `coordinate_status=pendiente` y el cargador no confunde un dato ausente con un valor estimado.

## Punto geográfico representativo

El catálogo reserva los campos `latitude`, `longitude` y `representative_point_definition`. Antes de completarlos, el equipo debe elegir, por ejemplo, un punto oficial del núcleo urbano o un punto de referencia municipal consistente. Un centroide administrativo o una coordenada toponímica no necesariamente coincide con el acceso a la red vial al que ajusta un motor de rutas. El origen/destino ajustado por el motor deberá conservarse luego como dato separado, si el proveedor lo expone.

## Modelo matemático

Para una permutación `r=(r_0,...,r_(N-1))`, se cierra explícitamente como `r_N=r_0`. Las matrices pueden ser dirigidas; no se exige `M[i,j] = M[j,i]`. La evaluación suma los N arcos, incluido el retorno:

\[
D(r)=\sum_{k=0}^{N-1}D_{r_k,r_{k+1}},\quad
T(r)=\sum_{k=0}^{N-1}T_{r_k,r_{k+1}},\quad
P(r)=\sum_{k=0}^{N-1}P_{r_k,r_{k+1}},\quad
F(r)=\sum_{k=0}^{N-1}F_{r_k,r_{k+1}}.
\]

Para un valor horario `v` en EUR/h, el costo total es `C(r;v) = v*T(r) + P(r) + F(r)`. El parámetro se puede cambiar en cada evaluación; las matrices se copian al construir el problema y quedan de solo lectura. `RouteCost` devuelve distancia, tiempo, costo laboral, peajes, combustible y costo total por separado.

La formulación supone que cada arco tiene un trayecto fijo ya seleccionado. Si entre dos ciudades hay rutas alternativas, sus componentes pueden cambiar y se debe decidir cómo fijar o evaluar esas alternativas antes de adquirir matrices. Un cambio de `v` en este modelo solo cambia la ponderación del tiempo, no recalcula el camino por carretera.

## Contrato de ACO y GA

Cada implementación expondrá `algorithm.run(problem, seed, budget, **params) -> TSPRunResult`. `problem` será la misma instancia `TSPProblem` en ambos métodos. El presupuesto es un entero positivo de **evaluaciones completas de ruta**. Una evaluación completa ocurre cuando el algoritmo presenta una permutación válida y calcula todos los N arcos cerrados mediante `RunEvaluator.evaluate`.

Los costos de prefijos, arcos individuales, probabilidades, penalizaciones y otras puntuaciones parciales son cálculos auxiliares: no cuentan como evaluaciones completas y no deben aparecer en el contador. Cada método usará su propio `RunEvaluator`, que incrementa el contador solo después de evaluar con éxito una permutación completa y rechaza cualquier evaluación una vez agotado el límite. El tiempo de ejecución y el costo de inicialización se pueden registrar aparte; no forman parte de este presupuesto de objetivo.

El historial contiene `ConvergencePoint(evaluations, best_cost_eur)` en la primera evaluación y cada vez que mejora el mejor costo. `evaluations` es el contador acumulado de rutas completas, no el número de generaciones. Al comparar curvas sobre un presupuesto común, se interpreta como una función escalonada y se conserva el último mejor valor hasta el siguiente punto. `TSPRunResult` incluye la ruta, costo y desglose, historial, número de evaluaciones, semilla y `stop_reason`.

No se implementaron optimizadores en esta fase. El contrato es suficiente para acordarlo con el integrante responsable del GA antes de escribir los algoritmos.

## Validaciones y decisiones pendientes

Las pruebas usan una instancia sintética dirigida de tres ciudades para verificar el cierre, el desglose manual, la asimetría y el efecto del valor horario; esos números no son datos de España. El catálogo se prueba aparte y no contiene coordenadas sintéticas.

Siguen pendientes: inspeccionar el dataset IGN descargable y poblar coordenadas verificadas; escoger el tipo de punto representativo; acordar con el integrante 2 nombres y semántica del contrato; decidir la regla de selección de ruta, perfil/horario del vehículo, tarifas de peajes y precio de combustible. No se consultaron rutas ni se generaron matrices reales.
