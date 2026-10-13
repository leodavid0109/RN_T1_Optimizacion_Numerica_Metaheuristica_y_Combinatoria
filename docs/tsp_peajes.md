# Inventario y tarifas de peajes del TSP

**Estado al 2026-10-12:** código y pruebas con fixtures sintéticos; no se ha
consultado Overpass durante esta fase, no se han descargado datos OSM y no se
han asignado nuevas tarifas a las 12 rutas ORS.

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

`match_infrastructure_to_route` mide la distancia mínima de las geometrías y
devuelve una fracción aproximada del avance de ruta, un umbral explícito y las
etiquetas que dan contexto de sentido. El nivel de resultado es siempre
`candidato_proximidad`. La proyección local equirectangular sirve para filtrar
candidatos en radios cortos; no se considera prueba topológica. Una estación al
lado de la calzada contraria, una vía paralela, un ramal o una salida cercana
pueden quedar a poca distancia y no haber sido recorridos.

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

La ruta piloto Bilbao ↔ Zaragoza contiene segmentos nombrados AP-68 en ORS,
pero no hemos reconsultado ORS en esta fase ni demostrado exactamente sus
entradas/salidas. Además, desde 2026-11-11 el tramo alavés entra en un nuevo
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
