# Fase 3C.1 — Preparación de adquisición de datos reales del TSP

**Estado:** plan y generador de manifiesto local. No se ha instalado ningún motor,
descargado un extracto OSM ni consultado la matriz del piloto de cuatro ciudades.
La Fase 3B y su protocolo `TSPObjective` permanecen intactos.

## 1. Estado del repositorio y del equipo

El PR #3 aparece en `origin/main` como `8669ffa` («Merge pull request #3 from
leodavid0109/feature/tsp-dual-model»). `main` local avanzó a ese commit por
`--ff-only`, y esta rama se creó desde allí: `feature/tsp-real-data`. Al iniciar
la preparación, el árbol de trabajo estaba limpio. El contrato compartido sigue
siendo el protocolo estructural de [los modelos duales](tsp_modelo_dual.md).

Inventario de solo lectura obtenido el 2026-10-12:

| Recurso | Observación |
|---|---|
| Sistema | Windows 11 Home Single Language, build 26200, 64 bits |
| Procesador | AMD Ryzen 5 4600H, 12 procesadores lógicos |
| RAM | 15,36 GiB visibles; aproximadamente 4,03 GiB libres al consultar |
| Disco C: | 475,88 GiB totales; 359,08 GiB libres |
| Python | 3.14.7 x64 |
| Herramientas disponibles | Git 2.53.0, Node.js 24.19.0, pip 26.2.1 y curl 8.21.0; no se encontró npm, CMake ni Docker en PATH |
| Docker | No se encontró ejecutable |
| WSL2 | No instalado |
| Git | 2.53.0.windows.3 |

Geofabrik publica para España un PBF comprimido de 1,4 GB con datos hasta
2026-10-11; [la ficha de descarga](https://download.geofabrik.de/europe/spain.html)
a la fecha de consulta indicaba 1.490.515.895 bytes. El disco
puede alojar el PBF y productos derivados, pero la memoria libre medida no basta
para justificar de forma segura la fase de extracción/preprocesamiento. Las
fuentes de OSRM/Valhalla consultadas no dan un mínimo de RAM universal para ese
extracto y versión; por tanto no se inventa una cifra de memoria posterior al
procesamiento. Sin Docker ni WSL, tampoco está listo el entorno Linux habitual
para los contenedores. **Recomendación:** no procesar el PBF español completo en
este equipo ahora. Para una prueba local real, primero autorizar/instalar Docker
Desktop con WSL2 y comprobar memoria pico usando el extracto fijado. La
alternativa es un equipo Linux con memoria suficiente, una VM o una máquina
temporal; el piloto de cuatro nodos no reduce por sí solo el tamaño de la red
necesaria para conectar Bilbao, Zaragoza, Madrid y Toledo.

## 2. Motor y adquisición

### OSRM (recomendado como motor principal)

La [API de OSRM](https://project-osrm.org/docs/v26.4.0/api/) ofrece `table` para tiempos y distancias de las rutas más rápidas según el
perfil; duración se expresa en segundos y distancia en metros. Una solicitud
con las 47 coordenadas produce las 2.209 celdas, incluidas diagonal y 2.162
conexiones dirigidas no diagonales. La página oficial de herramientas documenta
por defecto un límite de 100 ubicaciones para tablas, configurable en el
servidor, por lo que 47 ubicaciones caben en una petición si se conserva esa
configuración. `table` no devuelve geometrías. Estas se obtienen con `route` por
par ordenado, guardando la geometría GeoJSON completa y pasos/clases.

El [perfil oficial `car.lua`](https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua)
incluye clase `toll` entre las clases que pueden
excluirse. El parámetro `exclude=toll` permite solicitar una ruta candidata sin
vías marcadas con esa clase, **si** el grafo se preprocesó con el mismo perfil y
con sus clases excludables. No significa que OSRM haya probado que no se cobra:
la etiqueta OSM puede faltar, estar desactualizada o representar una situación
distinta a la tarifa actual. Se validará la geometría resultante y se contrastará
con inventario oficial de concesiones y tarifas. `alternatives=2` solicita como
máximo alternativas a la ruta recomendada y no promete una ruta alternativa.

Para el Modelo A conviene usar la ruta rápida de OSRM como alternativa fija por
arco. Para el Modelo B, registrar además: (1) una alternativa `exclude=toll`
cuando la consulta la encuentre y su geometría pase verificación; (2) las rutas
que OSRM devuelva con `alternatives`; y (3) una candidata de otro perfil/motor
solo si hay una razón experimental documentada. El Modelo B elegirá entre los
registros verificados disponibles, no entre rutas desconocidas. No se usarán
las alternativas del demo público para poblar miles de arcos.

Instalación futura, únicamente tras aprobación: fijar imagen OSRM por versión o
digest, descargar un PBF fechado, verificar su hash y atribución/licencia,
ejecutar `osrm-extract` con perfil `car.lua`, `osrm-partition` y
`osrm-customize` (flujo MLD), luego servirlo con `osrm-routed --algorithm mld`.
La fuente oficial de OSRM proporciona el ciclo y opciones de perfil. No se
incluyen aquí comandos ejecutables con etiqueta `latest`: la versión de motor,
imagen y perfil debe quedar aprobada y congelada antes de adquirir datos.

### Valhalla (alternativa secundaria)

Valhalla tiene [servicios locales de matriz](https://valhalla.github.io/valhalla/api/matrix/api-reference/)
y [ruta](https://valhalla.github.io/valhalla/api/route/api-reference/), `auto` con geometría y
opciones dinámicas. Su parámetro `use_tolls` es una **preferencia suave**: valores
cercanos a cero [intentan evitar](https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/)
carreteras de peaje, pero no garantizan que la
ruta sea gratuita. La respuesta puede marcar `has_toll`; se debe inspeccionar y
verificar, nunca tratar el parámetro como certificado tarifario. Para autoalojar
la documentación recomienda imágenes Docker o generar tiles a partir de PBF.
Eso agrega tiles, configuración y operación; requiere fijar la misma fecha OSM y
versión para hacer una comparación de motor justa. Se recomienda como contraste
del perfil de evitación o si OSRM no ofrece una alternativa, no como segunda
fuente automática de «ruta libre».

| Criterio | OSRM local | Valhalla local |
|---|---|---|
| Matrices y rutas | `table` y `route`; tabla eficiente, rutas/geometry aparte | API matrix y route; respuesta de rutas con forma |
| Alternativas | `alternatives` puede no devolverlas; `exclude=toll` con perfil preparado | Costing dinámico; `use_tolls=0` intenta evitarlas, no es exclusión dura |
| Datos | Extracto OSM PBF + extracción y preparación del grafo | Extracto OSM PBF + construcción de tiles/configuración |
| Coste operativo | Menor complejidad para la matriz y compatibilidad con el piloto previo | Más opciones de costing, más configuración/tiles que validar |
| Peaje monetario | No calcula tarifa oficial | No calcula tarifa oficial |
| Elección | Motor principal para A y candidatos de B | Contraste técnico opcional después del piloto |

El [servicio demo OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
es de mejor esfuerzo, sin garantía; su política permite
uso razonable con atribución y prohíbe uso excesivo. No se usará para adquisición
completa. La licencia ODbL de OpenStreetMap exige atribución y puede imponer
obligaciones al compartir bases derivadas; la forma de publicar geometrías y
artefactos derivados ([licencia ODbL](https://www.openstreetmap.org/copyright))
deberá revisarse conforme a la licencia antes de subirlos.

## 3. Unidad de datos y trazabilidad

Conservar estos artefactos separados:

1. **Catálogo canónico**: `city_id` y orden actual del CSV; puntos IGN originales
   sin cambios, en latitud/longitud y con URL/fecha/fuente.
2. **Manifiesto de adquisición**: ciudades y orden de coordenadas enviadas,
   servicio, parámetros, motor/versión, perfil y hash/fecha del PBF.
3. **Respuestas crudas**: JSON de OSRM/Valhalla y geometrías completas, con
   metadatos de petición; no editar a mano las respuestas.
4. **Puntos ajustados**: coordenadas de snapping devueltas como campos separados
   de la coordenada IGN. Registrar distancia de snapping; investigar outliers.
5. **Alternativas**: una fila por arco dirigido y alternativa, compatible con
   `RouteAlternative`; tiempos en horas, distancia en km y moneda EUR. Cada
   importe requiere fuente/vigencia y estado de verificación.
6. **Matrices derivadas**: exportar filas/columnas en el orden canónico y
   documentar la transformación de segundos→horas, metros→km y euros. Guardar
   hash, código/versión de script y manifiesto de ejecución.

El extracto grande no debe ir al historial Git. Se puede conservar como
artefacto externo del equipo, con URL exacta, fecha de corte, tamaño, SHA-256,
licencia y ubicación durable; los datos derivados mínimos para ejecutar los
experimentos sin internet sí deben quedar empaquetados en el repositorio si su
redistribución está permitida. Las URLs y fechas no bastan para reproducir un
extracto cambiante: se requiere el archivo fijado o un artefacto preservado.

## 4. Tratamiento de peajes

La detección tiene dos capas distintas:

1. **Candidata cartográfica**: detectar clase/tag `toll` o etiqueta de peaje en
   los segmentos y pasos de la ruta; conservar vía, geometría y sentido. Esto
   sirve como alerta, no como tarifa ni como verdad jurídica.
2. **Verificación operativa**: cruzar la geometría con el inventario oficial
   del operador/administración vigente en la fecha de referencia. Identificar
   estación de entrada y salida, concesión, categoría de vehículo (`ligeros`),
   sentido y modalidad de pago aplicable. Consultar la tarifa publicada por el
   operador, BOE o administración competente. Sumar únicamente los tramos
   efectivamente recorridos. Registrar descuentos solo si el caso de uso los
   define y documenta; no asumir tarjetas, abonos, horarios o descuentos.

Estados del modelo: `verificado_con_peaje` (importe oficial, vigencia y par de
estaciones cotejados), `verificado_sin_peaje` (geometría completa cotejada con
fuentes vigentes), y `desconocido`. `desconocido` mantiene importe nulo y bloquea
un costo económico verificable. Un tramo AP no implica peaje vigente y una ruta
que toca una autopista no prueba que haya recorrido el tramo tarifado completo.

Automatizable: leer geometrías/pasos/clases, extraer IDs/nombres de vías,
consultar candidatos cartográficos, unir espacialmente contra un inventario
versionado, comprobar cobertura espacial y producir una cola de revisión.
Revisión manual necesaria: confirmar que la concesión cobra en la fecha elegida,
interpretar tablas de entrada/salida, categoría/horario/modalidad y aclarar
desacuerdos entre tags OSM y fuentes oficiales. No se encontró evidencia de una
API oficial española única y completa que entregue precio real para cualquier
par de estaciones de todas las concesiones; por tanto no se presupone.

Registro tarifario propuesto por segmento usado:

```text
route_id, segment_id, road_or_concession, entry_station, exit_station,
vehicle_category, direction, amount, currency, tariff_source_url,
valid_from, valid_through, checked_on, payment_method, verification_status,
calculation_method, notes
```

El total de peaje por ruta es suma de segmentos verificados; falta de un precio
para cualquier segmento produce total desconocido, no cero. El piloto anterior
contiene una tarifa AP-68 nominal de 39,90 € Bilbao–Zaragoza en la tabla 2026,
pero su imputación a esa ruta exacta requiere cotejar entradas/salidas y su
vigencia temporal; no es un precio nuevo adquirido en esta fase.

## 5. Vehículo y gasolina

BMW España identifica el [BMW 120 Serie 1 generación F70](https://www.bmw.es/es/coches-bmw/serie-1/bmw-serie-1/caracteristicas.html)
de 125 kW/170 CV y
publica consumo combinado WLTP de 5,3–5,5 l/100 km. BMW Group describe esa
configuración de lanzamiento como motor gasolina de tres cilindros y 1.499 cm³,
mild hybrid de 48 V, cambio automático Steptronic de doble embrague de 7
velocidades y tracción delantera. BMW España recomienda gasolina de 95 octanos.
La ficha española actual no asocia los extremos del intervalo WLTP con un
acabado/llanta inequívoco en la página consultada; el informe Vehicle Footprint
corresponde a un vehículo base seleccionado al inicio de producción y no
demuestra el valor de la configuración que el equipo vaya a fijar. Falta elegir
acabado/ruedas y recuperar su cifra WLTP por ficha exacta/COC o registro IDAE.
No se asigna 5,3, 5,4 ni 5,5 como valor del experimento por conveniencia.

MITECO lista [gasolina 95 E5](https://www.miteco.gob.es/es/energia/hidrocarburos-nuevos-combustibles/euros-por-100-km/metodologia.html)
como combustible representativo y declara que su
metodología promedia los PVP diarios informados durante el trimestre civil
anterior. La página pública consultada muestra una actualización del 2026-09-23
y 9,82 €/100 km para gasolina 95 E5 ([tabla consultada](https://www.miteco.gob.es/es/energia/hidrocarburos-nuevos-combustibles/euros-por-100-km/coste-euro-100km.html)). Esa cifra no es €/L y la página no muestra
en esa vista un precio unitario con el detalle suficiente para atribuirla al
trimestre natural Q3 completo (01-07 a 30-09). Por ello **no es el precio de
gasolina del modelo** y no se convierte a €/L usando un consumo aproximado.

Procedimiento propuesto para el precio Q3 2026: verificar después del cierre del
trimestre que el histórico oficial del Geoportal/API MITECO proporciona las
observaciones de Gasolina 95 E5 para 2026-07-01..2026-09-30; guardar JSON/CSV
original, consulta, zona/unidades y hash. Confirmar en metadatos el nivel de
agregación nacional usado por MITECO. Si solo están disponibles observaciones
por estación, calcular primero el promedio aritmético de estaciones reportadas
por cada día y después el promedio de días con datos (pesos iguales por día),
documentándolo como cálculo del proyecto, no como cifra publicada por MITECO.
Reportar cobertura diaria y no rellenar días faltantes. El precio del proyecto
será el resultado a EUR/L, con periodo, regla de agregación, fecha de extracción
y recurso crudo. No fijarlo hasta comprobar el endpoint/histórico y sus
metadatos. A fecha de esta preparación no se consultó el recurso histórico ni se
calculó un precio Q3.

Combustible por ruta, una vez elegida configuración: `F = (D_km / 100) ×
q_WLTP × p_EUR/L`. Es un costo operacional estimado según WLTP combinado; no
representa consumo observado en las rutas ni ajusta carga, conducción, clima,
pendiente o tráfico.

## 6. Prueba de adquisición de cuatro ciudades

El módulo `experiments.prepare_tsp_pilot` crea un **plan local** desde el CSV
verificado, sin conectarse a internet ni producir distancias/rutas. Para
inspeccionarlo:

```powershell
python -m experiments.prepare_tsp_pilot
```

El plan conserva orden `madrid, toledo, bizkaia, zaragoza` y las coordenadas
IGN `[longitude, latitude]`, y enumera 12 pares dirigidos. Describe una tabla
rápida OSRM (4×4), consultas `route` por cada arco para geometría y candidatas
con `exclude=toll`; no declara resultados. Puede validarse con:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp-tsp-acq tests/test_tsp_acquisition_plan.py
```

Para una prueba **local real** se necesitará el PBF de España porque los cuatro
nodos están en regiones separadas y recortar solo alrededor de las ciudades
rompería la conectividad entre ellas. Requisitos por autorizar: Docker Desktop/
WSL2 o un host Linux, descarga única aproximada de 1,4 GB (PBF actual; el corte
se debe fijar), espacio para PBF y grafo procesado, imagen/versión OSRM, y
prueba de memoria pico del preprocesamiento. Almacenamiento libre detectado
(359 GiB) parece suficiente en disco, pero RAM libre (4,03 GiB) y ausencia de
runtime Linux hacen que el ensayo local quede **pendiente**.

Cuando se apruebe el entorno, comandos de alto nivel (se completarán con tags y
montajes concretos de la versión elegida; no ejecutar hasta esa aprobación):

```text
docker pull osrm/osrm-backend:<versión-fijada>
docker run ... osrm-extract -p /opt/car.lua /data/spain.osm.pbf
docker run ... osrm-partition /data/spain.osrm
docker run ... osrm-customize /data/spain.osrm
docker run ... osrm-routed --algorithm mld /data/spain.osrm
python -m experiments.prepare_tsp_pilot > pilot_request_plan.json
```

La última línea solo produce un plan. Un cliente de adquisición, cuando se
implemente y apruebe, debe: guardar solicitud y respuesta sin pérdidas, comprobar
HTTP/`code=Ok`, cuatro waypoints y 4×4 tablas, valores finitos/no negativos,
ausencia de `null` y fallback, conversión de unidades, ajuste de coordenadas,
direcciones separadas, las 12 geometrías y estado de peaje. `exclude=toll` se
acepta como *candidato* solo después de inspeccionar sus segmentos; el costo
gratuito solo se certifica con fuentes oficiales. Criterios: 12 arcos, ninguna
dirección inferida por simetría, coordenadas ajustadas registradas aparte,
respuestas crudas preservadas y peajes/costos no verificables marcados como
desconocidos.

## 7. Secuencia de adquisición completa

1. Congelar orden e IDs de `capitales_peninsulares.csv`, revisión de coordenadas
   y fecha IGN. No geocodificar nombres de nuevo.
2. Fijar fecha/hora de corte OSM, versión y hash PBF, licencia/atribución,
   imagen OSRM por digest, `car.lua`/hash, algoritmo MLD y parámetros. Conservar
   originales IGN y registrar cada punto ajustado de OSRM.
3. Consultar tabla dirigida `distance,duration` para 47 ubicaciones; 2.209
   celdas, validar 47 filas×47 columnas, 47 ceros diagonales según servicio y
   2.162 celdas no diagonales conectadas. No convertir `null` en distancia por
   línea recta.
4. Consultar/guardar ruta y geometría para los 2.162 arcos rápidos si se
   requiere identificar peaje; obtener rutas `exclude=toll` y alternativas
   devueltas en otro conjunto de registros. Validar geometrías y deduplicar por
   geometría normalizada (con dirección), longitud/tiempo y secuencia de vías;
   OSRM no promete exhaustividad.
5. Producir un mapa de tramos candidatos a peaje a partir de geometrías, clases
   y vías OSM. Contrastar cada tramo con operadores/administración oficial y
   resolver entradas/salidas manualmente donde sea necesario.
6. Congelar tarifa nacional Gasolina 95 E5 del periodo Q3 validado y variante
   WLTP exacta, guardar fuentes/fecha. Calcular combustible sin redondeos
   intermedios; redondear solo presentación.
7. Emitir catálogo de alternativas y matrices A/B derivadas para un valor
   horario; mantener celdas incompletas marcadas y el evaluador actual fallando
   explícitamente cuando el costo no sea verificable.
8. Ejecutar validación de integridad (cobertura de pares, asimetría, unidades,
   límites, vigencia de peajes, fuentes, hashes, coordenadas, alternativas) y
   generar manifiesto, resumen de faltantes y archivos reproducibles sin red.

No toda geometría ni cada fila cruda necesariamente se debe mantener en Git: se
medirá su tamaño; se conserva en Git el conjunto derivado necesario para correr
los experimentos offline y se mantiene el crudo mediante artefacto versionado si
licencia y repositorio lo permiten.

## 8. Riesgos y decisiones pendientes

- Autorizar o no Docker Desktop/WSL2 y descarga del PBF de España; comprobar
  memoria pico en una ejecución pequeña controlada.
- Fijar versión/digest OSRM, extracto/fecha OSM, `car.lua` y regla de ajuste de
  coordenadas.
- Determinar si `exclude=toll` cubre las etiquetas que necesitamos y auditar
  falsos negativos/positivos contra tarifas oficiales.
- Acordar estrategia si falta precio verificable por tramo: mantener costo
  desconocido y retrasar ese arco, o restringir dataset a rutas con verificación.
- Elegir acabado/ruedas exactos del BMW 120 y obtener su WLTP de COC/IDAE/ficha
  oficial aplicable.
- Consultar el histórico MITECO de Gasolina 95 E5 para el Q3 2026 ya cerrado y
  validar metadatos/regla de agregación antes de fijar EUR/L.
- Definir el formato/ubicación durable para el PBF grande y respuestas con
  geometrías, revisando ODbL.

No se modificó la Parte 1 ni el contrato GA/ACO. No hay rutas, peajes o precios
de España inventados por esta fase, ni resultados del piloto de cuatro ciudades.
