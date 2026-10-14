# Licencias y atribución de los datos

## Resultados de openrouteservice

Los resultados Matrix y las matrices de combustible derivadas se ofrecen bajo [Creative Commons Atribución-CompartirIgual 4.0 Internacional (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/), conforme a la sección **Attribution and License — openrouteservice** de los términos de HeiGIT aplicables a la cuenta, consultados el 2026-10-12. El documento no muestra versión ni fecha de vigencia; se registra la fecha de consulta.

Conserva la atribución **© openrouteservice by HeiGIT | Data from OpenStreetMap**, indica que los valores fueron transformados y cita esta licencia. Las distancias se normalizaron de m a km (÷1000), las duraciones de s a h (÷3600), y el combustible se derivó con `km / 100 × consumo (L/100 km) × precio (EUR/L)`. Las modificaciones y fuentes se registran en `metadata.json`.

## OpenStreetMap

La atribución a OpenStreetMap se mantiene separada de la licencia ORS. Fuente: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), datos bajo [Open Database License 1.0 (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/). Este paquete incluye métricas de ruta producidas por el motor; no incluye el extracto de carreteras, geometrías ni atributos viales de la base OSM. Se proporciona atribución y enlace ODbL. No se declara que ODbL y CC BY-SA sean equivalentes ni que una licencia anule la otra.

La guía OSMF de [atribución para bases de datos y motores de rutas](https://osmfoundation.org/wiki/Attribution_Guidelines) exige identificar OpenStreetMap y enlazar la licencia; indica también que el share-alike ODbL es pertinente si la obra constituye una base derivada. Si el paquete se amplía con geometrías/atributos de OSM o una revisión determina que es una base derivada, habrá que revisar y cumplir por separado ODbL 4.4/4.6 (licencia compatible y acceso a la base derivada o alteraciones) antes de distribuir esa versión.

## Catálogo geográfico

`cities.csv` reproduce las coordenadas IGN con procedencia por ciudad, bajo [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) según los avisos de reutilización del IGN recogidos en el catálogo. Esta licencia del catálogo no sustituye CC BY-SA de las matrices ORS.

## Código, combustible y alcance

El código del repositorio y los datos tienen avisos separados; este documento no concede licencia al código. El precio de combustible procede del Weekly Oil Bulletin de la Comisión Europea, publicado el 2026-10-08 y consultado el 2026-10-12; la unidad original EUR/1000 L se normaliza a EUR/L. `metadata.json` conserva fuente, fechas y hash del archivo fuente. La fecha efectiva de descarga no quedó registrada.

No se incluyen tarifas de peaje. Un peaje desconocido no equivale a cero y este conjunto **no constituye una matriz de costo económico total**.


## Geometrías y resultados Directions publicados

Los shards de rutas y sus atributos `tollways`/`waycategory` son resultados de openrouteservice y se ofrecen conforme a la licencia de resultados CC BY-SA 4.0 indicada en los términos de HeiGIT consultados el 2026-10-12; atribución: **© openrouteservice by HeiGIT | Data from OpenStreetMap**. Los atributos de ruta pueden derivar de la base cartográfica de OpenStreetMap. Se mantiene por separado la atribución y el aviso ODbL de [OpenStreetMap](https://www.openstreetmap.org/copyright); CC BY-SA y ODbL son licencias distintas. El conjunto no contiene el extracto vial original de OSM. Si la clasificación de una distribución como base derivada de OSM activara obligaciones adicionales, estas se rigen por ODbL y deben cumplirse independientemente; no se afirma que la licencia ORS las sustituya.

El empaquetado excluye instrucciones textuales innecesarias, encabezados de cuota, credenciales y los contenedores crudos. Mantiene geometría WGS84, segmentos extras, IDs y hashes necesarios para reproducir el análisis.
