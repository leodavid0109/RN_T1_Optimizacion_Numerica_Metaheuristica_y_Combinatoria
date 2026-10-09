# Trabajo 1 · Optimización numérica, metaheurística y combinatoria

Redes neuronales y algoritmos bioinspirados · UNAL, Facultad de Minas · 2026-02

## Contenido

- **Parte 1:** descenso por gradiente frente a algoritmo evolutivo, PSO y evolución diferencial, sobre dos funciones de prueba en 2D y 3D.
- **Parte 2:** problema del viajero sobre las 47 capitales peninsulares de España, con colonia de hormigas y algoritmo genético; costo = valor de la hora × tiempo + peajes + combustible.

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
# python -m experiments.<nombre> --config configs/<nombre>.yaml
```

## Documentación del equipo

- [Decisiones](docs/decisiones.md)
- [Cacería de la alucinación](docs/alucinaciones.md)
- [Fuentes de datos](data/fuentes.md)
