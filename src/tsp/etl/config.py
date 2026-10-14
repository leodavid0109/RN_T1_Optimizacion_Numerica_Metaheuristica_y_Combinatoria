"""Carga y valida parámetros no secretos del ETL desde YAML."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml


DEFAULT_DIRECTIONS_ENDPOINT = "https://api.heigit.org/openrouteservice/v2/directions"
DEFAULT_MATRIX_ENDPOINT = "https://api.heigit.org/openrouteservice/v2/matrix"
_LEGACY_ORS_HOST = "api.openrouteservice.org"


def normalize_ors_endpoint(value: str, service: str) -> str:
    """Normaliza el endpoint ORS y rechaza el host obsoleto o URLs con secretos."""
    if service not in {"directions", "matrix"}:
        raise ValueError("servicio ORS no reconocido")
    try:
        parts = urlsplit(str(value).strip())
        host = (parts.hostname or "").lower()
        if (parts.scheme != "https" or not host or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError("el endpoint ORS debe ser HTTPS y no incluir credenciales ni parámetros")
        if host == _LEGACY_ORS_HOST:
            raise ValueError("api.openrouteservice.org está obsoleto; use api.heigit.org/openrouteservice/v2")
        if host == "api.heigit.org":
            # Admitir base, /openrouteservice, /v2 o el endpoint completo sin
            # duplicar segmentos al construir la URL final.
            path_parts = [part for part in parts.path.split("/") if part]
            allowed = {"openrouteservice", "v2", service}
            if any(part not in allowed for part in path_parts):
                raise ValueError("la ruta del endpoint HeiGIT contiene segmentos inesperados")
            if len(path_parts) != len(set(path_parts)):
                raise ValueError("la ruta del endpoint HeiGIT duplica segmentos")
            return urlunsplit(("https", "api.heigit.org",
                               f"/openrouteservice/v2/{service}", "", ""))
        if not parts.path.strip("/"):
            raise ValueError("un endpoint ORS de proveedor alternativo requiere una ruta explícita")
        return urlunsplit(("https", parts.netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("endpoint ORS inválido") from exc


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
        # Precedencia explícita: variable de entorno > YAML > valor predeterminado.
        directions_value = os.environ.get("ORS_DIRECTIONS_ENDPOINT") or data.get(
            "directions_endpoint", DEFAULT_DIRECTIONS_ENDPOINT
        )
        matrix_value = os.environ.get("ORS_MATRIX_ENDPOINT") or data.get(
            "matrix_endpoint", DEFAULT_MATRIX_ENDPOINT
        )
        config = ETLConfig(
            profile=str(data["profile"]),
            directions_endpoint=normalize_ors_endpoint(directions_value, "directions"),
            matrix_endpoint=normalize_ors_endpoint(matrix_value, "matrix"),
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
