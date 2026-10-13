# Instancia vial nacional TSP — España peninsular (2026)

Datos adquiridos mediante openrouteservice Matrix (`driving-car`) el 2026-10-12T22:14:41.568892-05:00 (hora Bogotá); el timestamp UTC y el timestamp del proveedor constan en `metadata.json`. Se solicitaron distancia y duración en unidades originales m/s, con 47 orígenes y 47 destinos en orden canónico. Matrix utiliza la preferencia predeterminada de su endpoint; no se etiqueta como la estrategia `fastest` de Directions. ORS no informó la versión de su grafo.

Incluye distancias dirigidas, duraciones y tres escenarios de combustible. Las distancias se convierten m/1000 a km; las duraciones s/3600 a horas. No incluye tarifas de peaje ni matriz de costo económico total.

## Licencias de datos

Los resultados Matrix de openrouteservice y las matrices de combustible derivadas se distribuyen bajo CC BY-SA 4.0 conforme a los términos HeiGIT de la cuenta. Atribución: **© openrouteservice by HeiGIT | Data from OpenStreetMap**. El catálogo de ciudades conserva CC BY 4.0 del IGN según su procedencia. También incluimos el aviso ODbL para OpenStreetMap: ODbL y CC BY-SA no son intercambiables. Véase `LICENSE-DATA.md`.

## Archivos y unidades

`cities.csv` conserva el orden canónico y procedencia IGN; `distance_km.csv` está en km; `duration_hours.csv` en horas; las tres matrices `fuel_*_eur.csv` están en EUR. Las matrices son dirigidas: fila = origen, columna = destino; la diagonal es cero. CSV tiene etiquetas de fila y columna, así que contiene 48×48 campos con 47×47 valores numéricos.

## Uso offline

Desde la raíz del repositorio: `python -c "from src.tsp.etl.dataset_export import load_published_dataset; d=load_published_dataset('data/datasets/spain_tsp_2026'); print(d['city_order'][:3], d['distance_km'].shape)"`. La carga valida hashes y orden. No construye costos totales porque los peajes siguen sin estar completos.

## Combustible y peajes

Precio: Eurosuper 95, 1.849098398 EUR/L, Weekly Oil Bulletin de la Comisión Europea publicado el 2026-10-08 y consultado el 2026-10-12. BMW 120 F70, 5.4 L/100 km de referencia, con escenarios 5.3/5.5. Fórmula: `distance_km / 100 × consumption_l_100km × price_eur_l`. La fecha efectiva de descarga del boletín no quedó registrada. Los peajes no están incorporados; un importe desconocido no se reemplaza por cero.

## Atribución

Rutas: © openrouteservice by HeiGIT. Datos cartográficos: © OpenStreetMap contributors, ODbL. Coordenadas de ciudades: IGN, CC BY 4.0, según procedencia del catálogo. Ver `metadata.json`.
