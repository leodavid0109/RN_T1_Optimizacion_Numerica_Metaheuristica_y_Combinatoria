# Evidencia vial ORS para tres rutas piloto

El cliente Directions existente admite `--extra-info tollways,osmid,waycategory`
con el perfil `driving-car`. La petición sigue usando `preference=fastest`,
geometría e instrucciones. Según la [referencia oficial de ORS](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/),
las secciones de `extras.*.values` contienen índices inicial y final **de
vértices** de la geometría. Dos secciones pueden compartir un vértice, sin
compartir una arista. `osmid` puede venir como `osmId` en la respuesta. La
distancia de `tollways.summary` está en metros y se normaliza a km; si el
resumen falta, la distancia marcada como peaje queda desconocida.

## Adquisición controlada desde PowerShell

Desde la raíz del repositorio, primero ejecutar cada línea **sin** `--execute`
para revisar el plan. Las siguientes líneas sí harían las peticiones cuando
el usuario decida ejecutarlas; Codex no las ejecutó:

```powershell
.\.venv\Scripts\python.exe -m experiments.acquire_tsp_routes --pairs madrid:toledo --strategy fastest --extra-info tollways,osmid,waycategory --max-requests 1 --max-http-requests 1 --max-retries 0 --execute
.\.venv\Scripts\python.exe -m experiments.acquire_tsp_routes --pairs bizkaia:zaragoza,zaragoza:bizkaia --strategy fastest --extra-info tollways,osmid,waycategory --max-requests 2 --max-http-requests 2 --max-retries 0 --execute
```

El presupuesto conjunto es de **tres intentos HTTP**, sin reintentos. Antes
de ejecutar se requiere `ORS_API_KEY` en el entorno local; nunca se registra.
Se conserva el límite diario ya configurado en `configs/tsp_etl.yaml`. Las
respuestas nuevas se guardan en `data/raw/routes/enriched/` y el catálogo y
estado en `data/processed/routes/enriched/`, ambos excluidos de Git. La
identidad de petición incluye el conjunto ordenado de atributos solicitados;
sin ellos se conserva la identidad anterior. El catálogo de rutas previo no
se sobrescribe. Una ejecución repetida omite las solicitudes completadas.

Después de obtener las respuestas, reconstruir el análisis sin conexión:

```powershell
.\.venv\Scripts\python.exe -m experiments.analyze_tsp_ors_extras
```

El análisis escribe `enriched_routes.json`, `enriched_routes.csv` y
`overpass_way_plan.json` bajo `data/processed/tolls/ors_extra_info/`. Los
archivos incluyen índices, IDs OSM asociados a tramos marcados, categorías,
longitud tarifada informada por ORS, fecha de adquisición, hash de la geometría
y comparación con la geometría original. Si difiere el hash, **no** se
trasladan peajes ni evidencia de una geometría a la otra. La planificación de
Overpass deduplica IDs de vías y forma lotes de hasta 20; no realiza llamadas.
Cuando se autorice una consulta puntual, `OverpassCatalogStore.get_or_fetch_way_ids`
reutiliza el JSON crudo de un lote ya completado y registra el HTTP 504 como
error reanudable. Cada invocación pendiente emplea una sola petición y no
reintenta automáticamente; el presupuesto global y la pausa entre lotes deben
fijarse en la ejecución controlada posterior. Los IDs de vías pueden orientar
una consulta puntual, pero no identifican por sí solos una estación o un cobro.

## Interpretación y trabajo pendiente

Una sección `tollways=1` es evidencia cartográfica según el grafo de ORS; no
es tarifa. `tollways=0` tampoco certifica peaje cero. `waycategory` es una
clasificación vial, no una regla de cobro. El informe deja siempre
`toll_verification=UNKNOWN` y `toll_cost_eur=null`.

Para Madrid → Toledo se deben contrastar las vías OSM y las referencias de la
ruta con A-42, AP-41 y otras vías usadas realmente. Para ambos sentidos de
Bilbao–Zaragoza se deben localizar entrada, salida y sentido sobre AP-68,
comprobar posibles tramos adicionales y aplicar el tarifario oficial 2026
solo después de verificar categoría, fecha, horario y modalidad de pago.
El inventario Overpass local sigue siendo parcial; el plan por IDs podría
reducir consultas por cajas, pero no demuestra cobertura nacional. Una
respuesta sin algún atributo solicitado se rechaza y queda registrada como
fallida, sin sustituir una adquisición válida anterior. Los HTTP 504 se
registran como fallos reanudables y no se reintentan con los comandos
anteriores.

Fuentes técnicas consultadas el **2026-10-13**:

- [ORS Directions Extra Info](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/).
- [ORS Directions, solicitudes y retornos](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/requests-and-return-types/).
- [Overpass QL, guía de lenguaje](https://wiki.openstreetmap.org/wiki/Overpass_API/Language_Guide).

Las tarifas y fuentes oficiales del corredor AP-68 se documentan en
`data/fuentes.md` y `docs/tsp_peajes.md`.
