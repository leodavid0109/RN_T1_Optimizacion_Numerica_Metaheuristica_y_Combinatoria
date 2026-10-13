# Evaluación de TollGuru para el TSP español

**Consulta documental:** 2026-10-13. No se hicieron llamadas a TollGuru, ORS ni Overpass durante esta evaluación.

## Conclusión ejecutiva

TollGuru es un candidato razonable para una prueba de contraste, especialmente con **TollTally Complete Route Polyline**, porque acepta la geometría completa de otro motor y devuelve información de peajes para esa ruta concreta. **No está aprobado como fuente de tarifas oficiales ni como sustituto de los tarifarios de operadores.** La página de TollGuru para España advierte que las tarifas están temporalmente no disponibles y que los importes mostrados podrían ser inexactos. La documentación de entrada Polyline tampoco establece una clase de vehículo español que podamos mapear inequívocamente al BMW 120. Por ello, esta fase implementa transporte y planificación protegidos, pero no interpreta automáticamente ningún resultado como peaje verificable.

## Qué hacen las dos APIs

| Servicio | Endpoint documentado | Uso | Geometría | Limitación relevante |
|---|---|---|---|---|
| TollTally, ruta completa | `POST https://apis.tollguru.com/toll/v2/complete-polyline-from-mapping-service` | Valorar una ruta exacta proporcionada por ORS | La documentación acepta polyline codificada o `path` de coordenadas latitud/longitud y permite indicar la fuente `custom` | Devuelve información para una ruta, no rutas alternativas. El proveedor advierte que se envíe la geometría completa. Los tipos enumerados en el esquema Polyline se describen expresamente como específicos de EE. UU. |
| Origin–Destination–Waypoints | `POST https://apis.tollguru.com/toll/v2/origin-destination-waypoints` | Calcular rutas propias y mostrar peajes/costos para las opciones devueltas | La respuesta puede incluir rutas y geometrías cuando la opción de respuesta correspondiente se habilita | No conserva necesariamente la ruta ORS. La documentación anuncia opciones rápidas, baratas y otras rutas óptimas, pero no promete enumerar todas las rutas posibles. El conteo de transacciones es mayor que una solicitud HTTP. |

La documentación actual de TollGuru describe el endpoint de ruta completa como TollTally Polyline y lo recomienda si ya se dispone de un motor de mapas. Para el TSP, este es el flujo preferido para **contrastar** ORS sin cambiar la geometría que define el arco. El modo OD sirve para estudiar alternativas independientes, etiquetadas con su motor y su propia procedencia; no se deben reemplazar con ellas los valores ORS.

## Esquema de solicitud y cliente local

El cliente en `src/tsp/etl/tollguru.py`:

- Solo prepara solicitudes al importarse o al construir el objeto; no hay tráfico implícito.
- Requiere `execute=True` para cualquier HTTP. La ejecución de esta fase nunca lo utilizó.
- Lee `TOLLGURU_API_KEY` del entorno. La clave no va en planes, excepciones ni persistencia.
- Usa HTTPS, timeout explícito, contador estricto de solicitudes y cero reintentos.
- Convierte las coordenadas ORS `[longitud, latitud]` al orden `latitud,longitud` que ejemplifica el campo `path` de TollGuru.
- Guarda una respuesta real solo en `data/raw/tollguru/`, excluida de Git. La carpeta `data/processed/tolls/` existente también está excluida.
- No convierte peajes del proveedor en `RouteAlternative`, no inventa moneda ni modalidad y marca la copia local como estimación aún no verificada.

Los ejemplos específicos de POST de la documentación usan `x-api-key`, mientras que su apartado narrativo de autenticación dice HTTP Basic Auth y que la clave es el usuario. El cliente sigue el encabezado explícito `x-api-key` de los ejemplos/endpoints actuales; antes de un piloto se debe confirmar con el portal o soporte cuál esquema se aplica a la suscripción concreta. Las pruebas solo inspeccionan peticiones simuladas.

Ejemplo de planificación offline (no hace red):

```python
from src.tsp.etl.tollguru import TollGuruClient

client = TollGuruClient(max_http_requests=1)
plan = client.plan_polyline(
    "bizkaia-zaragoza-fast",
    ((-2.916682, 43.250131), (-0.878662, 41.657313)),
    vehicle={"type": "POR_CONFIRMAR_CON_TOLLGURU"},
)
print(plan.endpoint, plan.request_sha256)
print(client.execute(plan))  # Sin execute=True, no hace HTTP.
```

Ese fragmento ilustra el contrato del planificador; **el perfil del vehículo es un marcador y no un valor válido para una consulta**. No ejecutar hasta recibir de TollGuru el identificador admitido para un turismo español ligero y confirmar el método de autenticación. El cliente acepta payload de OD documentado, pero no fija un enum de vehículo que no hemos podido verificar.

## Rutas disponibles para un piloto

El catálogo local contiene geometrías ORS rápidas para:

- Bizkaia → Zaragoza.
- Zaragoza → Bizkaia.
- Madrid → Toledo.

No hay geometría Bilbao → Madrid. Este sentido no se puede valorar con TollTally sin adquirir primero una ruta mediante el proceso autorizado de ORS. Las geometrías de Madrid → A Coruña y Barcelona → Girona existen, pero no hacen parte de los cuatro corredores escogidos para esta prueba.

Un piloto Polyline limitado a los tres arcos disponibles requeriría **3 solicitudes HTTP** si se envía una por geometría completa. La documentación de facturación indica una transacción por polyline de hasta 300 millas, con segmentación y cargos adicionales por encima; una petición con error de entrada también cuenta una transacción. La longitud debe comprobarse con la geometría concreta y la facturación de la cuenta.

Una prueba OD de cuatro corredores sería hasta **4 solicitudes HTTP**, pero no se debe presupuestar como cuatro unidades: TollGuru publica una base de 5 transacciones por ruta OD con proveedor TollGuru/HERE y 7 con Google, según el desglose de sus FAQ. No hemos confirmado cómo facturan coordenadas directas o fuente `custom`, ni el cupo vigente de esta cuenta. Por eso el OD no se debe ejecutar hasta revisar la pantalla de Usage/Subscription y recibir el presupuesto efectivo.

## Vehículo, fecha y vigencia

El proyecto tiene como vehículo experimental el BMW 120 F70, gasolina mild hybrid, 170 CV, categoría académica de turismo ligero. Esto no determina por sí solo la categoría tarifaria interna de TollGuru. El esquema de TollTally Polyline enumera opciones de vehículo norteamericanas; debemos pedir el campo/categoría válido en España y confirmar qué atributos del coche se consideran (ejes, altura, clase de vehículo y remolque). No enviar `2AxlesAuto` como equivalencia sin confirmación.

La API permite enviar un `departureTime` o `locTimes`, que TollGuru utiliza como timestamp para calcular cargos sensibles a hora. Si no se especifican, usa la hora actual. **Eso no demuestra que su base consulte una tarifa histórica ni que conserve la tarifa legal vigente para ese día.** El estudio usa fecha de referencia 2026-10-12; una consulta realizada después debe registrar por separado:

1. Fecha/hora de viaje solicitada.
2. Fecha/hora real de consulta.
3. Timestamp retornado por el proveedor.
4. Fecha efectiva de la tarifa, si aparece.
5. Fecha de actualización y fuente tarifaria, si se documentan.
6. Vigencia confirmada aparte mediante la tarifa oficial del operador.

No encontramos documentación pública que garantice una consulta “as-of” histórica, ni un campo general que proporcione la fuente primaria/fecha de vigencia de cada tarifa. El lenguaje comercial de costos “historical” no basta para demostrar disponibilidad de una tabla tarifaria histórica para España.

## Costos, límites y cobertura

La documentación pública consultada el 2026-10-13 anunciaba prueba de 14 días; cuentas individuales reciben 15 transacciones diarias de prueba y cuentas con correo empresarial 150 por día. Para TollGuru Toll API se publicaban planes de pago desde USD 80/mes por 5.000 transacciones; esto no se debe extrapolar a TollTally: su página remite a una conversación comercial y no publica tarifa. Precios y trial son temporales y hay que confirmarlos en el dashboard antes de usar la cuenta.

La facturación se cuenta por **transacciones del proveedor**, no por llamadas HTTP. TollTally Complete Polyline: una transacción por ruta hasta 300 millas; rutas de 301–1000 millas se cuentan como dos, más de 1000 como tres; errores de entrada cuentan una. GPS Track y Polyline map matching usan una cuenta distinta. OD: el conteo publicado suma geocodificación, enrutamiento y peaje y varía según el proveedor de mapas.

La web de TollGuru para España muestra actualmente el aviso “Toll rates for Spain are temporarily unavailable” y advierte que los importes que pudieran aparecer pueden ser inexactos. La página publicita cobertura y métodos de pago, pero el propio aviso impide tratarla como prueba de cobertura tarifaria actual. Hacer una solicitud tampoco garantiza que el recorrido AP-68 tenga precio disponible.

## Conservación, licencias y redistribución

Las páginas públicas consultadas no conceden de forma clara una licencia abierta de redistribución para resultados TollGuru ni establecen cuánto tiempo se pueden almacenar o publicar. Los términos generales del sitio permiten a MapUp tratar el contenido que el usuario envía para operar el servicio, pero no resuelven los derechos sobre los resultados tarifarios de la API. Mantener localmente una respuesta no equivale a permiso para publicarla en GitHub bajo CC BY-SA, ODbL u otra licencia.

Hasta recibir confirmación escrita de MapUp/TollGuru:

- Las respuestas crudas permanecen en `data/raw/tollguru/`, excluidas de Git.
- No se publica ningún valor derivado de TollGuru.
- Sí se puede publicar el cliente, las pruebas simuladas, los identificadores de petición sin secreto y documentación propia.
- ORS/OSM conserva su atribución y licencia independiente; TollGuru no reemplaza ni licencia esos datos.

## Comparación con el tarifario AP-68

El documento oficial de Autopistas/AVASA para AP-68 2026 publicado en `docs/tsp_peajes.md` sirve para comprobar un par de estaciones, clase de ligeros y condiciones del periodo indicado. Su valor nominal Bilbao–Zaragoza de 39,90 EUR no se asigna a las geometrías ORS por el solo hecho de tener coincidencia cartográfica extensa con AP-68.

Para cada sentido se debe verificar: acceso exacto, salida exacta, continuidad recorrida, sentido y calzada, categoría aplicable al BMW, fecha de validez, horario, pago ordinario o Via-T/descuento, y cobertura de todo el recorrido. Comparar TollGuru requiere además escoger la misma modalidad de pago y fecha. Se registra la diferencia como `TollGuru - tarifa oficial`, junto con moneda, clase, par tarifario, fuente y fecha de consulta. Una discrepancia no se promedia: queda abierta hasta explicar su causa. Si TollGuru no aporta estación/par y vigencia, su total queda como estimación del proveedor.

## Uso posterior en los modelos

- **Modelo A:** conserva distancia/duración y geometría rápida ORS. Solo se completa `P_fast` después de asociar el recorrido con el tarifario oficial y cerrar la cobertura de cobros.
- **Modelo B:** cada ruta ORS alternativa o ruta TollGuru distinta es una alternativa separada, con motor, fecha, geometría, distancia y tiempo propios. No se reemplazan rutas ORS.
- El combustible lo calcula el proyecto con BMW 5,4 L/100 km y el precio oficial local de gasolina; se ignora el costo de combustible predeterminado de TollGuru.
- Un `hasTolls=false`, un arreglo vacío o un costo nulo/no retornado no autoriza el importe cero. Cero exige fuente y cobertura completa.
- Una salida TollGuru desconocida no se integra en la matriz económica ni desplaza una alternativa conocida.

## Decisión sobre adoptar el servicio

**Recomendación actual: TollTally solo como verificador experimental, no como fuente final de verdad.** La prueba se justifica si TollGuru confirma por escrito (1) disponibilidad de tasas españolas y AP-68 para la fecha requerida, (2) clase de vehículo de turismo en España, (3) método de autenticación correcto, (4) número de transacciones/precio exacto, (5) fecha/fuente/condiciones de la tarifa en respuesta y (6) derecho de almacenamiento local y redistribución académica. OD debe quedar como comparación de rutas alternativas y requiere un presupuesto independiente.

Descartar TollGuru como componente de costos finales si España sigue temporalmente sin tarifas, no se puede identificar la categoría de ligero o no se autoriza el almacenamiento que necesita el experimento offline.

## Fuentes consultadas

Todas se consultaron el **2026-10-13**; las páginas son dinámicas y conviene guardar una copia de términos o respuesta oficial de soporte antes del piloto.

- [TollGuru Toll API Docs](https://beta.tollguru.com/toll-api-docs) — endpoints, autenticación, esquema Polyline/OD, costes y respuesta.
- [TollGuru Toll API Pricing Plans](https://beta.tollguru.com/toll-api-pricing-plans) — trial, planes del API OD y aviso de precio de TollTally bajo contacto comercial.
- [TollTally API transaction count](https://beta.tollguru.com/faq/tolltally-api-transaction-count) — unidades facturables por longitud/endpoint.
- [Toll API transaction count](https://beta.tollguru.com/faq/toll-api-transaction-count) — transacciones OD según proveedor y componentes.
- [How to choose the right API](https://beta.tollguru.com/faq/how-do-i-choose-the-right-api) — distinción OD, ruta completa y GPS tracks.
- [TollGuru Spain toll calculator](https://tollguru.com/toll-calculator-spain) — cobertura publicitada y aviso actual de tarifas no disponibles/inexactas.
- [TollGuru terms and conditions](https://tollguru.com/terms-and-conditions) — términos generales; no encontrados términos específicos públicos de redistribución de resultados de API.
- [TollGuru API regional parameters FAQ](https://beta.tollguru.com/faq/what-toll-parameters-does-the-tollguru-api-cover-for-each-region) — presenta parámetros regionales, sin una tabla textual descargable que permita validar aquí el detalle español.
- [TollGuru FAQ sobre IVA europeo](https://beta.tollguru.com/faq/does-api-return-europe-toll-with-or-without-vat) — declara campos de IVA para Europa; no certifica por sí solo el origen o vigencia de cada tarifa española.
- [Tarifario oficial AP-68 2026 de Autopistas/AVASA](https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf) — referencia primaria de contraste por estaciones y clase.

## Información que debe confirmar la cuenta

1. ¿La suscripción habilita `complete-polyline-from-mapping-service` y cuál es su presupuesto/importe por transacción?
2. ¿`x-api-key` o Basic Auth es el esquema aceptado para ese producto y cuenta?
3. ¿Qué `vehicle` exacto representa turismo ligero español/clase 1 o 2 de AP-68?
4. ¿La fecha de viaje se usa solo para reglas horarias o hay tarifas históricas y cómo se identifica su fecha efectiva?
5. ¿Qué modalidad de pago devuelve la respuesta para España y cuál se consideraría ordinaria sin descuento?
6. ¿Qué campos contienen desglose por concesionaria/estación/entrada/salida y fuente/fecha de tarifa?
7. ¿Se permite almacenar resultados de forma indefinida, incluirlos en dataset offline del curso y redistribuirlos en repositorio público? Solicitar cláusula/licencia explícita.
8. ¿Hay cobertura activa de AP-68 en España hoy, pese al aviso temporal del calculador?
