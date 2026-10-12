"""Registro de métodos de la Parte 1 con la firma del formato común (ver src/result.py).

Para sumar un método: implementarlo en su propio módulo de src/ con esa firma y agregarlo
a METHODS. experiments/compare.py lo toma de aquí por su nombre en el YAML.
"""
from __future__ import annotations

from .gradient_descent import run_gd

METHODS = {
    "gd": run_gd,
    # "ea": run_ea,    # algoritmo evolutivo (integrante 2)
    # "pso": run_pso,  # enjambre de partículas (integrante 2)
    # "de": run_de,    # evolución diferencial (integrante 2)
}


from .particle_swarm import run_pso

METHODS = {
    "gd": run_gd,
    "pso": run_pso,
}