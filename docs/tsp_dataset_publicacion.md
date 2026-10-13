# Dataset nacional TSP: preparación y estado de redistribución

Consulta de licencias: 12 de octubre de 2026.

## Qué se prepara

`experiments/export_spain_tsp_dataset.py` crea offline `data/datasets/spain_tsp_2026/` desde el snapshot Matrix local validado y el catálogo canónico. Produce ciudades, distancias en km, duraciones en horas, matrices de combustible low/reference/high en EUR, metadatos, README, aviso de licencia y hashes SHA-256. Los números CSV se emiten con 17 cifras significativas y LF, sin modificar el snapshot de origen. `metadata.json` identifica el hash de respuesta (`8660e42cb511a530e5dfeb2dea003af50b2013dc03cebedd74276d2eebab1d9e`), el hash del contenedor crudo y los hashes de CSV. `SHA256SUMS.txt` cubre los archivos generados, incluido `metadata.json`.

Ejemplo de exportación, sin red:

```powershell
python -m experiments.export_spain_tsp_dataset --snapshot data/raw/routes/openrouteservice_driving-car_matrix_d762a01753af5a8418af_8660e42cb511a530e5dfeb2dea003af50b2013dc03cebedd74276d2eebab1d9e.json
```

Carga offline y verificación de hashes:

```powershell
python -c "from src.tsp.etl import load_published_dataset; d=load_published_dataset('data/datasets/spain_tsp_2026'); print(len(d['city_order']), d['distance_km'].shape, d['duration_hours'].shape)"
```

El cargador entrega las matrices de distancia, duración y combustible. No ofrece una matriz económica total: los peajes siguen incompletos y desconocidos no equivalen a cero. La matriz de combustible se calcula como `km / 100 × L/100 km × EUR/L`; se excluyen mantenimiento, seguro y depreciación.

## Decisión de publicación

Los CSV reales se preparan localmente, pero **no se agregan a Git ni se publican en GitHub en esta etapa**. `.gitignore` mantiene excluidos `data/raw/routes/` y `data/processed/matrices/`; no se relajan esas exclusiones. El paquete local de preparación se deja sin seguimiento de Git hasta cerrar los derechos.

La página pública [ORS Terms of Service](https://openrouteservice.org/terms-of-service/) redirige actualmente a los términos de la cuenta alojados en `account.heigit.org`, cuyo contenido no es accesible públicamente en la consulta realizada. La respuesta de un representante del foro ORS/HeiGIT del 12-10-2026 afirma que los resultados se licencian CC BY-SA 4.0 y remite a los términos; en ese mismo hilo el representante expresa que HeiGIT no está cualificado para resolver la interpretación jurídica. Otra página pública de términos consultada/indexada se refiere a CC BY 4.0. La discrepancia no se resuelve suponiendo que una atribución de respuesta del API sea una licencia.

El campo `results_license` existente en el JSON local fue escrito por `RouteStore` como anotación propia, no proviene del cuerpo original de Matrix. No constituye evidencia contractual ni metadato devuelto por el servidor. La respuesta original incluye atribución `openrouteservice.org | OpenStreetMap contributors`; no declara por sí misma una licencia de redistribución.

Además, OpenStreetMap se distribuye bajo [ODbL](https://www.openstreetmap.org/copyright). La OSM Foundation requiere atribución y, para bases de datos, incluir atribución y texto/enlace de ODbL en la base, base derivada o base colectiva. No está determinado aquí si una tabla de 2.162 distancias/duraciones de rutas constituye una base derivada relevante, ni cómo reconciliar obligaciones ODbL con la licencia de salida ORS. La licencia de metadatos de OSM no decide por sí sola el régimen de la salida calculada.

Por estas razones no se asigna todavía CC BY 4.0, CC BY-SA 4.0 ni ODbL como licencia única del conjunto. `LICENSE-DATA.md` local es un aviso de no redistribución, no una concesión de derechos. Antes de publicar hace falta conservar los términos exactos aceptados por la cuenta ORS usada y obtener confirmación inequívoca del régimen aplicable a resultados Matrix (incluida redistribución persistente en repositorio público), además de resolver documentalmente la interacción con ODbL. Si los términos solo permiten CC BY-SA, la licencia y atribución del paquete deberán reflejarlo y el equipo tendrá que confirmar que puede cumplir sus condiciones.

## Procedencia y alcance económico

- ORS Matrix `driving-car`, perfil de automóvil; Matrix devolvió distancias y duraciones. No se informó una versión del grafo/mapa.
- La preferencia de ruta guardada se registra como valor predeterminado del endpoint, no como `fastest` de Directions.
- La consulta local del snapshot ocurrió a las 2026-10-12 22:14:41 hora de Bogotá (2026-10-13T03:14:41Z). La fecha real de descarga del precio de combustible no está registrada; se conserva `null`, no se inventa.
- Coordenadas del catálogo: IGN, procedencia indicada por registro.
- Combustible: BMW 120 F70, supuesto representativo de 5,4 L/100 km, con escenarios 5,3 y 5,5; precio reportado por el boletín oficial de 2026-10-08, normalizado desde EUR/1000 L.
- Peajes no incluidos. No existe una matriz de costo económico total ni afirmación de optimalidad sobre la matriz nacional.

## Fuentes consultadas

- [Términos ORS](https://openrouteservice.org/terms-of-service/) — consultados 2026-10-12; redirigen a términos de cuenta autenticados.
- [Respuesta de HeiGIT/ORS sobre CC BY-SA 4.0](https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079) — publicada 2026-10-12.
- [Respuesta de HeiGIT/ORS sobre almacenamiento persistente de Matrix](https://ask.openrouteservice.org/t/persistent-storage-and-reuse-of-matrix-api-duration-results/8010) — publicada 2026-08-27; condiciona el uso a los términos.
- [OSMF Attribution Guidelines](https://osmfoundation.org/wiki/Attribution_Guidelines) — adoptadas 2021-06-25; página consultada 2026-10-12.
- [OSM Copyright and License](https://www.openstreetmap.org/copyright) — consultado 2026-10-12.

El aviso local `data/datasets/spain_tsp_2026/LICENSE-DATA.md` registra esta decisión junto al paquete preparado.
