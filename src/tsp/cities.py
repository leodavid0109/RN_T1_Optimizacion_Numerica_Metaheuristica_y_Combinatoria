"""Catálogo y validación de ciudades para el problema del viajero."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "capitales_peninsulares.csv"
EXPECTED_CITY_COUNT = 47


@dataclass(frozen=True)
class City:
    """Ciudad del catálogo; las coordenadas pueden quedar pendientes de verificación."""

    city_id: str
    name: str
    province: str
    latitude: float | None
    longitude: float | None
    source_url: str
    consulted_on: str
    coordinate_status: str
    representative_point_definition: str


def validate_city_catalog(cities: Iterable[City], expected_count: int = EXPECTED_CITY_COUNT) -> tuple[City, ...]:
    """Valida identificadores, nombres y coordenadas sin exigir coordenadas aún no verificadas."""
    records = tuple(cities)
    if len(records) != expected_count:
        raise ValueError(f"se esperaban {expected_count} ciudades y se recibieron {len(records)}")

    ids = [city.city_id.strip() for city in records]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("el catálogo contiene identificadores vacíos o duplicados")

    names = [city.name.strip().casefold() for city in records]
    provinces = [city.province.strip().casefold() for city in records]
    if any(not name for name in names) or any(not province for province in provinces) or len(set(names)) != len(names):
        raise ValueError("el catálogo contiene ciudades/provincias vacías o ciudades duplicadas")

    for city in records:
        if not city.source_url or not city.consulted_on:
            raise ValueError(f"falta procedencia del registro {city.city_id}")
        if (city.latitude is None) != (city.longitude is None):
            raise ValueError(f"coordenadas incompletas para {city.city_id}: latitud y longitud deben ir juntas")
        if city.latitude is None:
            if city.coordinate_status != "pendiente":
                raise ValueError(f"{city.city_id} no tiene coordenadas pero no está marcado pendiente")
            continue
        if not -90 <= city.latitude <= 90 or not -180 <= city.longitude <= 180:
            raise ValueError(f"coordenadas fuera de rango para {city.city_id}")
        if city.coordinate_status != "verificada":
            raise ValueError(f"{city.city_id} tiene coordenadas y debe marcarse como verificadas")
    return records


def load_city_catalog(path: str | Path = CATALOG_PATH) -> tuple[City, ...]:
    """Carga el CSV canónico de capitales y valida sus registros."""
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        required = {field for field in City.__dataclass_fields__}
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise ValueError(f"el catálogo debe incluir las columnas: {', '.join(sorted(required))}")
        cities = []
        for row in rows:
            latitude = float(row["latitude"]) if row["latitude"].strip() else None
            longitude = float(row["longitude"]) if row["longitude"].strip() else None
            cities.append(City(
                city_id=row["city_id"].strip(),
                name=row["name"].strip(),
                province=row["province"].strip(),
                latitude=latitude,
                longitude=longitude,
                source_url=row["source_url"].strip(),
                consulted_on=row["consulted_on"].strip(),
                coordinate_status=row["coordinate_status"].strip(),
                representative_point_definition=row["representative_point_definition"].strip(),
            ))
    return validate_city_catalog(cities)
