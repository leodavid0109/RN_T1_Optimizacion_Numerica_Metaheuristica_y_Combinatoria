# Instancia vial nacional TSP — España peninsular (2026)

Datos adquiridos mediante openrouteservice Matrix (`driving-car`) el 2026-10-12T22:14:41.568892-05:00 (hora Bogotá); el timestamp UTC y el timestamp del proveedor constan en `metadata.json`. Se solicitaron distancia y duración en unidades originales m/s, con 47 orígenes y 47 destinos en orden canónico. Matrix utiliza la preferencia predeterminada de su endpoint; no se etiqueta como la estrategia `fastest` de Directions. ORS no informó la versión de su grafo.

Incluye distancias dirigidas, duraciones y tres escenarios de combustible. Las distancias se convierten m/1000 a km; las duraciones s/3600 a horas. No incluye tarifas de peaje ni matriz de costo económico total.

## Licencias de datos

Los resultados Matrix de openrouteservice y las matrices de combustible derivadas se distribuyen bajo CC BY-SA 4.0 conforme a los términos HeiGIT de la cuenta. Atribución: **© openrouteservice by HeiGIT | Data from OpenStreetMap**. El catálogo de ciudades conserva CC BY 4.0 del IGN según su procedencia. También incluimos el aviso ODbL para OpenStreetMap: ODbL y CC BY-SA no son intercambiables. Véase `LICENSE-DATA.md`.

## Archivos y unidades

`cities.csv` conserva el orden canónico y procedencia IGN; `distance_km.csv` está en km; `duration_hours.csv` en horas; las tres matrices `fuel_*_eur.csv` están en EUR. Las matrices son dirigidas: fila = origen, columna = destino; la diagonal es cero. CSV tiene etiquetas de fila y columna, así que contiene 48×48 campos con 47×47 valores numéricos.

## Uso offline

El cargador del repositorio comprueba los hashes, el orden y las matrices base. Ejemplo para consultar un arco y evaluar un tour cerrado (incluye retorno a la primera ciudad):

```python
from src.tsp.etl.dataset_export import load_published_dataset

data = load_published_dataset("data/datasets/spain_tsp_2026")
index = {city_id: i for i, city_id in enumerate(data["city_order"])}
i, j = index["madrid"], index["toledo"]
print("Madrid → Toledo, v=25:", data["baseline_cost_v_25_eur"][i, j], "EUR")

tour_ids = ["madrid", "toledo", "caceres"]  # demostración; no es una solución TSP
tour = [index[city] for city in tour_ids]
closed = tour + [tour[0]]
for value in (10, 25, 50):
    matrix = data[f"baseline_cost_v_{value}_eur"]
    total = sum(float(matrix[a, b]) for a, b in zip(closed, closed[1:]))
    print(f"Baseline sin peajes, v={value}: {total:.6f} EUR")
```

El módulo ACO consume un `TSPObjective`; no se añade un GA en esta entrega porque todavía no está integrado en esta rama. Las matrices CSV quedan disponibles para que el GA compartido las cargue por el mecanismo que implemente su integrante. No se necesita clave ni conexión de red para leer el paquete.

## Combustible y peajes

Precio: Eurosuper 95, 1.849098398 EUR/L, Weekly Oil Bulletin de la Comisión Europea publicado el 2026-10-08 y consultado el 2026-10-12. BMW 120 F70, 5.4 L/100 km de referencia, con escenarios 5.3/5.5. Fórmula: `distance_km / 100 × consumption_l_100km × price_eur_l`. La fecha efectiva de descarga del boletín no quedó registrada. Los peajes no están incorporados; un importe desconocido no se reemplaza por cero.

## Atribución

Rutas: © openrouteservice by HeiGIT. Datos cartográficos: © OpenStreetMap contributors, ODbL. Coordenadas de ciudades: IGN, CC BY 4.0, según procedencia del catálogo. Ver `metadata.json`.


## Rutas ORS enriquecidas

Se distribuyen las 2.162 geometrías dirigidas `fastest` como JSON Lines UTF-8 comprimidos en gzip determinista (`mtime=0`), en shards ordenados por el catálogo, dentro de `routes/ors_enriched/`. Cada registro incluye distancia y duración originales en m/s, geometría WGS84, `tollways`, `waycategory`, IDs estables, hashes y fecha de adquisición. `osmId` no fue devuelto por el servicio público en estas respuestas. La clasificación de segmentos es cartográfica, no una tarifa monetaria ni prueba de cobro.

`routes/ors_enriched/manifest.json` enumera filas, unidades, atribución y SHA-256 de cada shard. El empaquetado se puede reproducir offline con `python -m experiments.export_tsp_spain_publication` si se conservan los snapshots originales locales y el análisis generado por `python -m experiments.analyze_tsp_ors_extras`.

Las matrices `baseline_cost_v_10_eur.csv`, `baseline_cost_v_25_eur.csv` y `baseline_cost_v_50_eur.csv` calculan `v*T + combustible`. Son **BASELINE SIN COMPONENTE DE PEAJES**, no equivalen a rutas gratuitas ni a un costo económico total.
