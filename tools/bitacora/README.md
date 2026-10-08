# Bitácora de alucinaciones

Formulario local para registrar los hallazgos de la «Cacería de la alucinación».
Solo usa la biblioteca estándar de Python (3.9 o superior): no agrega nada a `requirements.txt`.

## Uso

Desde la raíz del repositorio:

    python tools/bitacora/server.py

Se abre `http://127.0.0.1:8765`. Opciones: `--port 9000`, `--dir docs/alucinaciones`,
`--autor "Nombre"` (por defecto, `git config user.name`), `--no-browser`.

## Qué guarda y cómo se comparte

- Cada hallazgo es un archivo propio: `docs/alucinaciones/data/<id>.json`.
- El reporte `docs/alucinaciones/alucinaciones.md` se regenera solo con cada cambio.
  No se edita a mano; sale de los JSON.
- Para compartir con el equipo: `git add docs/alucinaciones && git commit && git push`.
  Como cada hallazgo es un archivo distinto, registrar en paralelo no genera conflictos.
  Después de un `git pull`, vuelve a la pestaña del navegador para refrescar la lista.
- Los códigos `H-01`, `H-02`… se numeran por fecha de creación y pueden moverse si alguien
  fusiona un hallazgo más antiguo. Para citar un hallazgo en un commit usa su
  **referencia estable** (6 caracteres, visible al expandirlo):
  `fix: Rastrigin sin A (hallazgo 1a60e2)`.

## Reglas que aplica

- «Por verificar»: basta con título, prompt y respuesta (se registra antes de verificar).
- «Confirmado»: exige sospecha, evidencia, corrección y lección.
- «Descartado»: la IA acertó; exige describir qué se verificó. Sirve si faltan hallazgos.

## Seguridad

Escucha solo en `127.0.0.1`, rechaza cabeceras `Host` ajenas y exige una cabecera propia en
las escrituras, para que una página web externa no pueda escribir en tu bitácora.
