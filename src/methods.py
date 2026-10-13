
"""Registro de métodos de la Parte 1 con la firma común definida en src/result.py.
Para sumar un método: implementarlo en su propio módulo de src/ con esa firma y agregarlo
a METHODS. experiments/compare.py lo toma de aquí por su nombre en el YAML.
"""
from __future__ import annotations

from .differential_evolution import run_de
from .evolutionary_algorithm import run_ea
from .gradient_descent import run_gd
from .particle_swarm import run_pso

METHODS = {
    "gd": run_gd,
    "ea": run_ea,
    "pso": run_pso,
    "de": run_de,
}
