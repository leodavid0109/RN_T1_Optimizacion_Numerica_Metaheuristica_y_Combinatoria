# Líneas base y validación de Ant System

## Vecino más cercano

Para cada ciudad de inicio, el procedimiento agrega la ciudad no visitada con
menor costo dirigido desde la ciudad actual. Los empates locales se resuelven
por el índice de ciudad menor. La construcción consulta la matriz de arcos,
pero una solución solo se cuenta cuando se evalúa el ciclo completo, incluido
el retorno al origen, con `RunEvaluator`.

Por defecto se consideran todos los inicios, en un orden reproducible derivado
de la semilla. Si el presupuesto es menor que el número de ciudades, se evalúan
solo los primeros inicios de ese orden. Si se agotan los inicios antes del
presupuesto, el algoritmo informa el número real de evaluaciones y no genera
rutas artificiales para llenar el presupuesto.

## 2-opt para costos dirigidos

La búsqueda invierte segmentos cíclicos de la ruta. Para una ruta con segmento
`b,...,c`, predecesor `a` y sucesor `d`, el cambio de costo incluye:

```text
Δ = c[a,c] + c[b,d] - c[a,b] - c[c,d]
    + Σ(x->y interno) (c[y,x] - c[x,y])
```

El segundo término suma el cambio de sentido de **cada arco interno**. La
fórmula simétrica común omite este término porque presupone `c[x,y] = c[y,x]`;
no sirve para este problema dirigido. La implementación prioriza corrección y
evalúa cada ruta vecina completa mediante el objetivo, evitando usar un delta
incorrecto. Cada vecino evaluado consume una evaluación completa.

Se ofrecen dos políticas reproducibles:

- `first_improvement`: acepta el primer vecino que reduce estrictamente el costo
  según un orden determinista y reinicia la búsqueda.
- `best_improvement`: examina el vecindario y acepta el vecino de menor costo
  que mejore estrictamente la ruta actual.

Se consideran segmentos cíclicos de longitud 2 a `N-2`, se normalizan para que
la primera ciudad siga fija y se deduplican. Se excluyen inversiones
degeneradas. Con menos de cuatro ciudades no hay movimientos 2-opt de dos
aristas no adyacentes. La ruta siempre conserva la permutación y el cierre.

Si no se suministra una ruta inicial a `TwoOpt`, se construye un vecino más
cercano desde la ciudad 0 y esa ruta inicial consume una evaluación. El método
compuesto `NearestNeighborTwoOpt` evalúa los recorridos de varios inicios y
continúa desde el mejor usando **el mismo** `RunEvaluator`; no vuelve a evaluar
la ruta seleccionada.

## Validador exacto de tamaño pequeño

`solve_exact_small` fija la ciudad 0 y recorre las `(N-1)!` permutaciones
restantes. Usa el objetivo común y cuenta cada ciclo completo en
`objective_evaluations`. Devuelve todas las rutas dentro de una tolerancia
numérica de `1e-12` del costo mínimo y limita la entrada a nueve ciudades. El
límite evita que se ejecute accidentalmente sobre las 47 ciudades (`46!` rutas).
Es un validador offline para pruebas pequeñas, no un algoritmo de producción.

Las fixtures incluyen matrices simétricas y asimétricas, costos cero, costos con
grandes diferencias y problemas con uno o varios óptimos. La enumeración se
utiliza únicamente para obtener el óptimo de estas instancias pequeñas.

## Conteo y equidad

Una evaluación es una llamada a `evaluate_route` que calcula el desglose de un
ciclo cerrado. `RunEvaluator` hace cumplir el máximo y registra mejoras con el
contador acumulado real. Inspeccionar arcos durante vecino más cercano, enumerar
movimientos o calcular probabilidades no cuenta como evaluación, pero sí consume
tiempo de CPU. En 2-opt cada vecino cuyo ciclo completo se calcula cuenta;
paradas por óptimo local pueden usar menos del presupuesto. No se completa ese
remanente con evaluaciones ficticias.

Compartir presupuesto de objetivo permite comparar la calidad en función de
cuántas soluciones completas puntuó cada método. No implica que los algoritmos
tengan el mismo costo computacional: construir una solución ACO, generar una
vecindad 2-opt y ejecutar las operaciones internas del GA tienen costos distintos.
Por eso se reportan también evaluaciones realmente usadas y tiempo medido.

## Experimento reducido

Ejecutar desde la raíz, sin internet:

```powershell
.\.venv\Scripts\python.exe -m experiments.validate_tsp_aco --config configs/tsp_baselines_demo.yaml
```

La configuración hace tres corridas por método sobre una matriz sintética
dirigida de cinco ciudades, con presupuesto máximo de 60 evaluaciones por
corrida. El óptimo se obtiene una vez por enumeración (`4! = 24` ciclos). El
script genera `results/tsp_baselines_demo/runs.csv` y `summary.md`, ignorados por
Git y reproducibles. El CSV conserva ruta, costo, brecha, evaluaciones, tiempo,
criterio de parada e historial de convergencia de cada corrida.

La salida es una validación de la implementación, no un resultado del TSP
español. ACO es estocástico; tres semillas no permiten inferir rendimiento
general ni reemplazan las 30 corridas por configuración previstas para el
estudio final.

## Relación con ACO y GA

`NearestNeighbor`, `TwoOpt`, `NearestNeighborTwoOpt` y `AntSystem` implementan
la firma estructural `run(problem, seed, budget, **params) -> TSPRunResult` y
consumen los mismos `TSPObjective` y `RunEvaluator`. Un GA puede usar la misma
instancia y el mismo presupuesto sin que se cambien sus operadores. En la rama
revisada todavía no hay código de GA que permita comprobar su integración de
extremo a extremo.

Vecino más cercano y 2-opt son heurísticas deterministas dadas la semilla y la
instancia; ACO es una metaheurística poblacional estocástica. Ninguna de estas
heurísticas demuestra optimalidad para instancias grandes. El óptimo exacto solo
se usa aquí como referencia en instancias pequeñas.
