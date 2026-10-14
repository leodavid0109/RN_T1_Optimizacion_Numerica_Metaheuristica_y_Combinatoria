# Regeneración del informe

`build_informe_trabajo1.py` utiliza `Informe_Trabajo1_base.docx` como plantilla preservada, el catálogo y las geometrías del dataset vial versionado, los resultados ACO versionados y los metadatos del paquete económico. No consulta servicios externos.

Desde la raíz del repositorio, después de instalar `requirements.txt`:

```bash
python -m informe.build_informe_trabajo1
```

El comando genera `docs/Informe_Trabajo1.docx` y sus figuras de apoyo en `informe/figures/`. Para guardar una edición regenerada sin reemplazar el informe publicado, indique otro destino:

```bash
python -m informe.build_informe_trabajo1 --output results/reproducible/report/Informe_Trabajo1.docx --figure-dir figures/reproducible/report
```

La fuente histórica `build_parte1.js` genera un borrador de Parte 1 y no es la fuente del informe integrado. El script Python es el generador de esta versión completa.
