# Inventario y tarifas de peajes del TSP

**Estado al 2026-10-12:** se ejecutó localmente una parte del piloto Overpass:
dos de 35 regiones quedaron adquiridas, una falló con HTTP 504 y 32 permanecen
pendientes. Se generaron informes offline de los dos snapshots disponibles. No se
asignaron tarifas a las 12 rutas ORS. El ETL y sus validaciones están
implementados, pero las matrices económicas nacionales todavía no existen.

## 1. Fuentes y qué prueban

| Fuente | Uso posible | Lo que no prueba |
|---|---|---|
| ORS Directions `extra_info` (`tollways`, `waycategory`, `osmid`) | Localizar tramos de una ruta ligados a vías OSM y recuperar sus IDs de vía. La documentación indica que `tollways` vale 0/1 según el perfil y que `waycategory` contiene la categoría tollway; `osmid` identifica vías. | No devuelve importes, estaciones de entrada/salida ni certifica el estado legal/tarifario vigente. La clasificación depende del perfil y los datos del grafo. |
| OpenStreetMap vía Overpass | Consultar por bounding box estaciones `barrier=toll_booth`, pórticos `highway=toll_gantry` y vías `toll=yes`, con IDs, etiquetas y geometría. | Una etiqueta o punto cercano no prueba que el vehículo de la ruta cruzara la instalación, qué calzada recorrió ni cuánto pagó. La cobertura y actualidad dependen de contribuciones OSM. |
| Tarifas oficiales de Autopistas/AVASA | Tabla AP-68 2026 por estación de entrada y salida, clase ligera/pesada, importes en euros; el documento indica que las tarifas publicadas rigen desde el 1 de enero. | No empareja por sí sola una geometría ORS a su pareja de estaciones; descuentos y modalidad pueden cambiar el importe efectivo. |
| Transportes / SEITT | Tarifas oficiales en documentos descargables para las autopistas estatales gestionadas por SEITT, con casos que diferencian horario y forma de pago (por ejemplo AP-41). | No se encontró una API única que entregue el costo de cualquier ruta y operador. Los formatos publicados son documentos, no un servicio universal de tarificación. |
| Diputación Foral de Álava / Arabat | Avisos oficiales sobre el cambio de gestión/canon para el tramo alavés de AP-68. | El anuncio/proyecto de tarifa futura no es una tarifa vigente hasta publicarse y entrar en vigor el acto definitivo. |

La API ORS documenta campos cartográficos, no importes. La página pública del
operador Autopistas enlaza el PDF de AP-68 2026. Para la fecha de estudio
2026-10-12, el PDF muestra la clase **Ligeros** y 39,90 EUR en la celda Bilbao →
Zaragoza. Esa cifra describe el par nominal del tarifario, no el importe de
cualquier ruta entre las capitales: antes de cargarla en una alternativa se
deben confirmar las estaciones exactas recorridas, categoría y condiciones.

La vigencia es temporalmente sensible. La Diputación de Álava anunció como
fecha prevista de inicio del nuevo esquema el 2026-11-11 y señaló que un decreto
posterior fijaría el canon; al 2026-10-12 el portal oficial aún mostraba abierto
el trámite de audiencia sobre el canon inicial. Por eso no aplicamos el importe nominal de
2026 a fechas posteriores al 10 de noviembre ni convertimos la propuesta por
kilómetro difundida en septiembre en tarifa vigente. El cálculo AP-68 debe
segmentarse por concesión/administración y fecha.

No se encontró, en las fuentes oficiales revisadas, una API pública completa y
estructurada con todas las tarifas españolas por entrada, salida, fecha y
vehículo. El método realista es descargar los documentos oficiales, transcribir
y normalizar las tarifas a CSV con doble revisión y guardar PDF fuente, hash y
vigencia local. El código importa ese CSV normalizado; no extrae PDF por OCR ni
interpreta automáticamente una tabla gráfica. Los datos de tarifa descargados
se guardarán en `data/raw/tolls/` y el catálogo normalizado en
`data/processed/tolls/`; ambas carpetas están excluidas de Git hasta completar
la revisión de licencias y redistribución.

## 2. Cliente y catálogo geográfico

`src/tsp/etl/toll_infrastructure.py` define un cliente Overpass que acepta solo
HTTPS y una caja acotada (área máxima de 1 grado cuadrado). Cada llamada
explícita realiza exactamente una petición; no hay reintentos ni división
automática para barrer España. El plan regional se compone de cajas pequeñas
alrededor de corredores y estaciones potenciales. La guía de Overpass aconseja
usar extracts para descargas grandes, informa HTTP 429 ante límites y da como
orientación de uso moderado aproximadamente 10.000 consultas y menos de 1 GB
por día, no como cuota garantizada.

El parser conserva el tipo e ID OSM, geometría longitud/latitud, clasificación,
nombre, operador, `ref`, dirección/`oneway`, todas las etiquetas, fuente y fecha
efectiva de consulta. `OverpassCatalogStore("data")` conserva el JSON original
en `data/raw/tolls/`, el GeoJSON y el manifiesto en `data/processed/tolls/`, y
reutiliza una caja durante 30 días por defecto; solo `refresh=True` la consulta
de nuevo antes de vencer esa ventana. Es una regla local conservadora, no una
garantía de frescura de OSM. Se puede exportar/cargar GeoJSON offline. Para redistribuir datos
OSM se debe atribuir a OpenStreetMap y cumplir ODbL; mantenerlos privados en
local mientras se verifica la política del curso no equivale a tener permiso
para subirlos al repositorio.

## 3. Cruce espacial con las 12 rutas locales

`match_route_alternatives_to_infrastructure` cruza alternativas cargadas del
catálogo ETL con el inventario local; falla si falta alguna geometría.
`match_infrastructure_to_route` mide la distancia mínima de las geometrías y
devuelve una fracción aproximada del avance de ruta, un umbral explícito y las
etiquetas que dan contexto de sentido. Distingue `candidato_proximidad` de
`coincidencia_vial_probable`, cuando un elemento lineal `toll=yes` se alinea
geométricamente cerca y de forma aproximadamente paralela durante al menos
250 m. La proyección local equirectangular es un filtro de radio corto, no una
prueba topológica. Una estación al lado de la calzada contraria, una vía
paralela, un ramal o una salida cercana pueden quedar a poca distancia y no
haber sido recorridos.

La automatización puede cruzar geometría ORS con `osmid`/`tollways`, vías y
estaciones OSM, ordenar candidatos por avance, cotejar `ref` y etiquetas de
sentido y crear una cola de casos dudosos. El tránsito y el par tarifario solo
se elevan a verificados tras comprobar continuidad vial, sentido/calzada,
entrada y salida contra una fuente oficial. No se cobra por cada estación o
nodo cercano. Las etiquetas `oneway`/`direction` se guardan como evidencia, no
como confirmación de sentido de cobro.

## 4. Tarifas y evaluación

`src/tsp/etl/toll_tariffs.py` importa CSV con columnas explícitas para operador,
autopista, entrada, salida, dirección, categoría, importe EUR, vigencia, fecha
de publicación/adquisición, condiciones de pago, fuente y estado. Rechaza
duplicados, fechas invertidas, importes inválidos, tarifa pagada con 0 EUR y
registros sin estado verificado. PDF/XLSX se conservan como fuente y la
transcripción al CSV requiere revisión humana; la coma decimal se acepta.

Una sección de ruta aporta estación de entrada/salida, dirección y prueba de
asociación revisada. Solo se asigna tarifa si coincide exactamente con
operador, autopista, categoría, par, sentido y fecha y existe una única fila aplicable. Secciones
repetidas se rechazan para evitar doble cobro. Si falta una tarifa o no se ha
confirmado el emparejamiento, el resultado es `desconocido` y el importe `None`.
La bandera `inventory_complete` y `inventory_source` son obligatorias para
sumar un costo de ruta: una sección identificada no demuestra que se hayan
encontrado todas las demás ni conserva por sí sola la fuente de cobertura.
El estado `verificado_sin_peaje` exige inventario de cobertura completa y una
fuente explícita que documenten que no se recorrió sección tarifada. La
ausencia de resultados Overpass o de `tollways` no basta para asignar cero.

La evaluación proyectada en `RouteAlternative` conserva el registro original
inmutable. El snapshot se considera válido solo para la fecha indicada; se
revisan tarifas cuando cambia la fecha de estudio o la vigencia. El constructor
de matrices existente mantiene peajes desconocidos fuera de una matriz
económica completa.

## 5. AP-68: ejemplo verificable y límites

Para el escenario 2026-10-12, el PDF oficial de Autopistas/AVASA tiene una
matriz de Ligeros; Bilbao → Zaragoza figura como 39,90 EUR. La fuente publica
estaciones intermedias y pares tarifarios, y el Ministerio publica documentos
AP-68 de recorridos directos/inversos y categorías. Esto habilita una tabla
tarifaria estructurada por transcripción, no una asignación automática por
nombre de vía.

El snapshot Overpass adquirido incluye una relación OSM `ref=AP-68` y vías
miembro. El cruce geométrico da aproximadamente 290,9 km de alineamiento con
cada ruta `fastest` de Bilbao ↔ Zaragoza y unos 332 m / 259 m con las
candidatas `avoid_tolls`. Es evidencia probable de un uso extenso en las rutas
rápidas y una coincidencia local breve en las candidatas; no confirma estaciones,
calzada, sentido ni longitud tarifada. Solo se adquirió una de las 8–9 celdas
planificadas por arco y no se puede probar que las candidatas eviten toda la
AP-68. Las respuestas ORS no contenían `extra_info` (0/12). Además, desde
2026-11-11 el tramo alavés entra en un nuevo
esquema de gestión. La propuesta comunicada por Álava es de precio por km y
requiere el decreto/acto definitivo, mapa de pórticos y reglas operativas para
transformarse en costo aplicable. El importe 39,90 EUR se puede citar como
referencia oficial del par de estaciones y del periodo previo, no como peaje
confirmado de la geometría ORS ni como valor futuro.

## 6. Proceso escalable recomendado

1. Fijar fecha del escenario, categoría `ligero` y pago ordinario sin descuentos.
2. Descargar inventario OSM por cajas de corredores y guardar respuesta,
   instancia, fecha, hash, atribución y licencia local.
3. Pedir `extra_info` ORS solo en rutas ya adquiridas/permitidas; extraer
   segmentos, IDs OSM y referencias sin cambiar la respuesta original.
4. Cruzar espacialmente y generar candidatos con distancia, avance y evidencia.
5. Revisar tarifa por operador y documentar estaciones/sentido.
6. Transcribir tarifarios oficiales a CSV con revisión independiente; fijar
   `valid_from`/`valid_through`, condiciones y hash del documento fuente.
7. Aplicar filas exactas a secciones verificadas y marcar huecos como
   desconocidos; solo certificar cero cuando se cubra la ruta entera.
8. Regenerar offline el catálogo de alternativas y matrices; ACO/GA no consultan
   APIs.

Antes de una adquisición Overpass se presentará el plan de cajas, número de
consultas y volumen previsto. Las pruebas actuales usan fixtures sintéticos y
no hacen consultas externas.

## 7. Plan reproducible del piloto Overpass

`src/tsp/etl/overpass_pilot.py` carga el catálogo local de rutas y genera un
manifiesto sin conexión. La planificación actual leyó **12 geometrías** (seis
arcos dirigidos, rápidas y candidatas `avoid_tolls`), con 28.692 vértices y
28.680 segmentos. Se usa una cuadrícula de celdas de 0,5° por 0,5° y un margen
configurable de 2 km alrededor de los segmentos. El margen se aproxima en
grados con la latitud local; es una envolvente conservadora, no un buffer
geodésico de precisión topográfica.

La deduplicación de celdas compartidas deja **35 cajas únicas**: 11 priorizadas
por corresponder a Bilbao ↔ Zaragoza y 24 para los demás corredores del
piloto. Cada consulta cubre un máximo de 0,25 grados cuadrados (aprox. 55 km
por lado en latitud media española). Las rutas rápidas y candidatas están
asociadas a cada celda en el manifiesto. El plan valida que cada vértice y el
punto medio de cada segmento de las 12 polilíneas caiga dentro de alguna caja
asignada a su alternativa (57.372 muestras de cobertura en esta ejecución).
La región prioritaria abarca
aproximadamente latitudes 41,5–43,5° y longitudes −3,0–0,0°; el conjunto
restante cubre Madrid–Toledo, Madrid–A Coruña y Barcelona–Girona. Los límites
exactos, IDs de celda y consultas quedan en el manifiesto local ignorado por
Git `data/processed/tolls/overpass_pilot_manifest.json`.

Planificar desde PowerShell, en la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m src.tsp.etl.overpass_pilot `
  --manifest data\processed\tolls\overpass_pilot_manifest.json `
  --cell-degrees 0.5 --margin-m 2000
```

El script no consulta red sin `--execute`. Cuando se autorice el piloto, el
comando correspondiente queda preparado con límite duro de 35 solicitudes,
dos segundos entre peticiones, sin concurrencia ni reintentos automáticos:

```powershell
.\.venv\Scripts\python.exe -m src.tsp.etl.overpass_pilot `
  --manifest data\processed\tolls\overpass_pilot_manifest.json `
  --cell-degrees 0.5 --margin-m 2000 `
  --execute --max-requests 35 --interval-seconds 2
```

Antes de ejecutar, la CLI vuelve a generar el manifiesto desde la geometría
local. `--max-requests` es un tope por invocación: puede ser menor que el total
planificado y las regiones restantes siguen pendientes para reanudar. Cada caja tiene cache propia y se guarda
en `data/raw/tolls/` y `data/processed/tolls/`. Un estado local registra las
cajas completadas. Al reanudar, las cajas ya adquiridas se omiten; una
respuesta incompleta no se considera exitosa. No hay reintentos automáticos.
Ante HTTP 429 se guarda el código, se detiene el lote y el estado impone una
espera de 30 segundos antes de admitir otra ejecución. El flujo es secuencial y
no requiere claves. Esos directorios permanecen excluidos de Git.

La consulta incluye instalaciones `barrier=toll_booth`, `highway=toll_gantry`
y elementos con `toll=yes`, con etiquetas y geometría. El consolidador offline
actual une observaciones por `(tipo OSM, ID OSM)`, conserva los archivos fuente,
fechas de adquisición y versión `osm_base`, marca snapshots discordantes y
mantiene los miembros de relaciones como `MultiLineString` para no conectar
artificialmente geometrías separadas. El analizador cruza las geometrías
locales y diferencia cercanía de coincidencia geométrica probable. Incluso un
alineamiento no confirma calzada, acceso, sentido ni cobro. Ninguna proximidad
genera tarifas.

Para regenerar el inventario y los informes sin conexión:

```powershell
.\.venv\Scripts\python.exe -m src.tsp.etl.toll_pilot_analysis
```

El comando genera `overpass_inventory.geojson`, `overpass_inventory.csv`,
`overpass_route_matches.csv` y `overpass_pilot_analysis.md` bajo
`data/processed/tolls/`. Los resultados contienen datos derivados de OSM y el
directorio sigue excluido de Git mientras no se cierre la revisión de
redistribución.

En la revisión local se detectó que el estado persistido contenía más progreso
que el resumen previo: el manifiesto tiene 35 cajas, con dos adquiridas, una
fallida (HTTP 504) y 32 pendientes. La última ejecución hizo dos solicitudes
HTTP y omitió una caja que ya estaba en caché. Los dos snapshots contienen 171
elementos recibidos; la consolidación por `(tipo OSM, ID OSM)` deja 168 objetos
únicos y elimina tres observaciones duplicadas. El inventario incluye vías y
13 estaciones `toll_booth`; no se encontraron pórticos `toll_gantry`. El cruce
actual produce coincidencias probables y candidatos por proximidad con AP-68,
pero no confirma estaciones de acceso/salida, sentido de cobro ni costo. Quedan
33 regiones no completadas: la fallida y las 32 pendientes. El informe offline
regenerable detalla cada objeto, su procedencia, distancia a las rutas,
fracción aproximada y cobertura de celdas.

Las 12 respuestas ORS locales registran motor **9.10.0**, perfil
`driving-car` y formato GeoJSON (`/geojson`). Sus `Feature.properties` contienen
`summary`, `segments` y `way_points`, pero no `extras`. Para esa versión, la
documentación enumera `tollways`, `waycategory` y `osmid` como datos disponibles
para `driving-car`, a solicitar mediante `extra_info`. En JSON normal aparecen
en `routes[*].extras`; en el formato GeoJSON de estas respuestas estarían en
`features[*].properties.extras` (las propiedades de cada Feature contienen los
mismos datos de ruta). `osmid` se representa en la respuesta con la clave
`osmId`. Esos atributos ayudarían a enlazar secciones con vías, pero no aportan
tarifas ni prueban estaciones de entrada/salida. Recuperarlos requeriría nuevas
consultas Directions para cada ruta que se quiera enriquecer; no se realizaron
aquí.

El servicio público Overpass comparte capacidad y puede responder 429 o 504;
su guía recomienda consultas pequeñas, y el inventario piloto propuesto son
35 peticiones secuenciales, sin paralelismo. El número no garantiza que cada
caja tenga respuesta ni constituye una cuota prometida. Para España completa,
la adquisición debe ser única por corredor/región con celdas deduplicadas, no
una solicitud por cada uno de los 2.162 arcos. Después se reutiliza el
inventario local para todos los cruces. OSM es una base colaborativa: deben
registrarse `osm_base`, fecha efectiva, instancia, consultas, IDs y atribución;
faltantes cartográficos requieren fuentes oficiales y revisión, y los datos
OSM redistribuidos deben cumplir ODbL.

## 8. Diagnóstico y reanudación del piloto HTTP

Las dos consultas completadas devolvieron 46 y 125 elementos crudos; una de
las respuestas incluye una relación extensa AP-68. El tamaño de la respuesta
puede aumentar el trabajo de consultas futuras, pero no permite atribuir por
sí solo el 504 a esa relación. Las consultas regionales están acotadas por
`[timeout:25]` en Overpass QL. El
transporte Python permite hasta 45 segundos para recibir la respuesta. Cada
caja produce como máximo un POST y el cliente no reintenta automáticamente.
La consulta contiene tres selectores `nwr` y pide `out body geom`; expandir
geometrías de vías y relaciones puede elevar el trabajo y el tamaño de respuesta.

HTTP 504 significa que un gateway/servidor no obtuvo a tiempo una respuesta de
su upstream. HTTP 429 indica limitación o saturación por política de tasa. Son
estados distintos: el 504 observado no demuestra agotamiento de cuota. La
aplicación se detiene ante el primer error, conserva archivos/estado de las
regiones adquiridas y no reintenta dentro de la misma ejecución. En la siguiente
ejecución omite las regiones `adquirida` y puede volver a intentar la región
fallida; si vuelve a fallar con 5xx, marca saturación recurrente y detiene el
lote. El estado y la caché no se borran.

La CLI ahora acepta `--priority 0` para limitar el lote a las regiones
prioritarias que cubren Bilbao–Zaragoza y admite un presupuesto parcial con
`--max-requests N`. Se cuentan por separado las llamadas HTTP y las regiones
completadas, fallidas y pendientes en todo el manifiesto. Se recomienda una
solicitud por ejecución y un intervalo de al menos cinco segundos después de
un 504; no se recomienda repetir de inmediato la misma caja. No se hizo una
nueva llamada como parte de este cambio.

Comando preparado para reanudar solo las celdas prioritarias en lotes de una
solicitud (no ejecutado en esta revisión):

```powershell
& .\.venv\Scripts\python.exe -m src.tsp.etl.overpass_pilot --execute --priority 0 --max-requests 1 --interval-seconds 5
```

Para reducir la carga de una región que vuelve a fallar, debe regenerarse un
plan más fino (por ejemplo, `--cell-degrees 0.25`) y conservar el manifiesto y
estado anteriores. Un cambio de parámetros crea otra huella de plan; por eso
no se debe reutilizar silenciosamente el estado anterior. Las respuestas en
`data/raw/tolls/` y los datos derivados en `data/processed/tolls/` siguen
excluidos de Git mientras se termina la revisión de redistribución ODbL.

## 9. Lista de verificación para confirmar costo AP-68

El valor nominal de 39,90 EUR del tarifario 2026 para clase ligera Bilbao →
Zaragoza no se asigna todavía a ninguna alternativa. Para elevar el hallazgo
cartográfico a un costo monetario verificable deben quedar registrados y
revisados todos estos puntos:

1. **Entrada y salida:** asociar los extremos de la sección tarifada con las
   estaciones oficiales del tarifario; no basta con los nombres de las ciudades.
2. **Cobertura de ruta:** demostrar que la geometría recorre la sección completa
   que corresponde a la pareja tarifaria y no una parte o un enlace próximo.
3. **Sentido y calzada:** comprobar sentido de circulación, calzada y enlaces
   usados. La coincidencia de una relación OSM bidireccional no los determina.
4. **Categoría:** confirmar que BMW 120 corresponde a la categoría oficial
   `Ligeros` para esa tarifa.
5. **Fecha de vigencia:** comprobar que la tarifa citada está vigente en la
   fecha de referencia del experimento y segmentar cualquier cambio de
   operador/regla en el tramo alavés.
6. **Horario y pago:** verificar recargos, bonificaciones, descuentos,
   dispositivos de pago y condiciones horarias aplicables; registrar la tarifa
   base si no se modela una condición personal.
7. **Fuente y extracción:** guardar URL/documento, fecha de consulta, fecha de
   vigencia, página/tabla/celda y regla de lectura de la tarifa.
8. **Revisión independiente:** una segunda persona coteja la correspondencia
   ruta-estaciones y el importe antes de cambiar el estado a verificado.

Hasta completar la lista, el estado del peaje permanece `desconocido` y el
costo económico de esa conexión no es verificable. La relación AP-68 y sus
ways miembro son representaciones cartográficas solapadas de una infraestructura,
no cobros independientes; nunca se suman por separado.
En las celdas adquiridas, la relación AP-68 de OSM se alinea aproximadamente
290,9 km con cada geometría ORS `fastest` Bilbao ↔ Zaragoza. Las candidatas
`avoid_tolls` también se alinean localmente unos 332 m y 259 m con esa relación.
Esto sugiere uso extenso de AP-68 en las rápidas y un cruce/acceso breve en las
candidatas, que debe revisarse cartográficamente. No es una medición de tramo
tarifado. La relación y algunas vías miembro representan partes del mismo
corredor: se conservan por ser IDs OSM diferentes, pero no se suman como
cobros distintos. Las respuestas ORS no contenían `extra_info` (0 de 12), así
que el cruce actual no dispone de identificadores de vía retornados por el
motor.

## 10. Auditoría de cobertura por arco

`src/tsp/etl/toll_coverage.py` resume las etapas de evidencia por conexión
dirigida: distancia/tiempo, geometría adquirida, candidatos de infraestructura,
entrada/salida revisadas, tarifa verificada y completitud económica de los
Modelos A y B. La salida separa expresamente candidatos geográficos de costos
verificados. Para el Modelo B, `model_b_known_options_evaluable` solo indica que
todas las alternativas actualmente registradas para ese arco tienen tarifa
verificada; no afirma que esas alternativas sean exhaustivas.

El informe puede regenerarse offline desde el dataset versionado y los archivos
locales disponibles:

```powershell
.\.venv\Scripts\python.exe -m experiments.report_tsp_toll_coverage
```

Genera `data/processed/tolls/toll_coverage_national.json` y
`toll_coverage_arcs.csv`. Lee el catálogo local de rutas y, si existe, el CSV de
coincidencias Overpass. No consulta APIs. El directorio `data/processed/tolls/`
permanece ignorado por Git, porque sus salidas incluyen datos derivados de OSM.
Si esos archivos locales faltan en otra máquina, el informe conserva en cero
solo los conteos observacionales de geometrías/candidatos; los estados
tarifarios siguen desconocidos y no se infiere una cobertura económica.

En la auditoría del 2026-10-13 se confirmó que el estado persistido cubre 2 de
35 celdas, con 1 fallo 504 y 32 pendientes; el inventario disponible consolida
168 objetos únicos de 171 observaciones (13 `toll_booth`, 155 vías `toll_road`)
y no registra `toll_gantry`. Las 12 alternativas del piloto tienen geometría,
pero ninguna tiene `extra_info` de ORS ni tarifa/entrada/salida verificada. El
dataset nacional sí cubre distancia, duración y combustible para los 2.162
arcos. La cobertura de costo económico completo de A y B permanece en cero;
la tarifa nominal AP-68 de 39,90 EUR no se asigna a ninguna geometría hasta
confirmar sus estaciones, sentido, clase, condiciones y cobertura tarifaria.

## 11. Inventario oficial de corredores y transcripción AP-68

La primera versión de un catálogo de corredores prioritarios queda en
`data/reference/toll_roads_2026.csv`. Se carga y valida con
`load_toll_road_catalog`. Es una lista de trabajo, no un inventario exhaustivo
de cada tramo de peaje de España: la página gubernamental identifica ejes
principales para 2026, mientras que su subsección enlazada “Autopistas con
peaje” aún describe una lista y tarifas de 2024. Por eso los operadores,
secciones exactas y vigencias que no están respaldados por una publicación
2026 aparecen como pendientes, no como hechos inferidos.

La página gubernamental indica que el peaje puede depender del vehículo,
distancia y, en algunos corredores, horario y método de pago. También describe
el pago en ramales de entrada/salida o en tronco y medios efectivo, tarjeta y
VIA-T. La resolución SEITT de 2024 determina el marco de actualización anual
máxima para 2026 en su red; la modificación BOE de diciembre de 2025 mantiene
AP-7 Cartagena–Vera como corredor SEITT y dispone tarifa cero para la
Circunvalación de Alicante. El acuerdo entró en vigor con su publicación el
2025-12-18, así que esa sección tiene tarifa publicada de cero en el escenario
2026. La ruta completa solo puede marcarse gratuita si se demuestra que no
recorre otros tramos tarifados.

Fuentes consultadas el 2026-10-13:

- Punto de Acceso General, “Peajes y Viñetas”, última actualización indicada
  2026-03-19: https://administracion.gob.es/tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas
- Tarifas oficiales de Autopistas: https://www.autopistas.com/tarifas-y-descuentos/tarifas/
- PDF AP-68 2026: https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf
- Acuerdo marco de tarifas SEITT: https://www.boe.es/eli/es/res/2024/12/06/%281%29
- Modificación SEITT publicada como BOE-A-2025-25961:
  https://www.boe.es/eli/es/res/2025/12/10/%282%29/dof/spa/pdf
- Adenda de Circunvalación de Alicante, BOE-A-2026-2970:
  https://www.boe.es/boe/dias/2026/02/09/pdfs/BOE-A-2026-2970.pdf
- Fin de la concesión AVASA AP-68, BOE-A-2026-19039:
  https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-19039
- Tarifas catalanas 2026 (C-16 y C-32):
  https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/peatges-tarifes-descomptes/tarifes-peatges/index.html
- Tramos de peaje gestionados por Bizkaia (AP-8 Galdakao–Ermua, Variante Sur Metropolitana y túneles de Artxanda):
  https://www.bizkaia.eus/es/tema-detalle/-/edukia/dt/6320
- Peajes AP-1 en Álava para el ejercicio 2026:
  https://www.araba.eus/Presupuestos/2026/TOM-2026_PTO-50-02.html
- Decreto gallego 125/2025: tarifas y bonificaciones AG-55/AG-57 durante 2026:
  https://www.xunta.gal/dog/Publicados/2025/20251231/AnuncioG0765-291225-0001_gl.html

### AP-68: tarifa del tramo nominal y rutas del piloto

La tabla oficial de ligeros del PDF AP-68 contiene 39,90 EUR tanto para Bilbao
→ Zaragoza como para Zaragoza → Bilbao; el documento dice que la tabla entra
en vigor el 1 de enero de 2026 e incluye el IVA del 21 %. La transcripción local
de esas dos filas se encuentra en
`data/processed/tolls/ap68_2026_ligeros.csv`, dentro de un directorio ignorado
por Git. Se conserva el documento como URL y página 1, pero no se copia el PDF
al repositorio porque no se ha confirmado una licencia de redistribución del
documento del operador. `published_on` permanece vacío porque la publicación
web no da una fecha inequívoca; `acquired_on` registra la consulta del
2026-10-13. La tarifa se registra como dato del par de estaciones, sin enlazarla
automáticamente a una geometría.

El Real Decreto 730/2026 establece el final de la concesión AVASA el
2026-11-10. Por tanto, los valores del cuadro solo se consideran candidatos
para el escenario anterior a la transición, incluido el 2026-10-12 del estudio;
no se extrapolan al periodo posterior. El documento tiene una matriz de
estaciones de entrada/salida y una tabla separada de estaciones de peaje
abierto. La tarifa Bilbao–Zaragoza no representa todos los movimientos de la
autopista.

Las rutas ORS rápidas locales tienen distancias de 304,1119 km
Bilbao→Zaragoza y 304,8493 km en sentido inverso, e incluyen `AP-68` entre sus
referencias de vía. La relación OSM AP-68 se alinea aproximadamente 290,943 km
con la primera y una longitud similar con la inversa. La única infraestructura
`toll_booth` del inventario local cercana a estas dos rutas es el área de peaje
de Alagón: dos nodos OSM con el mismo nombre, separados por unos 30 m. La
geometría rápida pasa junto a ambos cerca del 91,2 % de la primera ruta y del
9,0 % de la inversa. Pueden corresponder a puntos de cobro/calzada distintos;
la información local no determina su función y no los suma como dos cargos.
El inventario no contiene evidencia
local equivalente de las estaciones terminales de Bilbao/Zaragoza. Estos datos
prueban una coincidencia cartográfica extensa con AP-68, no las estaciones
exactas de entrada/salida, sentido de cobro, recorrido tarifario completo ni
ausencia de otros peajes en los conectores. Las alternativas `avoid_tolls`
también tienen pequeñas coincidencias locales con la relación AP-68, así que
no se pueden etiquetar como libres de peaje.

Resultado conservador: ninguna de las cuatro geometrías AP-68 del piloto
(rápidas y `avoid_tolls`, dos sentidos) obtiene actualmente un total monetario
de ruta. Las tarifas bilaterales 39,90 EUR quedan disponibles como referencia
tarifaria, pero el importe de ruta permanece `desconocido` hasta verificar el
par real de estaciones, dirección/calzada, categoría, condiciones y cobertura
completa. Una futura auditoría puede resolverlo mediante geometría de accesos
y estaciones oficiales, instrucciones/segmentos de ORS con IDs de vía y una
revisión cartográfica de conectores terminales.

El importador `TollTariff` ahora conserva también método de pago, regla
horaria, nombre de documento y página de fuente. Estos campos son opcionales
para seguir aceptando CSV históricos; cuando faltan, el método de pago queda
como `unknown`. La columna `published_on` admite vacío para no inventar una
fecha de publicación.
