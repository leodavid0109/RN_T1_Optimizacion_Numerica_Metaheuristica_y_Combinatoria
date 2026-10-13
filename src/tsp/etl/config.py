"""Carga y valida parámetros no secretos del ETL desde YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ETLConfig:
    profile: str
    directions_endpoint: str
    matrix_endpoint: str
    timeout_seconds: float
    max_retries: int
    minimum_seconds_between_requests: float
    standard_plan_daily_directions_limit: int
    standard_plan_daily_matrix_limit: int
    route_catalog: Path
    raw_responses: Path
    matrices: Path


def load_etl_config(path: str | Path = "configs/tsp_etl.yaml") -> ETLConfig:
    """Carga el YAML del proyecto y valida valores operativos esenciales."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        provider = data["provider"]
        storage = data["storage"]
        config = ETLConfig(
            profile=str(data["profile"]),
            directions_endpoint=str(data["directions_endpoint"]).rstrip("/"),
            matrix_endpoint=str(data["matrix_endpoint"]).rstrip("/"),
            timeout_seconds=float(data["timeout_seconds"]),
            max_retries=int(data["max_retries"]),
            minimum_seconds_between_requests=float(data["minimum_seconds_between_requests"]),
            standard_plan_daily_directions_limit=int(data["standard_plan_daily_directions_limit"]),
            standard_plan_daily_matrix_limit=int(data["standard_plan_daily_matrix_limit"]),
            route_catalog=Path(storage["route_catalog"]),
            raw_responses=Path(storage["raw_responses"]),
            matrices=Path(storage["matrices"]),
        )
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"configuración ETL inválida en {path}: {exc}") from exc
    if provider != "openrouteservice":
        raise ValueError("por ahora solo está implementado el proveedor openrouteservice")
    if (not config.profile or not config.directions_endpoint.startswith("https://")
            or not config.matrix_endpoint.startswith("https://")
            or config.timeout_seconds <= 0 or config.max_retries < 0
            or config.minimum_seconds_between_requests < 0
            or config.standard_plan_daily_directions_limit < 1
            or config.standard_plan_daily_matrix_limit < 1):
        raise ValueError("la configuración ETL contiene parámetros fuera de rango")
    return config
