"""Prepare an offline request manifest for a four-city TSP routing pilot.

This module reads the verified city catalogue and prints request *templates*.
It does not contact a routing service, download map data, or create route costs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from src.tsp.cities import CATALOG_PATH, City, load_city_catalog


PILOT_CITY_IDS = ("madrid", "toledo", "bizkaia", "zaragoza")


def build_pilot_manifest(cities: Sequence[City]) -> dict[str, Any]:
    """Build a deterministic OSRM pilot plan from canonical city records.

    The manifest describes 12 non-diagonal directed arcs. It includes one
    fastest-route table, and route requests for fast and toll-excluded
    candidates. It intentionally contains no distances, durations, or costs.
    """
    by_id = {city.city_id: city for city in cities}
    if len(by_id) != len(cities):
        raise ValueError("el catálogo contiene identificadores duplicados")
    missing = [city_id for city_id in PILOT_CITY_IDS if city_id not in by_id]
    if missing:
        raise ValueError(f"faltan ciudades del piloto en el catálogo: {', '.join(missing)}")

    pilot_cities = [by_id[city_id] for city_id in PILOT_CITY_IDS]
    for city in pilot_cities:
        if city.coordinate_status != "verificada" or city.latitude is None or city.longitude is None:
            raise ValueError(f"la coordenada de {city.city_id} no está verificada")

    arcs = [
        {"origin_id": origin.city_id, "destination_id": destination.city_id}
        for origin in pilot_cities
        for destination in pilot_cities
        if origin.city_id != destination.city_id
    ]
    coordinates_lon_lat = [
        {"city_id": city.city_id, "longitude": city.longitude, "latitude": city.latitude}
        for city in pilot_cities
    ]
    return {
        "schema_version": 1,
        "purpose": "pilot_request_plan_only",
        "network_access_performed": False,
        "source_catalog": "data/processed/capitales_peninsulares.csv",
        "coordinate_order": "longitude,latitude (GeoJSON/OSRM)",
        "city_order": list(PILOT_CITY_IDS),
        "input_coordinates_ign": coordinates_lon_lat,
        "directed_arc_count": len(arcs),
        "directed_arcs": arcs,
        "requests": [
            {
                "id": "osrm_fastest_table",
                "engine": "OSRM",
                "service": "table",
                "profile": "driving",
                "annotations": ["distance", "duration"],
                "sources": "all",
                "destinations": "all",
                "coordinates": "input_coordinates_ign_in_city_order",
                "purpose": "fastest-route directed distances and durations",
            },
            {
                "id": "osrm_fastest_route_geometry",
                "engine": "OSRM",
                "service": "route",
                "profile": "driving",
                "per_directed_arc": True,
                "arc_count": len(arcs),
                "parameters": {
                    "steps": True,
                    "geometries": "geojson",
                    "overview": "full",
                    "alternatives": 2,
                },
                "purpose": "retain directed route geometry, road classes and any returned alternatives",
            },
            {
                "id": "osrm_toll_excluded_candidates",
                "engine": "OSRM",
                "service": "route",
                "profile": "driving",
                "per_directed_arc": True,
                "arc_count": len(arcs),
                "parameters": {
                    "steps": True,
                    "geometries": "geojson",
                    "overview": "full",
                    "exclude": ["toll"],
                },
                "precondition": "local car profile must expose the toll class as excludable and be preprocessed with that profile",
                "purpose": "candidate intended to avoid OSM-tagged toll ways; verify response geometry and toll tags",
            },
        ],
        "explicitly_not_provided": [
            "snapped coordinates",
            "route distances or durations",
            "toll presence or tariff",
            "fuel costs",
            "verified route alternatives",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=CATALOG_PATH,
        help="CSV canónico de ciudades (predeterminado: catálogo del repositorio)",
    )
    arguments = parser.parse_args(argv)
    manifest = build_pilot_manifest(load_city_catalog(arguments.catalog))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
