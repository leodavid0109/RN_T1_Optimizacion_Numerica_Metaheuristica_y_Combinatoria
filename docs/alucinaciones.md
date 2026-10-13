# Cacería de la alucinación

Registro continuo. Se anota el prompt y la respuesta literales **antes** de verificar.
Meta: al menos 5 hallazgos genuinos en al menos 3 categorías. Un hallazgo sin evidencia se penaliza más que uno faltante.

Categorías: `matemáticas` · `código` · `datos del mundo real` · `bibliografía` · `conceptos`
Estados: `por verificar` · `confirmado` · `descartado` (la IA acertó; se documenta qué se verificó)

Los campos marcados [PENDIENTE] los completa el responsable con un dato que solo él puede dar.

## Resumen

| Código | Título | Categoría | Estado | Responsable |
|---|---|---|---|---|
| H-01 | Gradiente de Rosenbrock en (−1, 1) dado mal «a mano» | matemáticas | confirmado | Sebastian Estrada |
| H-02 | Paso fijo de 0.01 supuesto convergente en Rastrigin | matemáticas / código | confirmado | Sebastian Estrada |
| H-03 | Criterio de selección que desempataba mal en el experimento | código | confirmado (leve) | Sebastian Estrada |
| H-04 | Dos imprecisiones de Gemini sobre la geometría de Rosenbrock | conceptos | confirmado (leve) | Sebastian Estrada |
| V-01 | Fórmulas, dominios y mínimos de Rosenbrock y Rastrigin vs. Surjanovic y Bingham | matemáticas | descartado (la IA acertó) | Sebastian Estrada |
| V-02 | Contador de evaluaciones generado por IA (`src/contador_ia.py`) | código | descartado (la IA acertó) | Sebastian Estrada |

## Plantilla

Copiar este bloque por cada hallazgo.

### H-00 · Título corto

- **Fecha / responsable:**
- **Modelo:**
- **Categoría:**
- **Estado:**
- **Prompt (literal):**
- **Respuesta de la IA (literal):**
- **Sospecha** (qué parecía incorrecto):
- **Evidencia** (fuente no generada por IA, o ejecución de código):
- **Corrección** (y commit que la aplica):
- **Lección aprendida:**

## Hallazgos

### H-01 · Gradiente de Rosenbrock en (−1, 1) dado mal «a mano»

- **Fecha / responsable:** 2026-10-09 · Sebastian Estrada
- **Modelo:** Claude (asistente de la sesión de trabajo)
- **Categoría:** matemáticas
- **Estado:** confirmado
- **Prompt (literal):** «no deberia primero ejectar el mio para tener comparacion»
- **Respuesta de la IA (literal):** «Debería dar, hechos a mano: Rastrigin: f(0,0) = 0, f(1,1) = 2 y grad(1,1) = (2, 2). Rosenbrock: f(1,1) = 0, f(0,0) = 1, grad(0,0) = (−2, 0) y grad(−1,1) = (−400, 200).»
- **Sospecha** (qué parecía incorrecto): al ejecutar `src/functions.py`, el gradiente en (−1, 1) salió (−4, 0) y no (−400, 200).
- **Evidencia** (fuente no generada por IA, o ejecución de código): salida de PowerShell: `Rosenbrock grad(-1,1)= [-4. 0.]`.
  Cuenta a mano: con a = −1 y b = 1, b − a² = 0; la primera componente es −400·a·0 − 2(1 − a) = −4 y la segunda es 200·0 = 0.
  Fuente no generada por IA: Nocedal y Wright (2006), _Numerical Optimization_, Sec. 2.2, p. 19: para
  f(x) = 10(x₂ − x₁²)² + (1 − x₁)² el gradiente en (0, 1) es (−2, 20) y el hessiano es [[−38, 0], [0, 20]]; la misma fórmula
  con coeficiente 100 (Surjanovic y Bingham) da (−4, 0) en (−1, 1), igual que `src/functions.py`.
  Consulta de contraste a Claude Opus 5.5 (2026-10-10, sin código ni búsqueda): respondió ∇f(−1, 1) = (−4, 0); es un indicio,
  no una prueba. Prompt y respuesta literales en `docs/bitacora/H-01.tex`. [PENDIENTE: ese archivo no está en el repositorio;
  subirlo o copiar aquí su contenido] [PENDIENTE: versión exacta del modelo que dio el error y derivación propia a mano]
- **Corrección** (y commit que la aplica): el valor correcto es (−4, 0). El código ya lo calculaba bien; el error estaba en la referencia que dio la IA.
- **Lección aprendida:** un valor «a mano» generado por una IA se comprueba con código antes de usarlo como referencia.

### H-02 · Paso fijo de 0.01 supuesto convergente en Rastrigin

- **Fecha / responsable:** 2026-10-09 · Sebastian Estrada
- **Modelo:** Claude (asistente de la sesión de trabajo)
- **Categoría:** matemáticas (también código)
- **Estado:** confirmado
- **Prompt (literal):** «si yo quiero ser el que haga todo lo 1ro que deberia hacer»
- **Respuesta de la IA (literal):** el test generado decía `r = gradient_descent(p, np.array([0.1, -0.1]), lr=1e-2, max_iters=2000)`
  seguido de `assert r.best_f < 1e-8`. El mensaje que entregó el resultado dijo: «Mi primer test usaba 0.01 y falló.»
- **Sospecha** (qué parecía incorrecto): el test asumía que un paso de 0.01 converge al mínimo de Rastrigin 2D. pytest falló.
- **Evidencia** (fuente no generada por IA, o ejecución de código): salida de pytest: `best_f = 0.000198` frente al `< 1e-8` esperado.
  El hessiano de Rastrigin en el origen es 2 + 4π²A = 396.78, luego el paso estable es menor que 2/396.78 = 0.00504.
  Con lr = 0.001 el mismo punto inicial converge a 0.0.
- **Corrección** (y commit que la aplica): el test usa lr = 1e-3 y se añadió una prueba de que con 1e-2 no converge.
  Commit: `7188d66` (Fase 1: funciones, contador y descenso por gradiente).
- **Lección aprendida:** una tasa de aprendizaje fija se verifica contra la curvatura (2/λmax) antes de afirmar que converge.
- **Nota:** el error lo detectó el propio asistente antes de entregar el código; el fragmento fallido solo existe en la sesión, no en el repositorio.

### H-03 · Criterio de selección que desempataba mal en el experimento

- **Fecha / responsable:** 2026-10-09 · Sebastian Estrada
- **Modelo:** Claude (asistente de la sesión de trabajo)
- **Categoría:** código
- **Estado:** confirmado (leve)
- **Prompt (literal):** «continua con lo que me toca a mi realiza o dame las indicaciones para hacerlo»
- **Respuesta de la IA (literal):** el código generado ordenaba las tasas con `sort_values(["mediana", "lr"])`, es decir, ante empate elegía la tasa menor.
- **Sospecha** (qué parecía incorrecto): en la primera corrida de demostración, Rastrigin 2D eligió lr = 0.001 y no 0.003,
  con la misma mediana pero 138 evaluaciones frente a 42,5.
- **Evidencia** (fuente no generada por IA, o ejecución de código): prueba
  `test_desempate_elige_la_tasa_que_gasta_menos_evaluaciones` en `tests/test_gd_experiment.py`: con lr = 1e-3 y 3e-3 la
  mediana de f final es idéntica (21,39) y las evaluaciones medias son 140 frente a 42,7. Con el criterio anterior (ordenar
  por mediana y menor tasa) la prueba falla; con el actual pasa.
- **Corrección** (y commit que la aplica): el desempate usa evaluaciones medias y, si persiste, la menor tasa; la mediana se
  compara a 4 cifras significativas. Commit: `aae65b6` (Experimento GD de la Parte 1); prueba en `553d07f`.
- **Lección aprendida:** un criterio de selección con empates debe decir explícitamente qué cuesta menos, y se prueba con un caso de empate.
- **Nota:** el error lo detectó el propio asistente antes de entregar el código; la versión con el fallo no está en el repositorio.

### H-04 · Dos imprecisiones de Gemini sobre la geometría de Rosenbrock

- **Fecha / responsable:** 2026-10-12 · Sebastian Estrada
- **Modelo:** Gemini Pro 3.1
- **Categoría:** conceptos
- **Estado:** confirmado (leve)
- **Prompt (literal):** «por qué el descenso por gradiente falla en la función de rastrigin y por qué es lento en rosenbrock? explícalo con la geometría de cada función»
- **Respuesta de la IA (literal):**
  > El descenso por gradiente se comporta de manera deficiente en las funciones de Rastrigin y Rosenbrock, pero por dos razones geométricas completamente opuestas.
  >
  > Aquí te explico qué le ocurre al algoritmo al enfrentarse a la topología de cada una.
  >
  > 1. Función de Rastrigin: La trampa de los mínimos locales
  > Visualmente, la función de Rastrigin parece una cubeta para huevos o un cuenco gigante lleno de cientos de pequeñas ondulaciones. Matemáticamente, es una parábola a la que se le ha sumado una función coseno para crear "baches".
  >
  > El problema geométrico: Está plagada de mínimos locales. Tiene un único mínimo global (en el centro profundo), pero está rodeado por un campo minado de cráteres.
  >
  > Por qué falla el descenso por gradiente: El algoritmo es "miope" y codicioso. Solo mira hacia dónde la pendiente baja en su ubicación inmediata y camina hacia allí. Al soltar el algoritmo en casi cualquier punto de partida de la función de Rastrigin, bajará por la ladera más cercana y caerá en el primer "bache" (mínimo local) que encuentre. Una vez en el fondo de ese bache, el gradiente (la pendiente) es cero en todas las direcciones. Como el algoritmo no tiene impulso ni visión panorámica para saber que debe "subir" un poco para encontrar un valle aún más profundo, se detiene prematuramente, asumiendo erróneamente que ha resuelto el problema.
  >
  > 2. Función de Rosenbrock: El valle plano y curvo
  > Conocida popularmente como la "función banana", su geometría no tiene el problema de las múltiples trampas de Rastrigin, pero presenta un desafío de navegación extremo.
  >
  > El problema geométrico: Tiene forma de un cañón o valle parabólico. Las "paredes" de este valle son extremadamente empinadas, pero el "suelo" del valle es casi perfectamente plano y se curva lentamente (como una banana) hacia el mínimo global que se esconde en la punta.
  >
  > Por qué es lento el descenso por gradiente: Cuando el algoritmo comienza en las laderas, el gradiente lo empuja violentamente hacia abajo (hacia el fondo del valle). Sin embargo, debido a que el valle es curvo y estrecho, el algoritmo tiende a "pasarse de largo", rebotando contra la pared opuesta. Esto genera un efecto de zigzag u oscilación perpetua de pared a pared. Peor aún, una vez en el suelo del valle, la pendiente que apunta hacia el verdadero mínimo global es tan microscópica (el suelo es demasiado plano) que los pasos del algoritmo se vuelven diminutos. Termina rebotando de lado a lado mientras avanza a paso de tortuga por la curva de la banana.
  >
  > En resumen: En Rastrigin, el algoritmo fracasa porque es engañado por pozos falsos (falta de exploración global). En Rosenbrock, el algoritmo se estanca porque las paredes empinadas causan oscilación y el suelo plano destruye la velocidad de avance (problema de condicionamiento).
- **Sospecha** (qué parecía incorrecto): dos afirmaciones sobre Rosenbrock no coincidían con la función ni con las corridas
  propias: (1) que el mínimo global «se esconde en la punta» del valle; (2) que el algoritmo cae en una «oscilación perpetua de pared a pared».
- **Evidencia** (fuente no generada por IA, o ejecución de código):
  - El mínimo (1, 1) está en la mitad del valle parabólico, no en un extremo: el valle sigue hacia valores negativos de x₁.
    Sobre el fondo del valle (x₂ = x₁²) la función vale (1 − x₁)²: 9, 1, 0, 1 y 4 en x₁ = −2, 0, 1, 2 y 3. Se ve en
    `figures/gd/gd_rosenbrock_niveles.png`, donde la estrella está sobre la curva y no al final.
  - Con las tasas usadas (1e-5 a 2e-4) las trayectorias son suaves y no rebotan. Medición con `python -m experiments.gd_zigzag`
    (30 semillas en 2D): con η = 2e-4 solo el 0,03 % de los pasos se devuelve respecto al anterior (máximo 0,13 %); con
    η = 1e-3 se devuelve el 100 % y esas corridas terminan atrapadas contra el borde. El zigzag aparece solo con pasos cercanos
    al límite de estabilidad 2/λmax. Hessiano en (1, 1): [[802, −400], [−400, 200]], autovalores 0,3994 y 1001,6, número de
    condición 2508, 2/λmax = 0,001997 (cálculo ejecutado:
    `py -c "import numpy as np; H=np.array([[802.,-400.],[-400.,200.]]); w=np.linalg.eigvalsh(H); print(w, w[1]/w[0], 2/w[1])"`).
    Derivadas del hessiano: ∂²f/∂x² = 1200x² − 400y + 2, ∂²f/∂x∂y = −400x, ∂²f/∂y² = 200.
    [PENDIENTE: confirmar que la derivación fue hecha a mano por el responsable]
  - Nocedal y Wright (2006), Sec. 3.3, pp. 42 a 44: el descenso por pendiente máxima zigzaguea y su tasa de convergencia
    empeora al crecer el número de condición (Teoremas 3.3 y 3.4). Los teoremas suponen búsqueda de línea exacta; aquí se usan
    como respaldo cualitativo. Con κ ≈ 2508 en (1, 1) (cálculo propio) la tasa teórica es (κ − 1)/(κ + 1) ≈ 0,9992 por
    iteración en la norma ‖·‖_Q, o ≈ 0,9984 para f − f*.
  - Parte que acertó la IA: Rastrigin tiene muchos mínimos locales y el descenso se queda en el primer bache. Verificado con
    las 30 corridas (`results/gd/runs.csv`): ninguna llega al mínimo global y los valores finales se agrupan en mínimos locales (1,99; 3,98; 4,97…).
- **Corrección** (y commit que la aplica): el mínimo está en la mitad del valle, y la lentitud se explica por el número de
  condición (≈ 2508), con un paso máximo estable de ≈ 0,002. El informe (sección 7) lo explica así.
- **Lección aprendida:** una explicación geométrica correcta en lo general puede traer detalles falsos o exagerados; se
  contrasta con las trayectorias reales y con el cálculo del hessiano.

## Verificaciones sin error

### V-01 · Fórmulas, dominios y mínimos de Rosenbrock y Rastrigin vs. Surjanovic y Bingham

- **Fecha / responsable:** 2026-10-11 · Sebastian Estrada
- **Categoría:** matemáticas
- **Estado:** descartado (la IA acertó)
- **Prompt y respuesta:** el código de `src/functions.py` fue generado por Claude en la sesión del 2026-10-09 (prompt: «si yo quiero ser el que haga todo lo 1ro que deberia hacer»).
- **Qué verifiqué:** fórmula, dominio y mínimo global de cada función contra la página de Surjanovic y Bingham, _Virtual Library
  of Simulation Experiments_ (https://www.sfu.ca/~ssurjano/rastr.html y https://www.sfu.ca/~ssurjano/rosen.html), consultadas el 2026-10-11.
- **Resultado:** Rastrigin: f(x) = 10d + Σ[xᵢ² − 10 cos(2π xᵢ)], dominio [−5.12, 5.12], mínimo f(0, …, 0) = 0.
  Rosenbrock: f(x) = Σ[100(xᵢ₊₁ − xᵢ²)² + (xᵢ − 1)²], dominio [−5, 10] (alternativa [−2.048, 2.048]), mínimo f(1, …, 1) = 0.
  Todo coincide con `src/functions.py`.
- **Limitación:** la página no trae el gradiente; este se verificó con diferencias centrales en pytest y con derivación.
- **Lección aprendida:** [PENDIENTE: conclusión del responsable]

### V-02 · Contador de evaluaciones generado por IA (`src/contador_ia.py`)

- **Fecha / responsable:** 2026-10-11 · Sebastian Estrada
- **Modelo:** [PENDIENTE: modelo y versión que generó la clase]
- **Categoría:** código
- **Estado:** descartado (la IA acertó)
- **Prompt (literal):** [PENDIENTE: prompt exacto que se le dio a la IA]
- **Respuesta de la IA (literal):** [PENDIENTE: código completo que devolvió; coincide con `src/contador_ia.py`]
- **Qué verifiqué:** que un lote de 7 puntos cuenta 7, que el gradiente numérico cuesta 2n evaluaciones de f por punto y
  2·m·n por lote, que coincide con el gradiente analítico en Rosenbrock y Rastrigin, que las formas de salida y los errores
  son correctos y que `reset()` funciona.
- **Evidencia:** `py -m pytest tests/test_contador_ia.py -v` → 25 passed in 0.18s (Python 3.14.8, Windows).
- **Limitación:** las pruebas las escribió Claude, no el responsable. [PENDIENTE: añadir al menos una prueba propia y anotarla aquí]
- **Lección aprendida:** [PENDIENTE: conclusión del responsable]
