# Trabajo 1 · Optimización Numérica, Metaheurística y Combinatoria

Redes Neuronales y Algoritmos Bioinspirados · UNAL, Facultad de Minas · 2026-02

## Integrantes
- Leonard David Vivas Dallos
- José Nicolás Duque Linares
- Integrante 3

## Contenido

- **Parte 1:** Descenso por gradiente frente a algoritmo evolutivo, PSO y evolución diferencial, sobre dos funciones de prueba en 2D y 3D.
- **Parte 2:** Problema del viajero sobre las 47 capitales peninsulares de España, con colonia de hormigas y algoritmo genético.
$
\text{Costo} = \text{valor de la hora} \times \text{tiempo} + \text{peajes} + \text{combustible}
$

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `src/` | Algoritmos, funciones de prueba, contador de evaluaciones |
| `experiments/` | Un script por experimento |
| `configs/` | Parámetros (YAML) y semillas |
| `data/raw/`, `data/processed/` | Datos crudos del TSP y matrices derivadas |
| `results/`, `figures/` | Salidas regenerables |
| `tests/` | Pruebas unitarias |
| `docs/` | Decisiones, bitácora de alucinaciones |

## Reproducir

Cada experimento se ejecuta con un comando (se completa a medida que existan):

```bash
# Descenso por gradiente, versión de demostración (~15 s, con figuras y GIF)
python -m experiments.gd_experiment --config configs/gd_demo.yaml

# Descenso por gradiente, versión completa (~3,5 min con figuras)
python -m experiments.gd_experiment --config configs/gd.yaml

# Comparación de métodos con el mismo presupuesto y semillas (demo ~5 s; completa ~25 s)
python -m experiments.compare --config configs/compare_demo.yaml
python -m experiments.compare --config configs/compare.yaml
```

Cualquier parámetro del YAML se puede cambiar sin editar archivos con `--set clave=valor`
(se puede repetir), por ejemplo:

```bash
python -m experiments.gd_experiment --config configs/gd_demo.yaml --set tasas_aprendizaje.rosenbrock=[0.0004] --set n_runs=10
python -m experiments.compare --config configs/compare_demo.yaml --set metodos.gd.rosenbrock.lr=0.0003
```

Las demos escriben en `results/*_demo/` y `figures/*_demo/` (ignoradas por git), así que no
sobrescriben los resultados completos que están en el repositorio.

Salidas: `results/gd/runs.csv` (una fila por corrida), `results/gd/summary.csv` (media, desviación,
mejor, peor y tasa de éxito por tasa de aprendizaje) y `figures/gd/` (convergencia, cajas,
curvas de nivel y GIF en 2D). Los parámetros (presupuesto, tasas, umbrales) están en `configs/gd.yaml`.

Conteo de evaluaciones (ver [decisiones](docs/decisiones.md)): `runs.csv` reporta `f_evals` y
`grad_evals` por separado, más dos totales: `equiv_evals` (gradiente analítico = 1 evaluación; es el
que se compara con el presupuesto) y `equiv_evals_2n` (gradiente por diferencias centrales = 2n).
Una corrida es exitosa si f − f* ≤ umbral (`exito_0.0001` principal, `exito_0.01` secundario).

Formato común de los métodos: cada algoritmo es una función
`metodo(problem, seed, budget, grad_cost, **hiperparametros) -> RunResult` (ver `src/result.py`,
que también trae `check_result` para probar el contrato). Para sumar un método a la comparación
se registra en `src/methods.py` y se agregan sus hiperparámetros en `metodos:` de
`configs/compare.yaml`.

Informe de la Parte 1: la versión de trabajo está en el Google Docs compartido del equipo. El borrador
inicial (`docs/Informe_Parte1.docx`, ignorado por git) se genera desde `results/` y `figures/` con Node
(requiere haber corrido antes los experimentos completos); sirve para sacar las tablas actualizadas:

```bash
npm --prefix informe install    # una sola vez
npm --prefix informe run parte1
```

Las tablas se leen de los CSV; el texto del análisis está en `informe/build_parte1.js` y hay que
revisarlo a mano si cambian los resultados. Lo pendiente sale resaltado en amarillo.

## Documentación del equipo

- [Decisiones](docs/decisiones.md)
- [Cacería de la alucinación](docs/alucinaciones.md)
- [Fuentes de datos](data/fuentes.md)
- [Fundamentos del módulo TSP](docs/tsp_fase1.md)
- [Modelos duales del TSP](docs/tsp_modelo_dual.md)
- [Preparación de adquisición de datos reales del TSP](docs/tsp_adquisicion.md)
- [ETL local y construcción offline de matrices del TSP](docs/tsp_etl.md)
- [Inventario de peajes, piloto Overpass y límites de verificación](docs/tsp_peajes.md)
- [Ant System para el TSP dirigido](docs/tsp_aco.md)

Demostración sintética offline de ACO (no utiliza datos de España):

```bash
python -m experiments.tsp_aco_demo --config configs/tsp_aco_demo.yaml
```
