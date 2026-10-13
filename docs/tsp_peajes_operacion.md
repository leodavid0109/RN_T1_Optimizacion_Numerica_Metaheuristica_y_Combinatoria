# Valoración offline de peajes y demostración ACO

Este flujo usa el dataset nacional versionado, el catálogo ORS local y transcripciones revisadas de tarifarios. Los comandos se ejecutan desde la raíz del repositorio con `.venv\Scripts\python.exe` en PowerShell. Ningún comando de esta página consulta una API.

## AP-68: tarifa oficial frente a peaje de una ruta

El CSV local `data/processed/tolls/ap68_2026_ligeros.csv` transcribe dos celdas nominales del [tarifario AVASA AP-68 2026](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf): Bilbao→Zaragoza y Zaragoza→Bilbao, 39,90 EUR por sentido para ligeros, sin descuentos, vigencia de referencia 2026-01-01 a 2026-11-10. Su hash, documento y página quedan en el manifiesto de importación. La fuente no demuestra que las geometrías ORS entren y salgan exactamente por esas estaciones.

```powershell
.venv\Scripts\python.exe -m experiments.import_tsp_toll_tariffs --input data/processed/tolls/ap68_2026_ligeros.csv --output data/processed/tolls/imported_ap68
.venv\Scripts\python.exe -m experiments.prepare_ap68_evidence
.venv\Scripts\python.exe -m experiments.build_tsp_economic --tariffs data/processed/tolls/imported_ap68/tariffs_normalized.csv --evidence data/processed/tolls/ap68_route_evidence.json --hour-value 25
.venv\Scripts\python.exe -m experiments.report_tsp_toll_coverage
```

La importación genera `tariffs_normalized.csv` y `tariffs_manifest.json`. La preparación crea `ap68_route_evidence.json` con IDs y hashes de las dos rutas rápidas locales. Si existe el informe Overpass local, conserva como candidatos la relación AP-68 y las estaciones cercanas, sin elevarlos a tránsito confirmado. Sus estaciones de entrada/salida se dejan ausentes, `route_match_verified=false`, `inventory_complete=false` y `matrix_route_equivalent=false`. El constructor produce `economic_arcs.csv` y `summary.json`; las columnas de costo total permanecen vacías cuando faltan peajes verificados. `--require-complete` bloquea expresamente una matriz densa incompleta. El reporte produce JSON, CSV por arco y `toll_pending_priority.csv`.

La evidencia de una ruta se registra por `route_id`, origen/destino, SHA-256 de la geometría, secciones con estación de entrada/salida, sentido y fuentes. `inventory_complete=true` exige revisión documentada de **todos** los posibles cobros, incluidos accesos y peajes fuera de AP-68. Para trasladar un peaje Directions a una celda Matrix se exige además `matrix_route_equivalent=true` y una fuente que pruebe esa equivalencia. Una coincidencia OSM o un importe de una estación aislada permite estado `PARTIAL`, nunca `VERIFIED_AMOUNT`. `VERIFIED_ZERO` exige cobertura completa y prueba explícita de gratuidad. Los archivos de rutas y tarifas locales siguen excluidos de Git.

## Prueba sintética completa

```powershell
.venv\Scripts\python.exe -m experiments.tsp_toll_synthetic_demo
```

El ejemplo sintético de dos ciudades verifica 3 EUR en un sentido y 0 EUR en el otro, con costo cerrado de 27 EUR a 10 EUR/h. Es una prueba del software y **no** evidencia de tarifas españolas.

## ACO auxiliar sobre las 47 capitales

```powershell
.venv\Scripts\python.exe -m experiments.tsp_aco_spain_auxiliary --hour-values 10,25,50 --seed 42 --budget 30
```

Lee `data/datasets/spain_tsp_2026/`, valida hashes y orden, y usa `c_aux(i,j;v)=v*T_matrix(i,j)+F_matrix(i,j)`. **Escenario auxiliar de validación algorítmica — no representa el costo económico total.** El archivo local `aco_auxiliary.json` registra orden, costo auxiliar, tiempo, combustible, convergencia, evaluaciones y duración de ejecución. Los peajes no se valoran ni se registran como cero verificado.

## Cola nacional reanudable

```powershell
.venv\Scripts\python.exe -m experiments.plan_tsp_direction_queue --batch-size 5
```

El universo contiene 2.162 arcos dirigidos. La cola excluye rutas rápidas con geometría existente y se recalcula offline tras cada lote, por lo que se reanuda sin duplicados. La prioridad inicial es la duración Matrix descendente, con desempate por IDs; esta regla identifica trayectos donde las alternativas pueden tener mayor efecto temporal, pero no prueba presencia de peajes. El plan imprime los primeros pares. Para **planificar** un lote concreto, sin llamadas:

```powershell
.venv\Scripts\python.exe -m experiments.acquire_tsp_routes --pairs 'ID_ORIGEN:ID_DESTINO,ID_ORIGEN:ID_DESTINO' --strategy fastest --max-requests 2 --max-http-requests 2 --max-retries 0
```

La adquisición requeriría autorización separada y `--execute`; el cliente ORS existente aplica los límites HTTP y conserva sus checkpoints. No se planifican aquí nuevas consultas.

## Pendientes de AP-68 y alcance nacional

Para ambos sentidos Bilbao–Zaragoza faltan entrada y salida tarifarias, calzada/sentido verificables, peajes adicionales y conciliación geométrica Directions/Matrix. Por ello, la cobertura económica nacional sigue incompleta. El Modelo B necesita además alternativas con peajes totalmente verificados; el conjunto conocido no se presume exhaustivo. No se puede alimentar el objetivo económico completo a ACO o GA hasta cubrir todos los arcos requeridos. El escenario auxiliar sí permite comprobar el funcionamiento de ACO con datos viales reales, sin interpretar sus costos como resultado final del problema.
