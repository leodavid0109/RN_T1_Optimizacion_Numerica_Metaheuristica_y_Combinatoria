"""Adquisición, persistencia y transformación offline de datos de rutas.

Importar este paquete nunca realiza conexiones de red. Las llamadas solo ocurren
cuando el consumidor invoca explícitamente un proveedor.
"""

from .acquisition import AcquisitionManager, AcquisitionRequest, AcquisitionSummary
from .config import ETLConfig, load_etl_config
from .economics import FuelEconomics, apply_fuel_economics, load_fuel_economics
from .dataset_export import export_spain_dataset, load_published_dataset
from .matrices import MatrixBuildReport, build_fuel_matrix, build_matrix_files
from .matrix_validation import MatrixDirectionsDifference, compare_matrix_to_directions
from .ors import OpenRouteServiceProvider, ProviderError, parse_ors_geojson, parse_ors_matrix
from .store import RouteStore
from .toll_infrastructure import (
    BoundingBox, OverpassCatalogStore, OverpassClient, OverpassError, RouteMatchCandidate, TollInfrastructure,
    load_infrastructure_catalog, match_infrastructure_to_route, match_route_alternatives_to_infrastructure,
    parse_overpass_response,
    save_infrastructure_catalog,
)
from .toll_tariffs import (
    RouteTollAssessment, RouteTollSection, TollTariff, apply_toll_assessment,
    assess_route_tolls, export_official_tariffs_csv, import_official_tariffs_csv,
)
from .toll_coverage import ArcTollCoverage, TollCoverageReport, build_toll_coverage_report, coverage_report_as_dict
from .tollguru import TollGuruClient, TollGuruError, TollGuruRequestPlan, TollGuruResponse

__all__ = [
    "AcquisitionManager", "AcquisitionRequest", "AcquisitionSummary", "ETLConfig", "load_etl_config",
    "FuelEconomics", "apply_fuel_economics", "load_fuel_economics",
    "export_spain_dataset", "load_published_dataset",
    "MatrixBuildReport", "MatrixDirectionsDifference", "OpenRouteServiceProvider", "ProviderError",
    "RouteStore", "build_fuel_matrix", "build_matrix_files", "compare_matrix_to_directions",
    "parse_ors_geojson", "parse_ors_matrix",
    "BoundingBox", "OverpassCatalogStore", "OverpassClient", "OverpassError", "RouteMatchCandidate",
    "TollInfrastructure",
    "load_infrastructure_catalog", "match_infrastructure_to_route",
    "match_route_alternatives_to_infrastructure", "parse_overpass_response",
    "save_infrastructure_catalog",
    "RouteTollAssessment", "RouteTollSection", "TollTariff", "apply_toll_assessment",
    "assess_route_tolls", "export_official_tariffs_csv", "import_official_tariffs_csv",
    "ArcTollCoverage", "TollCoverageReport", "build_toll_coverage_report", "coverage_report_as_dict",
    "TollGuruClient", "TollGuruError", "TollGuruRequestPlan", "TollGuruResponse",
]
