"""Carga y validación de matrices dirigidas del TSP."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def validate_matrix(matrix, size: int, name: str) -> np.ndarray:
    """Devuelve una copia float NxN de valores finitos no negativos, sin imponer simetría."""
    values = np.asarray(matrix, dtype=float)
    if values.shape != (size, size):
        raise ValueError(f"{name} debe tener dimensión {(size, size)}, recibió {values.shape}")
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contiene valores no finitos")
    if np.any(values < 0):
        raise ValueError(f"{name} contiene valores negativos")
    if not np.allclose(np.diag(values), 0.0, rtol=0.0, atol=1e-12):
        raise ValueError(f"la diagonal de {name} debe ser cero")
    result = values.copy()
    result.setflags(write=False)
    return result


def load_matrix_csv(path: str | Path, size: int, name: str) -> np.ndarray:
    """Carga una matriz cuadrada CSV sin cabeceras y aplica las validaciones del modelo."""
    path = Path(path)
    try:
        values = np.loadtxt(path, delimiter=",", dtype=float, ndmin=2)
    except (OSError, ValueError) as exc:
        raise ValueError(f"no se pudo cargar la matriz {name} desde {path}: {exc}") from exc
    return validate_matrix(values, size, name)
