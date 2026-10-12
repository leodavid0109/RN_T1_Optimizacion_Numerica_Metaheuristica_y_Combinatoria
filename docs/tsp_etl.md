# ETL local de rutas para el TSP

## Alcance y separación

`src/tsp/etl/` separa adquisición, persistencia y reconstrucción. Importar el paquete no abre conexiones. Las llamadas solo se producen al invocar `OpenRouteServiceProvider` desde `experiments/acquire_tsp_routes.py` con `--execute`; la reconstrucción con `experiments/build_tsp_matrices.py` es exclusivamente offline.

- `AcquisitionRequest` representa una conexión dirigida y sus coordenadas IGN en orden longitud/latitud. Su identificador depende de extremos, coordenadas y estrategia; el estado de adquisición también separa el perfil del motor.
- `OpenRouteServiceProvider` usa la API Directions v2 para obtener resumen, geometría y alternativas devueltas por el proveedor; puede pedir una preferencia rápida o evitar `tollways`. Un resultado sin tarifa conserva `TollStatus.UNKNOWN` y `toll_cost_eur=None`.
- El endpoint Matrix del mismo adaptador transforma metros a km y segundos a horas. La respuesta Matrix carece de geometría y no reemplaza Directions para rutas alternativas o verificación vial.
- `AcquisitionManager` exige un máximo de solicitudes explícito, omite estados ya adquiridos y controla una cuota diaria configurable. HTTP 429 y 5xx reciben reintentos acotados y se respeta `Retry-After`; 401/403 se detienen sin reintento.
- `RouteStore` conserva el catálogo canónico en CSV, la respuesta y petición sin credenciales en JSON y un registro de estado. Las respuestas se identifican por hash para conservar versiones de refresco; las verificaciones de peaje/combustible solo se conservan al refrescar cuando coinciden arco, geometría, distancia y duración. Si la ruta cambió, el registro anterior se archiva en `data/raw/routes/catalog_history/` y el nuevo costo queda pendiente. Escribe los archivos de forma atómica; no existe transacción entre catálogo, JSON y estado, así que una interrupción puede causar una consulta repetida, no la pérdida del CSV previo.
- `build_matrix_files` crea matrices CSV dirigidas con identificadores y manifiesto de orden/unidades. Las celdas no verificadas quedan vacías. La matriz de costo económico no se escribe si faltan peajes, combustible, arcos o valor horario.

El catálogo crudo no altera `RouteAlternative`, `AlternativeTSPProblem`, `TSPProblem` ni `TSPObjective`. Los peajes desconocidos y combustible pendiente permiten conservar datos de ruta; el evaluador económico existente seguirá rechazando registros incompletos. Cuando todas las entradas sean verificables, el cargador `load_complete_matrix` asegura orden, forma y valores completos antes de entregar una matriz inmutable al modelo.

## Reproducibilidad y credenciales

La clave de ORS se entrega solo mediante la variable de entorno `ORS_API_KEY`. El cliente nunca la agrega al manifiesto, a la URL ni al JSON guardado. El archivo `configs/tsp_etl.yaml` contiene parámetros no secretos que consumen los tres comandos ETL, incluida la tasa de consulta y un límite orientativo del plan Standard que debe cotejarse antes de cada adquisición; los flags pueden ajustarlos.

En la revisión del 2026-10-12 la variable estaba **ausente**. Para cargarla solo en la sesión PowerShell actual, sin imprimirla en pantalla ni escribirla en el repositorio:

```powershell
$secure = Read-Host "Clave ORS" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:ORS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
Remove-Variable secure, ptr
```

La variable desaparece al cerrar esa sesión. En la revisión del 2026-10-12 el valor persistente de usuario estaba definido, pero el entorno de PowerShell y el proceso hijo de `.venv` no lo tenían; un proceso de Codex ya abierto no recibe retroactivamente cambios del entorno de usuario. Se puede usar el bloque anterior en la sesión actual o cerrar completamente y reiniciar Codex para heredar la variable persistente. No guardar el secreto en scripts, YAML, historial del repositorio o logs. Establecerla no ejecuta ninguna solicitud automáticamente.

Planificar sin red (reemplazar los ids por cualquier arco válido del catálogo):

```powershell
python -m experiments.acquire_tsp_routes --pairs madrid:toledo,toledo:madrid `
  --strategy fastest --max-requests 2
```

Una adquisición real requerirá autorización explícita del equipo, una clave válida y la revisión de cuota/condiciones vigentes:

```powershell
$secure = Read-Host "Clave ORS" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:ORS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
python -m experiments.acquire_tsp_routes --pairs madrid:toledo,toledo:madrid `
  --strategy fastest --max-requests 2 --execute
```

Plan de una matriz pequeña y solicitud real, si se autoriza. `--max-cells` cuenta N², incluida la diagonal; `--city-ids` fija el orden del CSV:

```powershell
python -m experiments.acquire_tsp_matrix --city-ids madrid,toledo,bizkaia,zaragoza --max-cells 16
python -m experiments.acquire_tsp_matrix --city-ids madrid,toledo,bizkaia,zaragoza `
  --max-cells 16 --execute
```

Un snapshot Matrix conserva las ubicaciones de origen/destino resueltas por el proveedor en el JSON original cuando son devueltas, además de coordenadas IGN, orden y matrices normalizadas. Directions conserva geometría por ruta.

Agregar un candidato que evite vías etiquetadas como peaje requiere una consulta aparte por arco:

```powershell
python -m experiments.acquire_tsp_routes --pairs madrid:toledo `
  --strategy avoid_tolls --max-requests 1 --execute
```

La opción de evitar peajes solo solicita una ruta candidata según atributos cartográficos; no prueba que el trayecto esté libre de peaje ni asigna una tarifa. `--refresh` vuelve a consultar explícitamente el registro. Para minimizar mezclas de versiones de red, una actualización debe regenerar de forma coordinada los registros rápidos y alternativos de un conjunto experimental.

Reconstrucción offline:

```powershell
python -m experiments.build_tsp_matrices --mode fastest
python -m experiments.build_tsp_matrices --mode economic --hour-value 25
python -m experiments.build_tsp_matrices --mode fastest --fuel-scenario low
python -m experiments.build_tsp_matrices --mode fastest --fuel-scenario high
```

Con los datos actuales, estos comandos no generan datos ficticios: informan arcos ausentes y costes no verificables, guardan matrices de componentes con blancos para ausencias y omiten la matriz económica completa. El proceso de optimización no importa cliente de red ni consulta APIs.

## Cuotas y tamaño esperado

La página pública de restricciones de ORS consultada el 2026-10-12 informa hasta 3.500 pares origen-destino por petición Matrix; por ello 47×47 = 2.209 celdas caben en una solicitud de matriz, sujeto a los límites del plan. Los planes publicados consultados indican para Standard 2.000 Directions/día y 40/min, y 500 Matrix/día y 40/min; el plan colaborativo lista cuotas superiores, pero excluye uso comercial. Esos topes son cuotas del servicio, no autorización para una descarga masiva.

Para la cobertura de rutas rápidas, como cota simple se necesitaría una Directions por cada uno de los 2.162 arcos dirigidos para conservar una geometría por conexión; `alternatives` puede producir hasta tres candidatas, pero la respuesta no garantiza que existan o sean exhaustivas. Una segunda petición por arco para evitar peajes elevaría la cuenta hasta 4.324 llamadas. Es posible adquirir por lotes con pausa y reanudación, pero **no se hizo ni se autoriza en esta fase**. La matriz de distancias/tiempos es mucho más barata en número de llamadas, aunque no proporciona geometrías ni alternativas.

El motor ORS acepta indicaciones de evitación para Directions. La disponibilidad de una alternativa, el ajuste a una vía, la cobertura local y la calidad de cada ruta se deben verificar en el piloto antes de fijar motor/configuración. El perfil de automóvil no incorpora configuración exacta del BMW ni tráfico observado; sus duraciones son estimaciones del grafo/perfil.

## Proveedores y licencias (consulta: 2026-10-12)

| Servicio | Capacidades verificadas en documentación | Cuotas / credenciales | Conservación y redistribución |
|---|---|---|---|
| openrouteservice alojado | Directions v2 con geometría e información adicional; Matrix de distancia/tiempo. Directions admite opciones y rutas alternativas; hay un límite publicado de tres candidatas y no se garantiza que se devuelvan. Evitación se aplica a Directions; no se presupone que Matrix acepte las mismas opciones. | Requiere clave. Cuotas dependen del plan; revisar al ejecutar, no codificar como constantes legales. | Términos publicados requieren atribución. Una respuesta pública oficial de HeiGIT fechada 2026-10-12 afirma que resultados de API se licencian CC-BY-SA 4.0. Conservar respuestas localmente con atribución parece viable bajo esa licencia; publicar implica cumplir atribución y compartir bajo términos compatibles. Revisar el texto vigente de términos antes de publicar las respuestas. |
| OSRM demo público | Route devuelve distancias, duraciones y geometría; `alternatives` es no exhaustivo. Table devuelve tiempos/distancias de rutas rápidas, en segundos/metros, y admite matrices dirigidas. No hay tarifas de peaje. | Sin clave en la API documentada; el demo no ofrece cuota/garantía estable. Política: no uso excesivo, atribución OSM/OSRM, identificador de aplicación; servicio puede retirarse. | No usar para procesar las 2.162 conexiones. El demo no garantiza disponibilidad/calidad ni fecha de mapa; adecuado solo para pruebas pequeñas. Datos OSM requieren atribución/licencia ODbL. |
| GraphHopper Directions API alojada | Servicio comercial de rutas; API requiere cuenta e identificador. La página técnica ofrece opciones de routing, pero el alcance de perfiles/alternativas debe probarse antes de seleccionarlo. | Requiere clave; paquetes de pago por contrato y límites documentales/paquete. | Términos leídos el 2026-10-12 dicen que resultados solo se cachean temporalmente en cliente y que redistribución requiere paquete/contrato personalizado; no es opción compatible por defecto con el snapshot público y offline previsto. |

La opción inicial para un piloto controlado es ORS, condicionada a revisar y archivar los términos exactos del plan de la cuenta, cuotas reales y obligaciones CC-BY-SA/ODbL antes de publicar resultados. Hay una discrepancia de versiones: un resultado de términos ORS consultado muestra CC-BY 4.0, mientras que la respuesta directa de HeiGIT del 2026-10-12 indica CC-BY-SA 4.0; la página actual de cuenta redirige a acceso autenticado. Por prudencia este ETL documenta la licencia más reciente comunicada por HeiGIT, pero la distribución pública de respuestas crudas queda pendiente de guardar/revisar el texto vigente de términos de la cuenta. Si el equipo no puede cumplir esas condiciones, alternativa: autoalojar un motor libre con un extracto/versionado OSM autorizado, a costa de infraestructura y procesamiento que esta arquitectura intenta evitar.

## Peajes, combustible y límites científicos

El API entrega una geometría, no el importe de una concesión. La detección cartográfica puede señalar carreteras etiquetadas `toll`; la tarifa monetaria requiere identificar concesión, categoría ligera, accesos/salidas y tarifa vigente de la fuente oficial. Si esa correspondencia no se verifica, el estado queda `desconocido`; nunca se transforma en cero. La alternativa “avoid tollways” también se considera solamente candidata hasta inspeccionar toda la geometría.

El combustible se calcula como `distancia_km / 100 × consumo_l_100km × precio_EUR_l`. La configuración versionada está en `configs/tsp_economics.yaml`: BMW 120 Serie 1 F70 gasolina mild hybrid 48 V, 170 CV; 5,4 L/100 km como supuesto representativo (punto medio del rango BMW 5,3–5,5), con escenarios low/high 5,3/5,5. No se afirma que 5,4 sea la homologación de una variante concreta. El precio configurado es 1.8490983979999999 €/L, leído del XLSX oficial con impuestos del 2026-10-08: celda `Sheet1!B28`, España, unidad original EUR/1000 L, dividida por 1000. Archivo, hash, fecha consultada, fuente, celda y unidad quedan en YAML y `data/fuentes.md`. El costo económico sigue incompleto hasta verificar peajes; el precio conocido no convierte un peaje desconocido en cero. No se incluyen mantenimiento, seguro ni depreciación.

El comando de reconstrucción aplica el escenario seleccionado sin modificar el catálogo persistido:

```powershell
python -m experiments.build_tsp_matrices --mode fastest --fuel-scenario reference
python -m experiments.build_tsp_matrices --mode economic --hour-value 25 --fuel-scenario reference
```

`--fuel-scenario` acepta `low`, `reference` o `high`. Cambiar precio/consumo requiere editar el YAML con procedencia y fechas, no el código. Cada ejecución es local y offline.

## Restricciones y piloto ORS revisados el 2026-10-12

La documentación pública de ORS confirma:

- Matrix admite 3.500 pares origen×destino por solicitud; una matriz 47×47 son 2.209 celdas incluyendo la diagonal y queda bajo ese límite público. El plan Standard publicado indica 500 llamadas Matrix/día y 40/minuto. La cuota restante de la cuenta concreta no se comprobó; el entorno de proceso de Codex aún no tiene `ORS_API_KEY` aunque la variable persistente de usuario sí aparece definida.
- Directions admite hasta 6.000 km para conducción, geometría GeoJSON en `/v2/directions/{profile}/geojson`, y `options.avoid_features=["tollways"]` para perfiles `driving-*`.
- Las rutas con `alternatives` están limitadas a 100 km y hasta tres alternativas solicitadas. Por las distancias del piloto previo, este mecanismo no aplica a Bilbao–Zaragoza, Madrid–A Coruña ni Barcelona–Girona, y no promete enumeración exhaustiva. Para esos pares solo podría pedirse una Directions separada con `avoid_features` si no excede los límites generales; la salida debe verificarse en geometría y tarifa.

La página de planes lista para Standard 2.000 Directions/día y 40/minuto; no equivale a cuota disponible hoy en una clave. Sin clave el presupuesto efectivo ejecutable es cero. Revisar el tablero de la cuenta justo antes del piloto; el tamaño de cuota listado no es un permiso para reproducir llamadas ya almacenadas.

### Piloto de seis arcos, todavía no ejecutado en ORS

Arcos canónicos: `madrid:toledo`, `toledo:madrid`, `bizkaia:zaragoza`, `zaragoza:bizkaia`, `madrid:a_coruna`, `barcelona:girona`.

Plan de solicitud:

1. Seis llamadas `POST https://api.openrouteservice.org/v2/directions/driving-car/geojson`, una por arco, con las coordenadas del catálogo IGN en orden `[lon, lat]`, geometry y preferencia normal/rápida.
2. Opcionalmente, seis llamadas adicionales al mismo endpoint para los mismos arcos con `options: {"avoid_features":["tollways"]}`. Esto solicita una candidata cartográficamente encaminada evitando clases marcadas como toll; no certifica tarifa cero.
3. No se piden `alternative_routes` en este piloto por las limitaciones de 100 km y porque la API no enumera exhaustivamente las rutas.

Máximo presupuestado si se aprueban ambos lotes: **12 llamadas Directions** (6 rápidas + 6 con evitación). No se usa Matrix en este piloto específico. Los comandos de planificación, sin `--execute`, son:

```powershell
python -m experiments.acquire_tsp_routes --pairs madrid:toledo,toledo:madrid,bizkaia:zaragoza,zaragoza:bizkaia,madrid:a_coruna,barcelona:girona --strategy fastest --max-requests 6
python -m experiments.acquire_tsp_routes --pairs madrid:toledo,toledo:madrid,bizkaia:zaragoza,zaragoza:bizkaia,madrid:a_coruna,barcelona:girona --strategy avoid_tolls --max-requests 6
```

Al planificar sin ejecución el cliente no necesita clave ni abre conexión. Se recomienda ejecutar en dos lotes para que el equipo pueda aprobar uno o ambos presupuestos por separado. Por cada ejecución, el almacenamiento actual escribe el catálogo incremental `data/processed/routes/route_alternatives.csv`, estado `data/processed/routes/acquisition_state.json` y una respuesta cruda JSON por solicitud bajo `data/raw/routes/`. Las matrices se regeneran después con el constructor offline.

El archivo local examinado se preserva como `data/raw/weekly_oil_bulletin_2026-10-08_prices_with_taxes.xlsx`. El nombre que traía el archivo decía `2026-09-21`, pero su hoja sitúa la fecha de referencia en 2026-10-05 y sus metadatos fueron modificados el 2026-10-08; el boletín publicado con esa fecha aparece en el índice oficial de la Comisión. Se registraron la celda `Sheet1!B28`, el valor, la unidad y el SHA-256 en `configs/tsp_economics.yaml` y `data/fuentes.md`. La política general de la Comisión permite reutilizar contenido propio bajo CC BY 4.0 salvo aviso distinto; se versiona el XLSX con atribución y registro de que se extrajo y convirtió un valor. La fecha real de descarga del usuario no viene embebida; la consulta/inspección local fue el 2026-10-12.

El API reporta tiempos de perfil, no mediciones futuras ni tiempos de tráfico para una hora de salida. Puede cambiar el resultado con actualización del proveedor o de OSM. Se registra adquisición y perfil; cuando la API no exponga versión de grafo, se conserva expresamente como no informada y se guardan respuesta y petición bajo la licencia aplicable.

## Fuentes consultadas

- ORS API Reference: [Directions](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/), [Matrix](https://giscience.github.io/openrouteservice/api-reference/endpoints/matrix/) y [restricciones de API](https://openrouteservice.org/restrictions/).
- ORS [planes y cuotas](https://openrouteservice.org/plans/) y [términos de servicio](https://openrouteservice.org/terms-of-service/); la página de cuenta requiere autenticación. La respuesta de HeiGIT en [consulta de licencia de resultados](https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079) fechada 2026-10-12 declara CC-BY-SA 4.0.
- OSRM [API](https://project-osrm.org/docs/v5.24.0/api/) y [política de uso del servidor demo](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy).
- GraphHopper [Directions API](https://docs.graphhopper.com/openapi) y [términos del servicio](https://www.graphhopper.com/terms/), que especifican cacheado temporal y acuerdo para redistribución.
- Para capitales, vehículo, peajes y combustible siguen aplicando los registros de [data/fuentes.md](../data/fuentes.md); la tarifa monetaria de peajes continúa pendiente de verificación para muchos arcos.
