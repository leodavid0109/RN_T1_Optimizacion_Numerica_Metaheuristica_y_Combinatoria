# TSP España — matrices económicas experimentales (13-10-2026)

Este paquete permite ejecutar offline matrices finitas para experimentación. No es un tarifario real completo ni prueba que los precios estimados sean exactos.

## Escenario

Martes 13-10-2026, 12:00 hora peninsular; turismo ligero BMW 120 F70; pago general sin descuentos; combustible 5,4 L/100 km a 1,849098398 EUR/L; valor del tiempo 10, 25 o 50 EUR/h.

## Archivos

- `model_a_v{10,25,50}_eur.csv`: ruta rápida ORS, costes numéricos con los supuestos descritos.
- `model_b_v{10,25,50}_eur.csv`: misma matriz mientras no haya alternativa libre enriquecida válida.
- `model_b_choice_v{10,25,50}.csv`: todas las celdas no diagonales indican `FASTEST_ONLY`.
- `model_a_{low,high}_v*_eur.csv` y `model_b_{low,high}_v*_eur.csv`: sensibilidad al 50/150 % del proxy central.
- `strict/`: matrices estrictas parciales; celdas vacías siguen siendo UNKNOWN.
- `toll_evidence.csv`, `toll_components.csv`, `toll_fastest_eur.csv`: trazabilidad por arco.
- `toll_corridor_usage_candidates.csv`, `corridor_frequency_candidates.csv`: intervalos/etiquetas candidatos; no son un inventario espacial único certificado.
- `toll_corridor_catalog.csv`, `official_tariff_transcriptions_source.csv`, `osm_station_catalog_partial.csv`: referencias locales, con atribución y alcance parcial.
- `alternatives_inventory.csv`: seis opciones históricas sin extras completos; excluidas del Modelo B.
- `validation_sample_30.csv`: 30 arcos revisados estructuralmente por estratos; no son una muestra de ground truth tarifario independiente.
- `cities.csv`: catálogo ordenado de 47 ciudades; coincide con el dataset vial base.
- `avoid_tolls_pending.csv`: cola pendiente de rutas con tollways positivos, ordenada por coste proxy (priorización, no garantía de ahorro).
- `break_even_value_of_time.csv`: no calculado donde no existe alternativa libre validada.
- `metadata.json`, `LICENSE-DATA.md`, `SHA256SUMS.txt`: parámetros, límites, atribución y hashes.

## Matriz recomendada para la prueba del compañero

Para probar ACO o GA con peajes, cargue `model_a_v25_eur.csv`: es el Modelo A experimental base, en EUR por arco dirigido, con valor del tiempo de 25 EUR/h. Use el orden de `cities.csv`, cierre el tour regresando a su ciudad inicial y entregue a ambos algoritmos exactamente la misma matriz y presupuesto de evaluaciones. 25 EUR/h es el escenario central entre las sensibilidades, no una estimación oficial del valor social del tiempo.

El supuesto de recorrido completo se aplica solo a pares concretos con corredor indicado por ORS: AP-68 Bilbao–Zaragoza (39,90 EUR por sentido), AP-9 A Coruña–Pontevedra (8,80 + 7,55 = 16,35 EUR por sentido) y C-32 Tarragona–Barcelona (8,42 EUR de la barrera Vallcarca, una vez por sentido). Son inferencias de recorrido completo, no verificaciones de accesos ni de todos los eventos de cobro. No se extiende una tarifa a otros arcos por mencionar la autopista.

Para el baseline sin peajes, cargue `data/datasets/spain_tsp_2026/baseline_cost_v_25_eur.csv`. No interprete la diferencia con Modelo A como efecto tarifario exacto: este escenario combina ceros asumidos e importes proxy.

## Supuestos de peaje

Si ORS devuelve extras completos y no marca tramos tollways, se usa `ZERO_ASSUMED_ORS` (supuesto, no verificación oficial). Las rutas con pares tarifarios previamente inferidos conservan esos importes como inferencias. Los demás tramos positivos usan 0,14145 EUR por km tollways en la matriz base; sensibilidad: 0,070725 y 0,212175 EUR/km. El proxy no describe literalmente un sistema de tarifa por km ni es estadísticamente validado.

## Modelo B y adquisición

El piloto de 20 `avoid_tolls` dejó 20 rechazos de conexión sin código HTTP ni respuesta. Un intento posterior con permisos ampliados se interrumpió sin resumen, por lo que se desconoce cuántos intentos adicionales alcanzó a iniciar. No hay alternativas nuevas persistidas. Por ello el Modelo B numérico equivale al fastest-only y no debe describirse como comparación de rutas rápidas y libres. Revise diagnósticos y cuota antes de reintentar.

## Reproducción offline

Desde la raíz del repositorio: `python -m experiments.build_tsp_economic_bundle`. No necesita internet ni ORS_API_KEY.

## Atribución

Resultados ORS: © openrouteservice by HeiGIT | Data from OpenStreetMap, bajo CC BY-SA 4.0 según términos de cuenta consultados. Datos OSM: © OpenStreetMap contributors, ODbL 1.0. El catálogo parcial de estaciones conserva solo entidades cartográficas y no acredita el paso de una ruta ni un pago. Revisar licencias y atribución antes de redistribuir este paquete.
