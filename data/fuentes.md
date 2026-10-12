# Fuentes de datos del TSP

Cada dato real lleva fuente primaria y fecha de consulta. Los archivos crudos van en `data/raw/`.

| Dato | Fuente (URL o documento) | Fecha de consulta | Archivo crudo | Verificado por | Notas / limitaciones |
|---|---|---|---|---|---|
| Nombres de capitales y provincias | [Mapa político oficial IGN](https://www.ign.es/web/resources/docs/IGNCnig/RE-Mapa-Espana-Politico.pdf); [entidades administrativas IGN](https://www.ign.es/resources/ane/Informacion_Geografica_Destacada/IGN_INFOGEO_ENTIDADESADMIN.html) | 2026-10-12 | `data/processed/capitales_peninsulares.csv` | integrante 3 | El mapa enumera provincia y capital. No se descargó la tabla XLSX de entidades en este entorno. |
| Coordenadas de las 47 capitales | [Nomenclátor Geográfico Básico de España (IGN)](https://datos.gob.es/es/catalogo/e0dat0002-nomenclator-geografico-basico-de-espana1); [servicio API-Features IGN](https://api-features.ign.es/collections/namedplace) | 2026-10-12 | Pendiente | integrante 3 | Fuente oficial identificada; no se obtuvo/consultó el registro de cada capital. Las 47 coordenadas siguen vacías en el catálogo y no se usan como coordenadas verificadas. Definir el punto representativo antes de rellenarlas. |
| Distancias por carretera | | | | | |
| Tiempos de viaje | | | | | |
| Peajes | | | | | |
| Precio del combustible | | | | | |
| Consumo del vehículo | | | | | |
