# Fuentes de datos del TSP

## Migración del endpoint ORS Directions (2026-10-13)

- HeiGIT anunció la migración desde `api.openrouteservice.org` hacia `api.heigit.org`: https://ask.openrouteservice.org/t/deprecating-api-openrouteservice-org-in-favour-of-api-heigit-org/7912 . El endpoint configurado para Directions es `https://api.heigit.org/openrouteservice/v2/directions`; Matrix conserva `https://api.heigit.org/openrouteservice/v2/matrix`.
- La referencia de [Directions Extra Info](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/) se consultó el 2026-10-13. Su tabla actual marca `tollways`, `waycategory` y `osmid` disponibles para `driving-car`, con respuesta de OSM IDs bajo `osmId`. El primer intento controlado, por decisión de alcance, solicita solo `tollways` y `waycategory`; disponibilidad documentada no sustituye la validación en una respuesta real. Los atributos cartográficos no proporcionan importes tarifarios.
- La petición anterior Madrid–Toledo terminó en timeout de transporte después de un intento contabilizado, sin código HTTP. No se infiere si el backend alcanzó a procesarla. No se realizó una nueva solicitud durante esta corrección.

## Consulta documental Matrix ORS (2026-10-12)

- Documentación del endpoint Matrix: https://giscience.github.io/openrouteservice/api-reference/endpoints/matrix/ . Define locations como coordenadas, permite fuentes/destinos como subconjuntos de índices, reporta distancias en m/km/millas y duraciones siempre en segundos. Si se omiten fuentes/destinos, ambos usan todas las ubicaciones; la diagonal de una ubicación consigo misma es cero.
- Límites públicos: https://openrouteservice.org/restrictions/ . El Standard publica 3.500 pares origen×destino por petición Matrix y 25 pares cuando se usan argumentos dinámicos. Para 47×47 = 2.209 se omiten `sources` y `destinations`, evitando el modo dinámico; es una solicitud completa de todas las ubicaciones.
- Migración del host: https://ask.openrouteservice.org/t/reducing-the-quota-of-deprecated-api-api-openrouteservice-org/8013 . El anuncio de HeiGIT del 2026-08-27 indica que `api.openrouteservice.org` está deprecado en favor de `api.heigit.org` y que el primero quedó limitado al 10% de las cuotas publicadas, con apagado previsto entre 2026-11-02 y 2026-11-06. La configuración Matrix usa `https://api.heigit.org/openrouteservice/v2/matrix`.
- Compatibilidad de `preference`: la documentación Matrix consultada no enumera ese campo y la propuesta para añadir preferencias seguía abierta el 2026-10-12: https://github.com/GIScience/openrouteservice/pull/2324 . Por eso el cliente no envía `preference`; usa el comportamiento público por defecto de `driving-car`. No se considera automáticamente idéntico a Directions ni al Modelo A hasta medir diferencias.
- Alcance de redistribución: las respuestas HTTP crudas y encabezados de cuota permanecen excluidos de Git. Los resultados derivados seleccionados para distribución pública se publicaron/prepararon en `data/datasets/spain_tsp_2026/` bajo CC BY-SA 4.0 según los términos de cuenta HeiGIT consultados; ODbL se trata separadamente y su alcance se documenta en `LICENSE-DATA.md`.

## Paquete nacional ORS Directions (2026-10-14)

- Se confirmó la licencia de resultados ORS en los términos de cuenta HeiGIT, sección “Attribution and License — openrouteservice”, consultados el 2026-10-12: resultados CC BY-SA 4.0 y atribución **© openrouteservice by HeiGIT | Data from OpenStreetMap**. El documento no indica versión o fecha de vigencia. OpenStreetMap se atribuye y licencia por separado bajo ODbL 1.0; no se consideran intercambiables. Véase [LICENSE-DATA.md](datasets/spain_tsp_2026/LICENSE-DATA.md).
- La distribución versionada contiene matrices ORS Matrix, combustible derivado, baselines `v*T + combustible` sin peajes y 2.162 salidas geométricas ORS Directions comprimidas. El paquete no contiene las respuestas HTTP crudas ni encabezados de cuota. Los originales permanecen en `data/raw/` y excluidos de Git.
- Todas las rutas del paquete fueron adquiridas en `driving-car`, `preference=fastest`, con `extra_info=tollways,waycategory`; la ausencia de `osmId` se registra como limitación, no como invalidez. `tollways` es evidencia cartográfica y no una tarifa ni una prueba monetaria de cobro.
- La exportación y la validación offline se reproducen con `python -m experiments.analyze_tsp_ors_extras`, `python -m experiments.export_tsp_spain_publication` y `python -m experiments.export_tsp_spain_publication --verify-only`.

No se llamó a Matrix durante la preparación del flujo nacional. El comando se validó únicamente en modo de planificación, sin tráfico de red.

Cada dato real lleva fuente primaria y fecha de consulta. Los archivos crudos van en `data/raw/`.

| Dato | Fuente (URL o documento) | Fecha de consulta | Archivo crudo | Verificado por | Notas / limitaciones |
|---|---|---|---|---|---|
| Nombres de capitales y provincias | [Nomenclátores Geográficos del IGN](https://www.ign.es/web/rcc-nomenclator-nacional); [Mapa político oficial IGN](https://www.ign.es/web/resources/docs/IGNCnig/RE-Mapa-Espana-Politico.pdf) | 2026-10-12 | `data/processed/capitales_peninsulares.csv` | integrante 3 | El catálogo contiene 47 capitales provinciales peninsulares; se excluyen Palma, Las Palmas de Gran Canaria y Santa Cruz de Tenerife. |
| Coordenadas representativas de capitales | [Consulta filtrada del IGN API-Features](https://api-features.ign.es/collections/namedplace/items?filter=tipo%20%3D%20%27Capital%20de%20provincia%27&filter-lang=cql-text&f=json&limit=100); [documentación de Nomenclátores IGN](https://www.ign.es/web/rcc-nomenclator-nacional); [ficha y licencia CNIG NGBE](https://centrodedescargas.cnig.es/CentroDescargas/detalleArchivo?sec=9000001) | 2026-10-12 | `data/raw/ign_capitales_provincia_2026-10-12.geojson`; `data/processed/capitales_peninsulares.csv` | integrante 3 | La consulta filtrada `tipo = 'Capital de provincia'` devolvió 50 registros; se mapearon 47 por etiqueta a la lista canónica y se excluyeron las tres capitales insulares. Se copió `geometry` (longitud, latitud; CRS84), el id de feature, `fecha` y `fuente`. Son puntos oficiales representativos, no accesos a carreteras. La ficha de CNIG declara CC-BY 4.0; atribución: «Obra derivada de NGBE CC-BY 4.0 ign.es». |
| Distancias por carretera | [OSRM API](https://project-osrm.org/docs/); [política del servidor demo OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server); [OSRM herramientas de autoalojamiento](https://project-osrm.org/docs/v26.4.0/tools); [Geofabrik España](https://download.geofabrik.de/europe/spain.html) | 2026-10-12 | `data/raw/osrm_pilot_routes_2026-10-12.json` | integrante 3 | Se hicieron seis consultas puntuales al servidor demo, a más de un segundo entre solicitudes y dentro del uso no comercial razonable permitido. Se guardaron petición, respuesta y geometría simplificada. Distancias medidas por el motor sobre el mapa OSM disponible al momento de consulta; el demo no publica la fecha exacta del extracto. No usarlo para adquirir masivamente las 2.162 rutas. Geofabrik publicaba el 2026-10-12 un PBF de España de 1,4 GB, con corte OSM 2026-10-11T20:21:06Z; se consultó la ficha, no se descargó el archivo. La cifra es variable y debe verificarse al congelar la adquisición. |
| Tiempos de viaje | [OSRM API](https://project-osrm.org/docs/) | 2026-10-12 | `data/raw/osrm_pilot_routes_2026-10-12.json` | integrante 3 | Los tiempos reportados son duraciones estimadas por el perfil de conducción de OSRM, no mediciones reales ni necesariamente tiempos con tráfico en tiempo real. Las respuestas incluyen geometría simplificada y pasos con nombres/referencias viales; no contienen una marca monetaria ni tarifa de peaje. |
| Tarifas y vigencia de peajes | [Punto de Acceso General: peajes y tarifas](https://administracion.gob.es/tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas); [tarifas oficiales Autopistas 2026](https://www.autopistas.com/tarifas-y-descuentos/tarifas/); [tarifa AP-68 2026, PDF](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf); [actualización oficial de tarifas 2026](https://cdn.transportes.gob.es/portal-web-transportes/recursos-web/transportes/media/press_release/251230-np-nacional-revision-tarifas-autopistas-estatales-y-seitt.pdf); [fin de peajes AP-2/AP-7 en Cataluña](https://cdn.transportes.gob.es/portal-web-transportes/recursos-web/transportes/media/press-release/220310_np_af.trafico_ap-7_salida_11_s._celoni.pdf); [fin de concesión C-33](https://govern.cat/govern/docs/2021/05/04/15/33/35f0ae98-4337-4889-bc31-da085933f5da.pdf); [vigencia AP-68, BOE 2023](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2023-2962); [fin de medidas, BOE 2026](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-19039) | 2026-10-12 | `data/raw/osrm_pilot_routes_2026-10-12.json`; tarifas enlazadas | integrante 3 | La tarifa AP-68 publica 39,90 € para ligeros entre las estaciones nominales Bilbao y Zaragoza, válida desde 2026-01-01 e IVA incluido. Las respuestas OSRM suman 293,18 km y 293,28 km en pasos ref=AP-68; el total de vía del piloto es 304,41/305,16 km. La tarifa nominal es una referencia oficial aplicable al par, pero el costo OD queda provisional hasta cotejar la geometría con las estaciones tarifarias exactas. Para la vigencia, el convenio BOE de 2023 dice que finaliza el 11-11-2026 y el Real Decreto de 2026 sitúa la fecha final de medidas en 10-11-2026; no se extrapola la tarifa al periodo posterior. En Barcelona–Girona, la ruta principal incluye refs AP-7/C-33: sus secciones catalanas corresponden a tramos liberados de peaje en 2021. Aún no se asigna 0 € a todo el trayecto: falta validar toda la geometría frente al inventario de concesiones. Para Madrid–A Coruña se observaron AP-6/AP-9M/AP-9, pero falta identificar entradas/salidas y sumar tarifas. Una etiqueta AP no basta para determinar si un tramo cobra. |
| Precio de gasolina 95 (Eurosuper 95) | [Weekly Oil Bulletin de la Comisión Europea](https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en); [aviso de reutilización de la Comisión](https://commission.europa.eu/legal-notice_en) | 2026-10-12 | `data/raw/weekly_oil_bulletin_2026-10-08_prices_with_taxes.xlsx` | integrante 3 | Boletín publicado 2026-10-08; hoja `Sheet1`; España en `A28`, Eurosuper 95 en `B1`, unidad en `B2` (`1000 l`) y valor en `B28` (`1849.0983979999999`), con cabecera monetaria A1 `in EUR`: 1849.0983979999999 EUR/1000 L ÷ 1000 = 1.8490983979999999 €/L. La fecha de referencia de precios de A2 es 05/10/2026; la página oficial identifica esta publicación como boletín del 08/10/2026. SHA-256: `CAF597685A68EA265E7E671715622B71B7402DE069D21477331EA196F8F6A3C0`. Consulta del archivo: 2026-10-12; la fecha real de descarga del usuario no está embebida y queda desconocida. El nombre original sugería 2026-09-21, pero el contenido A2 y metadato de modificación (2026-10-08) corresponden a la edición examinada; se conservó el archivo binario y se normalizó su nombre local. La Comisión declara reutilización CC BY 4.0 de contenido propio salvo aviso específico distinto; no se encontró nota individual de licencia en el libro. Atribución y cambio: «Comisión Europea, Weekly Oil Bulletin, precios con impuestos, publicado 2026-10-08; extracción de la fila España y conversión de EUR/1000 L a EUR/L». |
| Motores de rutas y extracto OSM | [OSRM API](https://project-osrm.org/docs/v26.4.0/api/); [perfil oficial `car.lua`](https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua); [perfiles OSRM](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/profiles.md); [Valhalla matrix](https://valhalla.github.io/valhalla/api/matrix/api-reference/); [Valhalla costing](https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/); [Geofabrik España](https://download.geofabrik.de/europe/spain.html); [licencia OSM](https://www.openstreetmap.org/copyright) | 2026-10-12 | No adquirido | integrante 3 | Documentación consultada para planificar la adquisición, no prueba experimental de cobertura o precisión. OSRM Table calcula métricas de las rutas rápidas; su perfil `car.lua` marca `toll` como clase excludable, condicionado a fijar/preprocesar el mismo perfil. Valhalla `use_tolls` es una preferencia, no garantía de ruta sin peaje. Ninguno da por ello una tarifa monetaria oficial. El extracto PBF español consultado tenía 1,4 GB y corte 2026-10-11; no se descargó ni se instalaron motores. Véase `docs/tsp_adquisicion.md`. |
| Consumo representativo del BMW 120 | [BMW España, datos técnicos BMW Serie 1 F70](https://www.bmw.es/es/coches-bmw/serie-1/bmw-serie-1/datos-tecnicos-bmw-serie1.html) | 2026-10-12 | `configs/tsp_economics.yaml` | integrante 3 | La ficha vigente consultada presenta BMW 120 gasolina mild hybrid 48 V, potencia total 125 kW/170 CV, y consumo promedio WLTP 5,3–5,5 L/100 km; recomienda gasolina de 95 octanos. Se fija 5,4 como punto medio representativo acordado por el equipo, no como dato homologado de una configuración/rueda/acabado concreto. Sensibilidad: 5,3 y 5,5. El perfil ORS no simula este vehículo; el factor se usa solo para convertir kilómetros a combustible estimado. |
| APIs y ETL de rutas (revisión de términos y capacidad) | [ORS Directions](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/); [ORS Matrix](https://giscience.github.io/openrouteservice/api-reference/endpoints/matrix/); [restricciones ORS](https://openrouteservice.org/restrictions/); [planes ORS](https://openrouteservice.org/plans/); [términos ORS de cuenta](https://account.heigit.org/info/tos); [respuesta HeiGIT sobre licencia de resultados](https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079); [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode); [ODbL](https://opendatacommons.org/licenses/odbl/1-0/); [guía de atribución OSMF](https://osmfoundation.org/wiki/Attribution_Guidelines); [API OSRM](https://project-osrm.org/docs/v5.24.0/api/); [política demo OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy); [API GraphHopper](https://docs.graphhopper.com/openapi); [términos GraphHopper](https://www.graphhopper.com/terms/) | 2026-10-12 | Sin respuestas API nuevas | integrante 3 | Consulta documental; no se hicieron llamadas API ni se instalaron herramientas. Los términos de cuenta HeiGIT fueron revisados por el integrante 3 el 2026-10-12, sección “Attribution and License — openrouteservice”: resultados CC BY-SA 4.0 y atribución `© openrouteservice by HeiGIT | Data from OpenStreetMap`; no se muestra fecha/versión del documento. OSM se mantiene con atribución/enlace ODbL separados; no se equiparan licencias. Ver alcance y límites de publicación en `docs/tsp_dataset_publicacion.md`. OSRM demo advierte contra uso excesivo; GraphHopper limita almacenamiento/redistribución por defecto. |

| Detección espacial y tarifas de peajes | [ORS Directions: extra_info](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/); [política de uso de Overpass](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html); [OpenStreetMap: copyright y ODbL](https://www.openstreetmap.org/copyright); [tarifas Autopistas 2026](https://www.autopistas.com/tarifas-y-descuentos/tarifas/); [PDF oficial AP-68 2026](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf); [Ministerio: tarifas AP-68 2025 y categoría ligera](https://cdn.transportes.gob.es/portal-web-transportes/carreteras/nuestrared/autopistaspeaje/peajes-actuales/autopista-ap-68%2C-bilbao---zaragoza-2025.pdf); [Ministerio: actualización de tarifas estatales y SEITT 2026](https://cdn.transportes.gob.es/portal-web-transportes/recursos-web/transportes/media/press_release/251230-np-nacional-revision-tarifas-autopistas-estatales-y-seitt.pdf); [SEITT/AP-41: tarifas 2026](https://cdn.transportes.gob.es/portal-web-seitt/media/document/precios_web_ap41_2026.pdf); [Álava: transición de la gestión AP-68](https://prentsa.araba.eus/es/-/el-gobierno-foral-presenta-en-jjgg-la-norma-foral-que-regulara-el-sistema-de-pago-por-uso-en-la-ap-68); [BOE: Real Decreto 730/2026](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-19039) | 2026-10-12 | Sin descargas geográficas; consulta documental | integrante 3 | ORS `tollways`, `waycategory` y `osmid` ofrecen evidencia cartográfica, no precios. Overpass permite consultas selectivas y reporta HTTP 429 ante límites; su guía recomienda evitar barridos a gran escala. OSM es ODbL y exige atribución; las carpetas de datos de peaje quedan ignoradas localmente mientras se revisa redistribución. Autopistas publica AP-68 2026 por estación/categoría: 39,90 EUR para el par nominal Bilbao–Zaragoza en clase ligera; no se asignó a la geometría ORS porque falta confirmar entradas/salidas. Álava anunció el inicio previsto de un nuevo esquema para el tramo alavés el 2026-11-11, pero el importe definitivo seguía en trámite al consultar; no se extrapola la tarifa anterior. SEITT publica documentos por autopista, con reglas horarias/formas de pago según caso; no se encontró API única completa de tarifas. Metodología implementada y límites en `docs/tsp_peajes.md`. |

## Notas de procedencia y decisiones pendientes

- `geometry.coordinates` en GeoJSON se conserva como `[longitud, latitud]`; el CSV lo almacena en columnas separadas `latitude` y `longitude`. Los campos adicionales `source_feature_id`, `source_record_date` y `source_record_source` permiten rastrear cada fila al registro y a su fuente interna. La fecha de consulta se distingue de la fecha que trae el registro.
- Los puntos de capital provincial son adecuados para representar nodos en mapas y para una primera unión espacial, pero un motor de rutas los ajustará a una arista vial cercana. Ese ajuste puede cambiar la distancia/tiempo del acceso urbano. Se debe guardar por separado la coordenada original y la coordenada/snapping del motor si se usa.
- Los documentos de OSRM, Valhalla y proveedores comerciales describen capacidades; no significan que se haya probado su cobertura, precisión local, cuotas, precio del servicio o calidad de ruta en las ciudades del estudio.
- El precio del combustible, el vehículo y el motor para la matriz completa siguen sin selección definitiva. Hay seis consultas puntuales de distancias, duraciones y geometrías en el archivo de piloto, pero todavía no existe una matriz de las 2.162 rutas ni una matriz completa de peajes.

## Piloto OSRM

Las solicitudes se hicieron el 2026-10-12 al endpoint `/route/v1/driving` del servidor demo público, con `alternatives=true`, `steps=true`, `overview=simplified` y `geometries=geojson`. Las coordenadas de entrada son los puntos representativos del IGN del catálogo; OSRM los ajusta a su red. El archivo crudo preserva las URLs solicitadas, las respuestas, los pasos y las geometrías. Se respetó el límite publicado de una solicitud por segundo y el uso no comercial razonable. El servidor no garantiza disponibilidad, latencia ni fecha de actualización del mapa.

| Origen → destino | Distancia de la ruta principal (km) | Duración estimada (min) | Alternativas devueltas | Vías principales nombradas por OSRM | Tarifa verificada |
|---|---:|---:|---:|---|---|
| Madrid → Toledo | 74,63 | 62,1 | 0 | A-42 | No; no se asigna costo cero a partir de OSRM. |
| Toledo → Madrid | 72,60 | 60,3 | 1 adicional: 84,59 km y 68,4 min | A-42; la alternativa pasa por M-45/A-3 | No; no se asigna costo cero a partir de OSRM. |
| Bilbao → Zaragoza | 304,41 | 197,5 | 0 | A-8, AP-68, Z-40/A-2 | 39,90 € es la tarifa oficial 2026 para el par nominal Bilbao–Zaragoza; imputación OD pendiente de validar estaciones. |
| Zaragoza → Bilbao | 305,16 | 198,8 | 0 | AP-68, A-8 | 39,90 € es la tarifa oficial 2026 para el par nominal Zaragoza–Bilbao; imputación OD pendiente de validar estaciones. |
| Madrid → A Coruña | 595,56 | 393,0 | 0 | A-6, AP-6, AP-9M, AP-9 | Sin total verificado; falta desglosar cruces y tarifas de cada operador. |
| Barcelona → Girona | 102,96 | 80,8 | 1 adicional: 103,29 km y 85,2 min | B-10, C-58, C-33, AP-7, C-65 | Sin costo OD asignado; las secciones AP-7/C-33 identificadas corresponden a tramos liberados, pero falta revisar la geometría completa. |

Las duraciones se convierten de segundos de OSRM a minutos y las distancias de metros a kilómetros. La asimetría observada (por ejemplo, Madrid–Toledo frente a Toledo–Madrid) es admisible por sentidos de circulación, acceso urbano, ajuste a la red y ruta elegida; no se fuerza simetría en el modelo. El servidor devolvió una alternativa para Toledo–Madrid y otra para Barcelona–Girona, no un inventario exhaustivo de rutas posibles. Sus duraciones son estimaciones estáticas del perfil y no incorporan condiciones de tráfico observadas para una hora de salida.

El piloto confirma que OSRM automatiza distancia, duración, secuencia vial y geometría para un par dirigido, pero no determina precio de peaje. La tarifa monetaria requiere enlazar cada sección de carretera de peaje con sus puntos de entrada/salida y la categoría del vehículo en la tabla del operador. El estado de peaje debe ser versionado por fecha: una ruta puede pasar por carreteras AP que ya son gratuitas, y la concesión AP-68 está próxima a terminar según la fuente oficial consultada. Para reproducibilidad de la matriz completa se recomienda autoalojar OSRM con una versión fijada del motor, perfil y extracto OSM archivado con fecha/atribución; usar el demo para 2.162 consultas no es apropiado. Seis consultas en el demo produjeron rutas en la prueba, pero eso no constituye garantía de rendimiento ni disponibilidad para el procesamiento completo.
# Consulta documental adicional: planificación Overpass (2026-10-12)

- Manual oficial de uso compartido de Overpass API:
  https://dev.overpass-api.de/overpass-doc/en/preface/commons.html
  Consultado el 2026-10-12. Describe instancias públicas compartidas, carga
  variable, control de recursos y respuestas HTTP 429/504. Sus cifras son
  orientaciones operativas, no una cuota garantizada para este proyecto.
- Recomendaciones de uso de Overpass API en OpenStreetMap Wiki:
  https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances
  Consultado el 2026-10-12. Recomienda cachear, limitar frecuencia, evitar
  consultas paralelas y esperar antes de repetir tras 429/406. Se utiliza como
  respaldo operativo para la espera de 30 segundos del piloto.
- Documentación oficial ORS Directions — información adicional:
  https://giscience.github.io/openrouteservice/v9.10.0/api-reference/endpoints/directions/extra-info/
  y formato de respuesta GeoJSON:
  https://giscience.github.io/openrouteservice/v9.10.0/api-reference/endpoints/directions/requests-and-return-types
  Consultado el 2026-10-12. Indica que `extra_info` admite `tollways`,
  `waycategory` y `osmid` para `driving-car` en el motor 9.10.0; en JSON quedan
  en `routes[*].extras`, y en el formato GeoJSON utilizado, bajo
  `features[*].properties.extras`. La clave de respuesta del dato solicitado
  como `osmid` es `osmId`. No devuelve tarifas ni accesos tarifarios.

El inventario planeado en esta fase es exclusivamente una cuadrícula local
derivada de las 12 geometrías piloto ORS. La planificación no descargó objetos
de Overpass ni consultó ORS. El manifiesto y las respuestas de proveedor se
guardan bajo `data/processed/tolls/` y `data/raw/tolls/`, carpetas ignoradas
por Git mientras se revisan los términos específicos de redistribución.

### Resultado real del piloto geográfico Overpass (2026-10-12, hora local)

Se revisaron sin nuevas consultas los archivos locales de `data/raw/tolls/` y
`data/processed/tolls/`. El manifiesto contenía 35 cajas; el estado registró
dos regiones adquiridas, una fallida (HTTP 504), 32 pendientes y dos solicitudes
HTTP en la última ejecución; además, se omitió una región previamente almacenada.
Por ello, no se completó el lote de 35 consultas. Hay dos respuestas locales,
con `osm3s.timestamp_osm_base` `2026-10-13T01:51:44Z` y
`2026-10-13T02:15:21Z`; los metadatos consignan adquisiciones efectivas
`2026-10-13T01:53:08.525656Z` y `2026-10-13T02:17:08.406499Z` (ambas el
2026-10-12, hora de Bogotá). Contienen 171 observaciones OSM; al consolidar por
`(tipo, ID)` quedan 168 objetos únicos y se eliminan tres duplicados. El
inventario incluye vías `toll=yes` y 13 estaciones `toll_booth`; no contiene
`highway=toll_gantry`. Las geometrías de la relación AP-68 se conservan como
líneas separadas para evitar segmentos ficticios.

El cruce offline con las 12 geometrías ORS encontró coincidencias geométricas
probables entre las rutas rápidas Bilbao–Zaragoza y Zaragoza–Bilbao y la
relación AP-68; las dos candidatas `avoid_tolls` también muestran un tramo
breve alineado/cercano en el área descargada. El dato no confirma por sí solo
tránsito tarifado, sentido, estaciones de acceso/salida ni coste. Los informes
regenerables están en `data/processed/tolls/overpass_inventory.csv`,
`overpass_route_matches.csv` y `overpass_pilot_analysis.md`; el catálogo
geográfico está en `overpass_inventory.geojson`. El informe consolidado registra
168 IDs únicos y 189 relaciones ruta–objeto para las 12 geometrías ORS. Permanecen excluidos de Git
por ser derivados de OSM/ODbL y estar pendiente la decisión de redistribución.
La metodología y sus limitaciones están en `docs/tsp_peajes.md`.

### Snapshot nacional ORS Matrix y revisión para redistribución (2026-10-12)

El snapshot local ORS Matrix conserva la respuesta con SHA-256
`8660e42cb511a530e5dfeb2dea003af50b2013dc03cebedd74276d2eebab1d9e`; el
contenedor JSON local tiene hash distinto y también se registra en los metadatos
del paquete preparado. La respuesta corresponde a `driving-car`, métricas
distancia/duración, unidades originales m/s y orden canónico de 47 ciudades.
Las matrices derivadas mantienen 2.162 arcos dirigidos; no contienen peajes.

El integrante 3 consultó directamente los términos de la cuenta HeiGIT en
`https://account.heigit.org/info/tos`, sección “Attribution and License —
openrouteservice”, el 2026-10-12. Esa sección establece CC BY-SA 4.0 para todos
los resultados ORS y la atribución `© openrouteservice by HeiGIT | Data from
OpenStreetMap`. El documento no muestra número de versión o fecha de vigencia;
se registra la fecha de consulta. El texto legal CC BY-SA 4.0 exige atribución
y compartir adaptaciones bajo la misma licencia o una compatible; cubre
derechos de base de datos donde corresponda.

OpenStreetMap mantiene una licencia distinta: ODbL 1.0. En este paquete no se
redistribuye el grafo OSM, geometrías ni atributos viales, sino valores de
distancia/tiempo resultantes del motor, por lo que conservamos el crédito OSM y
el enlace a ODbL sin presentar el conjunto como una extracción de la base OSM.
La guía OSMF de rutas requiere atribución y establece que el share-alike ODbL es
relevante si la salida constituye una base derivada. Si se amplía el contenido
con datos de red OSM o se determina que es una base derivada, se revisarán y
aplicarán por separado las obligaciones ODbL de licencia compatible y acceso a
la base/alteraciones. CC BY-SA y ODbL no son intercambiables ni se sustituyen.
El campo `results_license` del JSON local fue añadido por `RouteStore`, no
devuelto por ORS; la fuente de la licencia efectiva es el documento de cuenta.

Fuentes consultadas el 2026-10-12:

- Términos de cuenta HeiGIT: https://account.heigit.org/info/tos, sección
  “Attribution and License — openrouteservice”; consulta del integrante 3
  2026-10-12, versión/fecha de publicación no indicada.
- Texto legal CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/legalcode
- ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/
- Respuesta ORS/HeiGIT sobre CC BY-SA 4.0:
  https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079
- Respuesta ORS/HeiGIT sobre persistencia de resultados Matrix:
  https://ask.openrouteservice.org/t/persistent-storage-and-reuse-of-matrix-api-duration-results/8010
- Guía de atribución OSMF: https://osmfoundation.org/wiki/Attribution_Guidelines
- Licencia OSM: https://www.openstreetmap.org/copyright

El paquete versionado está en `data/datasets/spain_tsp_2026/`. El exportador
produce los CSV con orden canónico, metadatos, hashes y licencias por componente;
el cargador verifica todo offline. Combustible: se usa el boletín de la Comisión
publicado el 2026-10-08 y consultado el 2026-10-12; la fecha efectiva de descarga
del archivo no quedó registrada y se conserva como desconocida. El paquete no
contiene peajes ni una matriz de costo económico total.

### Tarifas oficiales y alcance nacional consultados (2026-10-13)

La página del Punto de Acceso General señala los principales corredores de
peaje para 2026 y advierte que los importes pueden depender de vehículo,
distancia, horario y forma de pago. Su subsección “Autopistas con peaje” aún
identifica expresamente datos de 2024; no se utiliza esa lista como inventario
exhaustivo de 2026. El CSV `data/reference/toll_roads_2026.csv` es una lista
prioritaria de corredores citados por documentos oficiales, con la granularidad
y vigencia pendientes marcadas como tales.

La tabla oficial AP-68 de Autopistas/AVASA fue consultada en el PDF de tarifas
2026. Para ligeros muestra 39,90 EUR para las estaciones nominales Bilbao ↔
Zaragoza, vigente desde el 1 de enero de 2026 e IVA incluido. Los dos registros
transcritos localmente están en `data/processed/tolls/ap68_2026_ligeros.csv`,
que permanece excluido de Git. No se conservó una copia PDF local ni se publica
la transcripción hasta confirmar condiciones de redistribución. Se conoce la
URL y la página 1; la fuente en línea no da una fecha inequívoca de publicación,
por lo que `published_on` queda vacío y no inventado. La fecha de consulta
efectiva registrada es 2026-10-13.

El BOE-A-2026-19039 fecha el final de la concesión AVASA para el 2026-11-10;
el caso AP-68 se limita al escenario anterior a esa fecha y no se extrapola al
régimen posterior. Las geometrías ORS locales muestran AP-68 en las referencias
de vía y coincidencia lineal extensa con la relación OSM, pero el inventario
solo aporta estaciones de Alagón próximas a la ruta. Las estaciones exactas de
entrada/salida de la ruta Bilbao–Zaragoza no están verificadas. Por tanto, los
39,90 EUR se conservan como tarifa oficial del par de estaciones nominal, no
como costo confirmado de las geometrías ORS; el peaje de esas rutas sigue
desconocido.

Fuentes oficiales revisadas el 2026-10-13:

- Punto de Acceso General, “Peajes y Viñetas” (página indica actualización
  2026-03-19): https://administracion.gob.es/tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas
- Tarifas Autopistas: https://www.autopistas.com/tarifas-y-descuentos/tarifas/
- Tarifario AP-68 2026: https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf
- Marco tarifario SEITT: https://www.boe.es/eli/es/res/2024/12/06/%281%29
- Modificación de tarifas/red SEITT, BOE-A-2025-25961:
  https://www.boe.es/eli/es/res/2025/12/10/%282%29/dof/spa/pdf
- Adenda SEITT sobre Circunvalación de Alicante, BOE-A-2026-2970:
  https://www.boe.es/boe/dias/2026/02/09/pdfs/BOE-A-2026-2970.pdf
- Modificación SEITT que establece tarifa de 0 EUR para Circunvalación de Alicante,
  vigente desde su publicación el 2025-12-18 (BOE-A-2025-25961):
  https://www.boe.es/eli/es/res/2025/12/10/%282%29/dof/spa/pdf
- Real Decreto 730/2026, medidas AP-68 y fin de concesión el 2026-11-10:
  https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-19039
- Tarifas oficiales catalanas 2026 para C-16/C-32 (incluye franjas, categorías y condiciones de descuento):
  https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/peatges-tarifes-descomptes/tarifes-peatges/index.html
- Inventario de tramos con peaje de Bizkaia (AP-8 Galdakao–Ermua, Variante Sur Metropolitana y túneles de Artxanda):
  https://www.bizkaia.eus/es/tema-detalle/-/edukia/dt/6320
- Presupuesto oficial de Álava 2026, tarifas de AP-1 por tramos:
  https://www.araba.eus/Presupuestos/2026/TOM-2026_PTO-50-02.html
- Decreto gallego 125/2025, congelación 2026 y bonificaciones AG-55/AG-57:
  https://www.xunta.gal/dog/Publicados/2025/20251231/AnuncioG0765-291225-0001_gl.html

### Revisión de estaciones OSM y ORS Extra Info (2026-10-13)

- ORS Directions Extra Info:
  https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/
  y categorías de vía:
  https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/waycategory
  Consultado el 2026-10-13. La tabla vigente muestra `tollways`, `osmid` y
  `waycategory` disponibles para `driving-car`; `osmid` se solicita con ese
  nombre y aparece como `osmId`. La información no viene implícita: debe
  pedirse en `extra_info`. La disponibilidad documental no confirma que una
  respuesta concreta contenga todos los campos; el cliente lo valida.
  `waycategory` es una máscara de bits: 3 combina Highway (1) y Tollways (2).
- Tarifario AP-68 2026, página 1:
  https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf
  Consultado el 2026-10-13. La tabla de ligeros enumera estaciones de
  referencia y muestra 39,90 EUR para Bilbao–Zaragoza desde 2026-01-01. El
  precio no se vincula a geometrías ORS porque el snapshot local no verifica
  estaciones de entrada y salida.
- Los informes locales de estaciones están en
  `data/processed/tolls/station_review/` y se regeneran con
  `python -m experiments.report_tsp_toll_stations`. El informe usa el
  inventario OSM parcial existente y las tres geometrías rápidas; no hizo
  llamadas de red y permanece en directorios excluidos de Git.
