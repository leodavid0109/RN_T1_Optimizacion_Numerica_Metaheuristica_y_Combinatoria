# Publicación del dataset nacional TSP

Consulta y revisión documental: 2026-10-12. Términos HeiGIT de cuenta revisados por el integrante 3 en `https://account.heigit.org/info/tos`, sección **Attribution and License — openrouteservice**. El documento citado no muestra número de versión ni fecha de vigencia; se registra la fecha de consulta.

## Paquete y reconstrucción

El paquete `data/datasets/spain_tsp_2026/` contiene las 47 ciudades, distancia dirigida en km, duración dirigida en horas, combustible de referencia/bajo/alto en euros, metadatos, README, aviso de licencia y SHA-256. No contiene respuesta HTTP cruda, geometrías ORS, archivos temporales ni peajes. El snapshot local de origen tiene SHA-256 `ea9c13d6a0c35bf3db3603be8e53372f94c5154682a9bf1d5a69c9e6a59ebf30`; el hash de la respuesta Matrix es `8660e42cb511a530e5dfeb2dea003af50b2013dc03cebedd74276d2eebab1d9e`.

El exportador offline está en `experiments/export_spain_tsp_dataset.py`. Para reconstruir, se necesita el snapshot local ignorado de ORS:

```powershell
python -m experiments.export_spain_tsp_dataset --snapshot data/raw/routes/openrouteservice_driving-car_matrix_d762a01753af5a8418af_8660e42cb511a530e5dfeb2dea003af50b2013dc03cebedd74276d2eebab1d9e.json
```

Los tres integrantes pueden cargar el dataset publicado sin conexión ni acceso a `data/raw`/`data/processed`:

```powershell
python -c "from src.tsp.etl import load_published_dataset; d=load_published_dataset('data/datasets/spain_tsp_2026'); print(len(d['city_order']), d['distance_km'].shape)"
```

El cargador comprueba hashes, IDs y orden canónico; el exportador valida dimensiones, valores finitos/no negativos, diagonal cero, arcos dirigidos y fórmula de combustible. Los CSV conservan 47×47 valores numéricos (más la columna/fila de IDs). La adquisición del Matrix fue `driving-car`, métricas distancia y duración, unidad original `m` para distancia y `s` para duración. Se normalizó `m / 1000 = km` y `s / 3600 = h`. El endpoint usó la preferencia predeterminada del servicio; no se iguala a `fastest` de Directions. La versión del grafo no está informada.

El combustible se calcula `distancia_km / 100 × consumo_L_100km × precio_EUR_L`, con BMW 120 F70, 5,4 L/100 km de referencia y sensibilidades 5,3/5,5; precio derivado del Weekly Oil Bulletin de la Comisión Europea publicado el 2026-10-08, consultado el 2026-10-12. La fecha efectiva de descarga del XLSX no se registró y se mantiene desconocida.

## Licencias distintas para datos distintos

- **Resultados ORS Matrix y matrices de combustible derivadas:** CC BY-SA 4.0, conforme a los términos de cuenta indicados arriba. Atribución exigida por HeiGIT: **© openrouteservice by HeiGIT | Data from OpenStreetMap**. Conservar el aviso de licencia, identificar transformaciones/cambios y compartir adaptaciones de estos resultados bajo CC BY-SA 4.0.
- **Catálogo de ciudades:** CC BY 4.0 para las coordenadas procedentes de IGN, con procedencia individual en `cities.csv`.
- **OpenStreetMap:** se da crédito a OpenStreetMap y se enlaza la ODbL 1.0. La matriz contiene métricas producidas por el motor de rutas; no se distribuye un extracto de carreteras, geometrías ni atributos viales OSM. Conforme a la guía OSMF de atribución para motores de rutas, se conserva la atribución y el vínculo de licencia. Esto no convierte ODbL y CC BY-SA en licencias equivalentes ni aplica una en sustitución de la otra. Si una ampliación incorporara una base derivada de OSM, habría que cumplir por separado ODbL Share-Alike y acceso a esa base/alteraciones antes de distribuirla.
- **Código:** el aviso de datos no licencia el software. El repositorio no contiene un `LICENSE` general de código; no se afirma una licencia de código que no exista.

Creative Commons BY-SA 4.0 cubre los derechos licenciados por el proveedor, incluidos los derechos sui generis de base de datos cuando correspondan; sus condiciones de atribución/share-alike no sustituyen las obligaciones independientes de ODbL si se distribuyera una base derivada OSM. No se identificó una incompatibilidad concreta para este paquete de métricas de rutas sin contenido de red OSM; se conservan atribución y enlace ODbL, y se deja documentado el límite de alcance.

Fuentes oficiales revisadas el 2026-10-12:

- Términos de la cuenta HeiGIT, sección **Attribution and License — openrouteservice**: https://account.heigit.org/info/tos
- Texto legal CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/legalcode
- ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/
- Guía de atribución OSMF: https://osmfoundation.org/wiki/Attribution_Guidelines
- Copyright y licencia de OpenStreetMap: https://www.openstreetmap.org/copyright

## Alcance económico

No se incluyen importes de peajes; peaje desconocido no significa cero. Las matrices de distancia, duración y combustible no forman una matriz económica completa `v*T + P + F`. ACO y GA pueden usar estos componentes offline al construir una instancia cuya función objetivo esté definida con sus componentes verificables; no debe etiquetarse como resultado económico final mientras falten tarifas.
