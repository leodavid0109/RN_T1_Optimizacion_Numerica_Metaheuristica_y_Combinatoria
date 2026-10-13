# Inspección local de estaciones de peaje

## Reproducir el informe y el mapa

Desde la raíz del repositorio, sin conexión:

```powershell
.\.venv\Scripts\python.exe -m experiments.report_tsp_toll_stations
```

El informe lee el GeoJSON consolidado de Overpass y las alternativas Directions
guardadas. Escribe `toll_stations.csv`, `station_route_candidates.csv`,
`toll_station_review.geojson`, `overpass_station_followup_plan.json` y
`toll_stations_summary.md` en `data/processed/tolls/station_review/`. Estos
resultados contienen datos derivados de OSM y quedan en el directorio local
ignorado por Git mientras se revisan los permisos de redistribución. El GeoJSON
puede abrirse en QGIS; tiene líneas de las tres rutas y puntos OSM con enlaces,
etiquetas y candidatos de ruta. La geometría no usa mapa de fondo ni requiere
red.

El programa considera candidatas a estaciones a menos de 100 m de la línea;
ese radio es un parámetro de búsqueda, no un umbral probatorio. Calcula
distancia al polyline, punto más próximo y fracción aproximada de recorrido.
Solo asigna `MATCHED_ROAD` cuando una `ref` explícita de la estación coincide
con referencias de la ruta. No asigna `POSSIBLE_PASSAGE` ni
`PASSAGE_VERIFIED`: requieren evidencia adicional y revisión humana. Todos los
importes permanecen nulos.

## Estado de los datos locales

El snapshot consolidado tiene 168 objetos OSM únicos; 13 son nodos
`toll_booth`. Todos tienen coordenadas puntuales válidas. Dos tienen nombre y
operador, ninguno tiene `ref`, etiquetas `addr:*`, `direction` ni `highway`.
Los dos puntos «Peaje de Alagon» se conservan bajo IDs diferentes. Las
coordenadas próximas pueden representar cabinas/carriles distintos, pero no
se agrupan con inferencias. Solo el nombre y operador que OSM registra están
en la tabla; no se geocodifican direcciones ausentes.

El inventario cubre dos cajas locales y tiene una región fallida (HTTP 504) y
32 pendientes. No es un censo. Cuatro relaciones estación–ruta quedan dentro
de 100 m para los dos sentidos Bilbao–Zaragoza; son los dos nodos «Peaje de
Alagon» frente a ambas rutas. Las rutas rápidas contienen la referencia
`AP-68`, evidencia de corredor, pero eso no demuestra cuál estación se cruzó.
No hay estaciones del inventario dentro del radio establecido para
Madrid–Toledo. Ese resultado no certifica que la ruta sea gratuita.

## Correspondencia con AP-68

El [tarifario oficial 2026 de Autopistas/AVASA](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf)
enumera estaciones para la tabla de ligeros: Bilbao, Arrigorriaga, Llodio,
Ziorroga, Altube, Subijana, Enlace AP-1, Zambrana, Haro, Cenicero, Navarrete,
Logroño, Recajo, Agoncillo, Lodosa, Calahorra, Alfaro, Enlace AP-15, Tudela,
Gallur, Alagón 272 y Zaragoza. La tabla publica 39,90 € para el par nominal
Bilbao–Zaragoza, con vigencia indicada desde 2026-01-01.

El nombre OSM «Peaje de Alagon» es una candidata textual/geográfica para
investigar respecto de «Alagón 272», no una correspondencia validada. OSM no
proporciona entrada, salida, sentido, tarifa, categoría ni condiciones en
estos dos nodos. El tarifario no da coordenadas de cabinas para demostrar
coincidencia con el polyline. No se asigna 39,90 € a ninguno de los dos arcos.

## Solicitud puntual Overpass preparada

`overpass_station_followup_plan.json` contiene dos consultas planificadas, no
ejecutadas: una por los IDs conocidos de nodos y otra que busca nodos,
pórticos y vías con etiquetas de peaje dentro de círculos de 100 m alrededor
de los candidatos del corredor AP-68. Cada consulta equivale a un HTTP y no
tiene reintentos. Si se autoriza, invocar cada consulta con el método
`OverpassClient.fetch_way_ids_payload` para los IDs o con el cliente acotado
existente para la consulta localizada, y persistir en
`OverpassCatalogStore.get_or_fetch_way_ids` cuando aplique. La consulta por ID
reutiliza resultados exitosos y guarda fallos 504 para reanudarlos; la
consulta por radio aún requiere un adaptador de consulta acotada y su estado
incremental antes de ejecutarse como lote automatizado.

Los IDs de vía de ORS Extra Info permiten pedir etiquetas y geometría de vías
concretas en vez de repetir cajas regionales. Todavía no hay respuestas ORS
enriquecidas reales guardadas: el próximo paso es adquirir las tres rutas
planificadas en la fase anterior y comprobar `tollways`, `osmId` y
`waycategory`. Aun así, esos atributos no resuelven por sí solos entrada y
salida tarifarias; deberán cruzarse con planos/listas oficiales de accesos y
la tarifa de la categoría ligera, fecha y modalidad pertinentes.

El cliente Overpass permite consultar lotes de hasta 50 IDs conocidos por
solicitud mediante `fetch_node_ids_payload` / `get_or_fetch_node_ids` para
nodos y `fetch_way_ids_payload` / `get_or_fetch_way_ids` para vías. Las
consultas usan el tipo OSM explícito, ordenan y deduplican el lote, conservan
la respuesta original en la caché local y no reintentan HTTP 504. La prueba
automatizada simula las respuestas; no implica que se haya llamado al
servicio durante esta fase. El plan por radio del informe también es solo un
artefacto pendiente, no ejecutado.

## Fuentes

- ORS [Extra Info](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/) y [categorías](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/waycategory), consultadas 2026-10-13. La disponibilidad publicada marca los tres atributos para `driving-car`; la adquisición real sigue pendiente. `waycategory` es una máscara de bits (`3` combina `Highway` y `Tollways`).
- [Tarifario AP-68 2026](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf), página 1; consultado 2026-10-13.
- OpenStreetMap contributors, fuente de los objetos del snapshot local; atribución y licencia ODbL documentadas en `data/fuentes.md`.
