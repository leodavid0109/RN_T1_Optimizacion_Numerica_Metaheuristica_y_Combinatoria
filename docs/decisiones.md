# Decisiones del equipo (Fase 0)

Completar y fechar cada decisión. Lo que está como «propuesta» no está decidido hasta que el equipo lo confirme.

| Decisión | Estado | Valor | Justificación breve |
|---|---|---|---|
| Función de prueba 1 (2D y 3D) | Propuesta | Rosenbrock | Valle curvo, mal condicionada, un solo mínimo global: pone a prueba al gradiente |
| Función de prueba 2 (2D y 3D) | Propuesta | Rastrigin | Muchos mínimos locales: pone a prueba a los métodos poblacionales |
| Vehículo para combustible | Pendiente | — | Necesita consumo homologado de una fuente verificable |
| Roles e integrantes | Pendiente | — | Ver tabla de roles abajo |
| Fecha de entrega | Pendiente | — | |
| Fecha de sustentación | Pendiente | — | |

## Roles

| Integrante | Responsable de | Revisa |
|---|---|---|
| | | |
| | | |
| | | |

Todos deben poder explicar todo el trabajo en la sustentación, no solo su parte.

## Reglas de equipo

- Commits pequeños y frecuentes, de distintos autores.
- Cada resultado se genera con un comando desde el repositorio.
- Ningún dato del TSP entra sin fuente y fecha de consulta en `data/fuentes.md`.
- Todo uso de IA para algo verificable se registra en `docs/alucinaciones.md` antes de verificarlo.

## Decisiones comunes de la Parte 1 (2026-10-12)

- Presupuesto: 20 000 evaluaciones equivalentes de f en 2D y 40 000 en 3D, igual para todos los métodos. Provisional hasta tener los resultados de los métodos poblacionales.
- Éxito: f − f* ≤ 1e-4 (principal) y ≤ 1e-2 (secundario).
- Costo de un gradiente analítico: 1 evaluación equivalente. Gradiente numérico por diferencias centrales: 2n.
- Reporte del descenso por gradiente: contador de f y de ∇f por separado, más dos totales (costo del gradiente 1 y 2n).
