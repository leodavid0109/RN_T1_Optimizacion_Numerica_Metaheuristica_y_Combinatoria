# Fundamentos del módulo TSP

Esta página resume la base común de la Parte 2. El catálogo vigente de 47 capitales, sus coordenadas IGN y el piloto OSRM se describen en [`data/fuentes.md`](../data/fuentes.md). La implementación de modelos de trayectos rápidos fijos y alternativas económicas se documenta en [`tsp_modelo_dual.md`](tsp_modelo_dual.md).

## Componentes

- `src/tsp/cities.py`: catálogo canónico y validación de las ciudades.
- `src/tsp/matrices.py`: carga/validación de matrices cuadradas, finitas, no negativas, dirigidas e inmutables.
- `src/tsp/problem.py`: `TSPProblem`, evaluación de rutas cerradas y desglose `RouteCost`.
- `src/tsp/alternatives.py` y `src/tsp/models.py`: catálogo tipado y selección entre alternativas para los modelos A y B.
- `src/tsp/contracts.py`: `TSPObjective`, el contrato estructural común, y resultados de algoritmos.
- `src/tsp/evaluation.py`: presupuesto de evaluaciones completas e historial de mejoras.

## Evaluación básica

Una ruta válida es una permutación de índices `0..N-1`. El evaluador añade explícitamente el retorno al primer nodo y suma los N arcos dirigidos. Para matrices de componentes, `C(v) = v*T + P + F`; variar `v` no modifica las matrices. No se impone simetría.

El presupuesto de algoritmos mide llamadas completas de permutación a `RunEvaluator.evaluate`. Costos parciales y generación de matrices no cuentan. El historial registra el mejor costo en el número de evaluaciones correspondiente.

## Evidencia

Las pruebas del núcleo usan una instancia pequeña sintética; las del catálogo verifican datos del repositorio contra su snapshot IGN. Los fixtures sintéticos sirven para validación matemática y no se interpretan como distancias, tiempos, tarifas, combustible ni resultados de España. Las fuentes reales, fechas y límites se mantienen en `data/fuentes.md`.
