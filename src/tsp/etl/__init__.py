"""Adquisición, persistencia y transformación offline de datos de rutas.

Importar este paquete nunca realiza conexiones de red. Las llamadas solo ocurren
cuando el consumidor invoca explícitamente un proveedor.
"""

from .acquisition import AcquisitionManager, AcquisitionRequest, AcquisitionSummary
from .config import ETLConfig, load_etl_config
from .economics import FuelEconomics, apply_fuel_economics, load_fuel_economics
from .matrices import MatrixBuildReport, build_matrix_files
from .ors import OpenRouteServiceProvider, ProviderError, parse_ors_geojson, parse_ors_matrix
from .store import RouteStore

__all__ = [
    "AcquisitionManager", "AcquisitionRequest", "AcquisitionSummary", "ETLConfig", "load_etl_config",
    "FuelEconomics", "apply_fuel_economics", "load_fuel_economics",
    "MatrixBuildReport", "OpenRouteServiceProvider", "ProviderError",
    "RouteStore", "build_matrix_files", "parse_ors_geojson", "parse_ors_matrix",
]
