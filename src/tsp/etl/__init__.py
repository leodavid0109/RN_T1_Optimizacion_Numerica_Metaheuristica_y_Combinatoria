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
from .toll_infrastructure import (
    BoundingBox, OverpassCatalogStore, OverpassClient, OverpassError, RouteMatchCandidate, TollInfrastructure,
    load_infrastructure_catalog, match_infrastructure_to_route, parse_overpass_response,
    save_infrastructure_catalog,
)
from .toll_tariffs import (
    RouteTollAssessment, RouteTollSection, TollTariff, apply_toll_assessment,
    assess_route_tolls, export_official_tariffs_csv, import_official_tariffs_csv,
)

__all__ = [
    "AcquisitionManager", "AcquisitionRequest", "AcquisitionSummary", "ETLConfig", "load_etl_config",
    "FuelEconomics", "apply_fuel_economics", "load_fuel_economics",
    "MatrixBuildReport", "OpenRouteServiceProvider", "ProviderError",
    "RouteStore", "build_matrix_files", "parse_ors_geojson", "parse_ors_matrix",
    "BoundingBox", "OverpassCatalogStore", "OverpassClient", "OverpassError", "RouteMatchCandidate",
    "TollInfrastructure",
    "load_infrastructure_catalog", "match_infrastructure_to_route", "parse_overpass_response",
    "save_infrastructure_catalog",
    "RouteTollAssessment", "RouteTollSection", "TollTariff", "apply_toll_assessment",
    "assess_route_tolls", "export_official_tariffs_csv", "import_official_tariffs_csv",
]
