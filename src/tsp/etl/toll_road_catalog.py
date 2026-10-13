"""Lectura validada de corredores de peaje oficiales conocidos.

El catálogo identifica corredores para priorizar la adquisición. No afirma que
la vía completa sea tarifada ni reemplaza la confirmación de cada tramo.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROAD_FIELDS = (
    "road_id", "name", "toll_scope", "operator", "vehicle_scope",
    "valid_from", "valid_through", "source_url", "source_status", "notes",
)


@dataclass(frozen=True)
class TollRoadRecord:
    road_id: str
    name: str
    toll_scope: str
    operator: str
    vehicle_scope: str
    valid_from: str
    valid_through: str
    source_url: str
    source_status: str
    notes: str

    def __post_init__(self) -> None:
        for field in ("road_id", "name", "toll_scope", "vehicle_scope", "source_url", "source_status"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} no puede estar vacío")
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url debe usar HTTPS")
        if self.valid_from:
            date.fromisoformat(self.valid_from)
        if self.valid_through:
            date.fromisoformat(self.valid_through)
        if self.valid_from and self.valid_through and self.valid_from > self.valid_through:
            raise ValueError("intervalo de vigencia invertido")


def load_toll_road_catalog(path: str | Path) -> tuple[TollRoadRecord, ...]:
    """Carga CSV y rechaza IDs duplicados o columnas incompletas."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(ROAD_FIELDS).issubset(reader.fieldnames):
            missing = sorted(set(ROAD_FIELDS) - set(reader.fieldnames or ()))
            raise ValueError(f"faltan columnas del catálogo vial: {', '.join(missing)}")
        result: list[TollRoadRecord] = []
        seen: set[str] = set()
        for line, row in enumerate(reader, start=2):
            record = TollRoadRecord(**{field: (row.get(field) or "").strip() for field in ROAD_FIELDS})
            if record.road_id in seen:
                raise ValueError(f"road_id duplicado en línea {line}: {record.road_id}")
            seen.add(record.road_id)
            result.append(record)
    return tuple(result)
