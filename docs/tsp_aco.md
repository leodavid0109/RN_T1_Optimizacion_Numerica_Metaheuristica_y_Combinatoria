# Ant System para el TSP dirigido

## Alcance

`src/tsp/aco.py` implementa Ant System (AS), la versión clásica de colonia de
hormigas, para minimizar el costo de ciclos dirigidos. El algoritmo optimiza el
orden de visita de las ciudades. En el Modelo A, cada arco conserva su trayecto
rápido; en el Modelo B, el objetivo existente elige por arco la alternativa
económica para el valor horario configurado. ACO no consulta proveedores ni
elige geometrías de carretera directamente.

La implementación utiliza los contratos existentes `TSPAlgorithm`,
`TSPObjective`, `RunEvaluator` y `TSPRunResult`. No crea una interfaz paralela ni
cambia la interfaz que puede implementar el GA. Como el objetivo recibe la
misma instancia y solo devuelve el desglose de una ruta completa, ambos métodos
pueden compararse por el número de evaluaciones completas. Ese presupuesto no
implica que cada evaluación o cada operador tenga el mismo costo de CPU.

## Formulación

Sea `c[i,j]` el costo dirigido del arco `i -> j` a partir de la matriz efectiva
del objetivo. Una solución es una permutación `π` de las `N` ciudades y su ciclo
incluye el arco de regreso:

```text
C(π) = Σ(k=0..N-1) c[π[k], π[(k+1) mod N]]
```

Cada hormiga parte de una ciudad elegida con el generador local de la semilla y
añade, sin repetición, una ciudad no visitada. Para un destino candidato `j`:

```text
P(i,j) = τ[i,j]^α · η[i,j]^β / Σ(l no visitada) τ[i,l]^α · η[i,l]^β
η[i,j] = 1 / c[i,j]
```

La matriz `τ` es dirigida: `τ[i,j]` y `τ[j,i]` se actualizan por separado.
También se respeta la asimetría de `c`; no se promedian ni reflejan arcos.

### Estabilidad numérica

Los pesos se normalizan mediante logaritmos y softmax, evitando calcular
potencias grandes o recíprocos que desborden. Si `β > 0` y algunos arcos
candidatos tienen costo exactamente cero, se asigna probabilidad cero a los
arcos positivos: corresponde al límite de `1/c` al acercarse `c` a cero. Entre
los arcos de costo cero, la feromona determina la probabilidad. Si `β = 0`, se
ignora la heurística, incluso para costos cero.

La matriz de costos del contrato debe tener valores finitos no negativos; los
arcos prohibidos o no finitos se rechazan. La diagonal debe ser cero, aunque no
se ofrece como candidato durante la construcción. Las feromonas se mantienen
positivas mediante un piso numérico y se saturan antes de desbordarse. Si el
costo total de una ruta es cero, `Q/C` no está definido: se usa un depósito
finito `Q`, documentado como caso límite para instancias sintéticas.

## Evaporación y depósito

Al terminar la colonia (que puede ser parcial por el presupuesto), se aplica:

```text
τ[i,j] ← (1 - ρ) τ[i,j]
τ[i,j] ← τ[i,j] + Σ(k usa i->j) Q / Ck
```

Cada depósito recorre todos los arcos del ciclo cerrado, incluido el retorno al
origen. Cuando `ρ = 1`, la evaporación elimina la memoria anterior y el piso
numérico evita feromonas nulas. `α` controla la influencia de feromonas;
`β` controla la preferencia heurística por costos bajos. `ρ` controla la pérdida
de feromona; `Q` escala los depósitos; `τ0` inicializa arcos dirigidos.

Al comienzo de cada colonia, todas las hormigas usan la feromona de la iteración
anterior. Después se evaporan y se suman los depósitos de esa colonia, siguiendo
Ant System clásico.

## Presupuesto y convergencia

`budget` mide llamadas de evaluación de rutas completas a través de
`RunEvaluator`. Construir una ruta y calcular probabilidades no consume una
evaluación, aunque sí forma parte del tiempo de ejecución. Cada ruta construida
se evalúa inmediatamente; el algoritmo no crea rutas sobrantes. Si restan menos
evaluaciones que `n_ants`, se ejecuta una colonia parcial de exactamente ese
tamaño y termina. No se llama de nuevo al objetivo para formar la salida.

`RunEvaluator` conserva un `ConvergencePoint` al encontrar un nuevo mejor costo,
con el contador acumulado de evaluaciones de esa ruta. Por eso el historial es
monótono y disperso (solo mejoras); al comparar curvas sobre una cuadrícula de
presupuesto se conserva el último mejor valor conocido. El resultado declara
`presupuesto_agotado` y reporta evaluaciones realmente utilizadas.

## Reproducibilidad y parámetros

Cada ejecución crea un `random.Random(seed)` local; no usa ni altera el estado
aleatorio global. Con la misma instancia, semilla, presupuesto y parámetros se
obtienen la misma ruta, costo e historial. El tiempo de ejecución se mide solo
en la demo y no pertenece al resultado determinista.

La configuración demostrativa está en `configs/tsp_aco_demo.yaml`:

| Parámetro | Valor demostrativo | Restricción |
|---|---:|---|
| `n_ants` | 10 | entero positivo |
| `alpha` | 1.0 | finito, no negativo |
| `beta` | 2.0 | finito, no negativo |
| `rho` | 0.5 | `0 < rho <= 1` |
| `q` | 1.0 | finito, positivo |
| `tau0` | 1.0 | finito, positivo |
| `presupuesto` | 73 | entero positivo de rutas completas |
| `semilla` | 42 | entero |

Son valores iniciales para demostrar el programa, no parámetros científicos
definitivos. Se deben seleccionar mediante experimentos repetidos y análisis de
sensibilidad antes de presentar resultados académicos.

## Pseudocódigo

```text
crear evaluador con presupuesto B
crear RNG local(seed) y τ[i,j] = τ0
mientras evaluaciones < B:
    tamaño_colonia = min(n_ants, B - evaluaciones)
    para cada hormiga de esa colonia:
        elegir inicio con RNG
        mientras queden ciudades:
            muestrear destino entre no visitadas con τ^α · (1/c)^β
        evaluar el ciclo cerrado una vez con RunEvaluator
        guardar ciclo y costo para el depósito
    evaporar τ con (1 - ρ)
    depositar Q/C en cada arco dirigido, incluido el retorno
devolver RunEvaluator.finish(seed, "presupuesto_agotado")
```

## Complejidad y limitaciones

Para una colonia de `m` hormigas y `N` ciudades, construir las rutas cuesta
`O(m N²)` en la implementación directa porque se recalculan probabilidades
entre destinos candidatos; almacenar feromonas y costos cuesta `O(N²)`. La
actualización de feromonas cuesta `O(mN + N²)`. El presupuesto puede dejar una
última colonia incompleta.

AS es estocástico y no demuestra optimalidad global. Puede converger
prematuramente, y sus parámetros afectan exploración y explotación. La matriz
de heurística se basa en costo económico efectivo; si un costo de arco no es
verificable (por ejemplo, peaje desconocido en Modelo B), el objetivo existente
rechaza la evaluación en lugar de imputar cero. El algoritmo no convierte una
ruta `avoid_tolls` en una tarifa verificada.

La demostración es una instancia sintética dirigida pequeña, solo para validar
ejecución, presupuesto e historial. No representa España ni constituye un
resultado del experimento. Ejecución offline desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m experiments.tsp_aco_demo --config configs/tsp_aco_demo.yaml
```

Los parámetros se pueden sobrescribir con el cargador existente:

```powershell
.\.venv\Scripts\python.exe -m experiments.tsp_aco_demo --set presupuesto=101 --set aco.n_ants=12
```

La salida incluye semilla, parámetros, presupuesto solicitado y usado, mejor
recorrido/costo, desglose, convergencia y tiempo local de ejecución. Opcionalmente
se guarda el JSON con `--output results/tsp_aco_demo/run.json`.
