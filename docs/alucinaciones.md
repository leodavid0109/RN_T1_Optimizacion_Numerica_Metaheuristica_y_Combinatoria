# Cacería de la alucinación

Registro continuo. Se anota el prompt y la respuesta literales **antes** de verificar.
Meta: al menos 5 hallazgos genuinos en al menos 3 categorías. Un hallazgo sin evidencia se penaliza más que uno faltante.

Categorías: `matemáticas` · `código` · `datos del mundo real` · `bibliografía` · `conceptos`
Estados: `por verificar` · `confirmado` · `descartado` (la IA acertó; se documenta qué se verificó)

## Resumen

| Código | Título | Categoría | Estado | Responsable |
|---|---|---|---|---|
| H-04 | Gradiente analítico de Rosenbrock (2D) | matemáticas | por verificar | seestradav |

## Plantilla

Copiar este bloque por cada hallazgo.

### H-00 · Título corto

- **Fecha / responsable:**
- **Categoría:**
- **Estado:**
- **Prompt (literal):**
- **Respuesta de la IA (literal):**
- **Sospecha** (qué parecía incorrecto):
- **Evidencia** (fuente no generada por IA, o ejecución de código):
- **Corrección** (y commit que la aplica):
- **Lección aprendida:**

## Hallazgos

### H-04 · Gradiente analítico de Rosenbrock (2D)

- **Fecha / responsable:** 2026-10-12 · seestradav
- **Categoría:** matemáticas
- **Estado:** por verificar
- **Prompt (literal):** _(pegar el prompt enviado a Gemini Pro 3.1)_
- **Respuesta de la IA (literal):** _(pegar la respuesta de Gemini Pro 3.1)_
- **Sospecha** (qué parecía incorrecto): _(completar al comparar con la derivación propia)_
- **Evidencia** (fuente no generada por IA, o ejecución de código): derivación a mano con la regla de la cadena,
  con u = x2 − x1²: ∂f/∂x2 = 200·(x2 − x1²) y ∂f/∂x1 = −400·x1·(x2 − x1²) − 2·(1 − x1).
  Coincide con `Rosenbrock.grad` en `src/functions.py`.
- **Corrección** (y commit que la aplica):
- **Lección aprendida:**
