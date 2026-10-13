# Revisión de rutas reales y prioridad de adquisición (fase 5H)

Fecha de revisión: 2026-10-13. Fecha de referencia económica: 2026-10-12.
Este informe usa exclusivamente el dataset nacional publicado y los archivos
locales de Directions y Overpass ya adquiridos. No se efectuaron nuevas consultas
ORS, Overpass ni TollGuru. Atribución de las rutas: © openrouteservice by HeiGIT;
datos © OpenStreetMap contributors. Los resultados ORS están sujetos a
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) y la base OSM a
[ODbL](https://www.openstreetmap.org/copyright).
El catálogo Directions registra adquisición el 2026-10-13, motor ORS 9.10.0
y versión de datos de red informada `2026-09-21T10:31:27Z`. Las respuestas
originales permanecen en `data/raw/routes/`, excluidas de Git.

## Resultado económico verificable

**Cero rutas reales tienen todavía un peaje total verificado.** La matriz vial
contiene 2162 arcos dirigidos; seis tienen geometría rápida. Dos rutas rápidas
presentan indicios cartográficos de infraestructura de peaje, pero ninguna tiene
entrada, salida y cobertura tarifaria completa certificadas. No se publica un
costo económico total para esos arcos ni se convierte un peaje desconocido en cero.
El archivo local `data/processed/tolls/verified_real_routes.csv` se genera con
encabezado y cero filas. Su fuente es el registro de evidencia de ruta revisada,
no la proximidad a un objeto OSM.

| Ruta rápida | ID y SHA-256 de geometría | Dirección ORS: km / h | Matrix: km / h | Diferencia absoluta: km / min | Combustible Directions, € | Peaje total |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Madrid → Toledo | `ors-fast-155a644304e93d3c`; `1ed2d7e3d7a295d65089bf58edd0695ca0169b81dab2c28293dadaa5e8677c7a` | 74,1794 / 0,9719167 | 74,17938 / 0,9719139 | 0,00002 / 0,00017 | 7,406911 | Desconocido |
| Bilbao → Zaragoza | `ors-fast-1f0905404de0ef2a`; `24b17388327d79cee531e357d39b1db40bef501f0c6ad4b049209c30e69c2890` | 304,1119 / 2,9471944 | 304,11184 / 2,9471917 | 0,00006 / 0,00017 | 30,365973 | Desconocido |
| Zaragoza → Bilbao | `ors-fast-5a313ddea76c91b1`; `2c9b8e1b7fabc12e9cf22da5dd50da61ed0c438c163469fc70bad284fb1ba17c` | 304,8493 / 2,9745833 | 304,84934 / 2,9745889 | 0,00004 / 0,00033 | 30,439603 | Desconocido |

El combustible de esta tabla se calculó con la distancia **Directions**,
5,4 L/100 km y 1,849098397 €/L. El dataset publicado contiene un precio
representado como 1,849098398 €/L; su diferencia de 0,000000001 €/L no es una
igualdad exacta y se conserva como procedencia distinta. Las pequeñas diferencias
Matrix–Directions no prueban identidad de geometría ni equivalencia tarifaria.
Las duraciones son estimaciones ORS, no mediciones de tráfico.

Para los valores horarios de 10, 25 y 50 €/h, las sumas **tiempo + combustible**
son respectivamente 17,126 / 31,705 / 56,003 € (Madrid→Toledo),
59,838 / 104,046 / 177,726 € (Bilbao→Zaragoza) y
60,185 / 104,804 / 179,169 € (Zaragoza→Bilbao). No son costos económicos
totales: a cada cifra le falta un peaje aún desconocido.

## AP-68: evidencia y bloqueo preciso

Las respuestas Directions rápidas identifican un paso `AP-68` de 292,900 km
en Bilbao→Zaragoza (índices de geometría 114–2678; entrada aproximada
`[-2.9182, 43.235052]`, salida `[-0.934055, 41.67774]`) y de 291,710 km
en sentido inverso (índices 115–2694; entrada aproximada
`[-0.957056, 41.687584]`, salida `[-2.926988, 43.240852]`). Estas coordenadas
son extremos de la **instrucción ORS**, no estaciones de peaje certificadas.
La relación OSM `283102` presenta alineamiento extenso, pero el inventario
Overpass local cubre solo una cuarta parte de las celdas del corredor. Los dos
nodos cercanos al peaje de Alagón tampoco identifican por sí solos el pago.

El [tarifario oficial AP-68 de 2026](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf),
página 1, publica 39,90 € para el par nominal Bilbao–Zaragoza en **ligeros** en
ambos sentidos, con entrada en vigor el 1 de enero de 2026. BMW 120 corresponde
a la categoría de turismo ligero. El PDF distingue estaciones, enlaces y peajes
abiertos; el valor nominal solo sería aplicable al recorrido ORS si sus accesos,
salidas y condiciones coincidieran exactamente. La [norma de finalización de la
concesión AVASA](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-19039)
fija el 10 de noviembre de 2026, posterior a nuestra fecha de referencia.

Pendiente para cada sentido: identificar sobre la geometría el enlace real de
entrada y salida, la calzada y estaciones cobradoras; contrastarlos con la
matriz de ligeros y con la tarifa ordinaria sin descuentos; revisar peajes
abiertos y conectores fuera de AP-68; documentar cobertura completa y revisión
humana. El registro local `ap68_route_evidence.json` conserva ambos sentidos
como pendientes, con hash exacto y estaciones nulas. No se asignan 39,90 €.

Las variantes `avoid_tolls` son diferentes: 336,9379 km y 4,317472 h en
Bilbao→Zaragoza; 335,5249 km y 4,335750 h en el inverso. Sus peajes también
son desconocidos; `avoid_tolls` expresa una preferencia de enrutamiento, no
una certificación tarifaria. Sin dos opciones valoradas, el Modelo B todavía no
puede decidir económicamente este par. Se mantendrán siempre juntos tiempo,
distancia, combustible y eventual peaje de la **misma** geometría.

## Madrid → Toledo: intento de certificar cero

El [BOE sobre SEITT](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-2970)
identifica AP-41 como autopista de peaje Madrid–Toledo. La
[información gubernamental sobre peajes](https://administracion.gob.es/tu-espacio-europeo/derechos-obligaciones/ciudadanos/vehiculos/normas-trafico-viales/peajes-vinetas)
enumera corredores tarifados, pero no certifica por omisión que cualquier
trayecto concreto sea gratuito. En la respuesta ORS Madrid→Toledo hay una
instrucción de 68,308 km con nombre `Plaza del Emperador Carlos V` (índices
25–557), desde `[-3.692427, 40.408737]` hasta `[-4.019735, 39.881551]`;
un punto intermedio es `[-3.819017, 40.159485]`. Son coordenadas `[lon, lat]`
de la geometría ORS, útiles para revisión manual en el
[Mapa Oficial de Carreteras 2026](https://publicaciones.transportes.gob.es/mapa-oficial-de-carreteras-2026-edicion-61).
No hay `extra_info` ni IDs OSM de cada vía. La etiqueta no describe
fiablemente los 68 km; la ruta podría seguir A-42, pero la evidencia local no
prueba que todos sus segmentos eviten AP-41 y cualquier otro peaje.

Para elevar esta ruta a `VERIFIED_ZERO` se necesita un inventario completo de
los segmentos realmente transitados, con referencias viales y evidencia de
ausencia de peajes vigentes en cada tramo, enlazado al hash de geometría y
revisado por una persona. La acción limitada recomendada es solicitar **una**
respuesta Directions enriquecida para Madrid→Toledo con los `extra_info` que
ORS soporte (`tollways`, `osmid`, `waycategory`), tras comprobar su esquema y
presupuesto, o hacer una revisión manual de la geometría sobre el mapa oficial
y las reglas AP-41. No se realizó esa solicitud en esta fase.

## Cola reproducible para nuevas geometrías

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m experiments.prioritize_tsp_direction_queue
.\.venv\Scripts\python.exe -m experiments.report_tsp_toll_coverage
```

El primer comando valida hashes del dataset publicado, usa recorridos
auxiliares NN, NN+2-opt y AS para `v=10,25,50` €/h (AS semillas 42 y 43,
presupuesto 80; NN 47 y NN+2-opt 200 evaluaciones) y excluye las seis
geometrías rápidas existentes. La prioridad es
`100 × frecuencia en 12 recorridos + 10 × indicio de corredor + min(horas Matrix, 10)`;
un indicio por extremos **no demuestra** que el trayecto use esa vía. Los archivos
locales ignorados son `data/processed/tolls/prioritized_queue/directions_priority.csv`
y `priority_manifest.json`. El segundo comando regenera cobertura y
`verified_real_routes.csv`, que permanece vacío hasta que exista evidencia
completa. Ambos funcionan offline.

Primeras veinte conexiones sugeridas, todas con Matrix y combustible, sin
geometría rápida ni peaje total:

| Posición | Arco dirigido | Apariciones / 12 | Motivo adicional |
| ---: | --- | ---: | --- |
| 1 | Tarragona → Barcelona | 8 | Frecuencia en los tres métodos |
| 2 | Segovia → Ávila | 7 | Frecuencia en los tres métodos |
| 3 | Salamanca → Zamora | 7 | Frecuencia en NN y AS |
| 4 | Valladolid → Palencia | 7 | Frecuencia en los tres métodos |
| 5 | Valencia → Teruel | 6 | Frecuencia en los tres métodos |
| 6 | Huesca → Lleida | 6 | Frecuencia en los tres métodos |
| 7 | Granada → Jaén | 6 | Frecuencia en AS y NN+2-opt |
| 8 | Castellón → Valencia | 6 | Frecuencia en los tres métodos |
| 9 | Murcia → Alicante | 6 | Frecuencia en los tres métodos |
| 10 | Zaragoza → Huesca | 6 | Frecuencia en los tres métodos |
| 11 | Pontevedra → A Coruña | 5 | Frecuencia; posible corredor AP-9 por extremos |
| 12 | Girona → Castellón | 5 | Frecuencia en NN y NN+2-opt |
| 13 | Gipuzkoa → Zaragoza | 5 | Frecuencia en los tres métodos |
| 14 | Cádiz → Huelva | 5 | Frecuencia en AS y NN+2-opt |
| 15 | Cuenca → Albacete | 5 | Frecuencia en NN y NN+2-opt |
| 16 | Albacete → Murcia | 5 | Frecuencia en los tres métodos |
| 17 | Soria → La Rioja | 5 | Frecuencia en AS y NN+2-opt |
| 18 | Badajoz → Cáceres | 5 | Frecuencia en los tres métodos |
| 19 | Pontevedra → Ourense | 5 | Frecuencia en los tres métodos |
| 20 | Lugo → A Coruña | 5 | Frecuencia en los tres métodos |

Un primer lote de cinco arcos supone **como máximo cinco solicitudes HTTP
Directions**, incluidos reintentos; el comando los desactiva. Antes de
autorizarlo, el modo sin `--execute` ya validó los cinco IDs y no hizo red:

```powershell
.\.venv\Scripts\python.exe -m experiments.acquire_tsp_routes --pairs "tarragona:barcelona,segovia:avila,salamanca:zamora,valladolid:palencia,valencia:teruel" --strategy fastest --max-requests 5 --max-http-requests 5 --max-retries 0
```

Cuando se autorice una adquisición posterior, se añade `--execute` al mismo
comando. El almacén existente omite solicitudes ya válidas y conserva las
respuestas originales en directorios excluidos de Git. Cinco adquisiciones
correctas elevarían las geometrías rápidas de 6 a 11 de 2162; **no** elevarían
automáticamente la cobertura económica, que exige revisión tarifaria.

La cola ayuda a decidir dónde adquirir primero; no garantiza contener arcos
del óptimo global económico. La solución nacional sigue bloqueada por el peaje
de 2162 arcos y por alternativas verificadas para el Modelo B.
