"""Carga de configuraciones YAML con cambios desde la línea de comandos.

Un cambio tiene la forma `clave.subclave=valor`; el valor se interpreta como YAML:

    n_runs=5
    presupuesto.2=5000
    tasas_aprendizaje.rosenbrock=[0.0001,0.0004]
    metodos.gd.rosenbrock.lr=0.0003
"""
from __future__ import annotations

import yaml


def _key(d: dict, part: str):
    """Las claves numéricas del YAML (p. ej. presupuesto: {2: ...}) son int, no str."""
    if part not in d and part.lstrip("-").isdigit():
        return int(part)
    return part


def apply_override(cfg: dict, override: str) -> dict:
    if "=" not in override:
        raise ValueError(f"cambio inválido {override!r}: se espera clave=valor")
    path, raw = override.split("=", 1)
    parts = path.strip().split(".")
    d = cfg
    for part in parts[:-1]:
        k = _key(d, part)
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[_key(d, parts[-1])] = yaml.safe_load(raw)
    return cfg


def load_config(path, overrides=()) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for o in overrides:
        apply_override(cfg, o)
    return cfg
