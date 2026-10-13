"""Almacén local de alternativas y respuestas crudas, con escritura atómica."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Iterable

from ..alternatives import RouteAlternative


class RouteStore:
    """Mantiene catálogo CSV, estados de solicitudes y JSON crudo sin credenciales."""

    def __init__(self, root: str | Path, *, raw_dir: str | Path | None = None) -> None:
        self.root = Path(root)
        self.raw_dir = Path(raw_dir) if raw_dir is not None else self.root / "raw"
        self.catalog_path = self.root / "route_alternatives.csv"
        self.state_path = self.root / "acquisition_state.json"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {"schema_version": 1, "requests": {}}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def request_succeeded(self, request_id: str) -> bool:
        return self._state()["requests"].get(request_id, {}).get("status") == "adquirida"

    def count_acquired_on(self, day: str, request_prefix: str = "") -> int:
        return sum(
            1 for key, entry in self._state()["requests"].items()
            if key.startswith(request_prefix) and entry.get("status") == "adquirida"
            and entry.get("acquired_on") == day
        )

    def save_success(
        self, request_id: str, safe_request: dict, response: dict,
        alternatives: Iterable[RouteAlternative],
    ) -> None:
        alternatives = tuple(alternatives)
        if not alternatives:
            raise ValueError("no se puede persistir una solicitud sin rutas válidas")
        rows = self._read_catalog()
        previous = [row for row in rows if row["request_id"] == request_id]
        current = [row for row in rows if row["request_id"] != request_id]
        previous_by_id = {row["alternative_id"]: row for row in previous}
        incoming = []
        replaced = []
        for route in alternatives:
            row = {"request_id": request_id, **_alternative_to_row(route)}
            old = previous_by_id.get(route.alternative_id)
            if old is not None and _same_route_observation(old, row):
                _preserve_verified_cost_inputs(old, row)
            elif old is not None:
                replaced.append(old)
            incoming.append(row)
        removed = [row for row in previous if row["alternative_id"] not in {r.alternative_id for r in alternatives}]
        archived = [*replaced, *removed]
        if archived:
            archive_dir = self.raw_dir / "catalog_history"
            archive_id = sha256(json.dumps(archived, sort_keys=True).encode()).hexdigest()[:12]
            _write_csv_atomic(archive_dir / f"{_safe_filename(request_id)}_{archive_id}.csv",
                              archived, ["request_id", *_csv_fields()])
        _write_csv_atomic(self.catalog_path, [*current, *incoming], ["request_id", *_csv_fields()])
        response_digest = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        raw_record = {
            "schema_version": 1,
            "request_id": request_id,
            "request": safe_request,
            "response": response,
            "attribution": "© openrouteservice by HeiGIT | Data © OpenStreetMap contributors",
            "results_license": "CC-BY-SA 4.0 según respuesta HeiGIT del 2026-10-12; confirmar términos vigentes de la cuenta",
        }
        raw_path = self.raw_dir / f"{_safe_filename(request_id)}_{response_digest}.json"
        _write_text_atomic(
            raw_path,
            json.dumps(raw_record, ensure_ascii=False, indent=2) + "\n",
        )
        state = self._state()
        state["requests"][request_id] = {
            "status": "adquirida", "alternative_count": len(alternatives),
            "acquired_on": datetime.now(timezone.utc).date().isoformat(),
            "raw_file": str(raw_path),
            "active_alternative_ids": [route.alternative_id for route in alternatives],
        }
        self._write_state(state)

    def save_failure(
        self, request_id: str, error_type: str, *, http_requests: int = 0,
        http_status_codes: Iterable[int] = (),
    ) -> None:
        state = self._state()
        state["requests"][request_id] = {
            "status": "error", "error_type": error_type,
            "http_requests": http_requests, "http_status_codes": list(http_status_codes),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_state(state)

    def save_matrix_snapshot(
        self, request_id: str, safe_request: dict, response: dict,
        normalized: dict, city_order: list[str],
    ) -> None:
        """Persiste respuesta Matrix y matrices numéricas locales etiquetadas."""
        size = len(city_order)
        if size < 2 or len(set(city_order)) != size:
            raise ValueError("el orden de ciudades del snapshot debe ser único y contener al menos dos ids")
        paths = {}
        for metric, matrix in normalized.items():
            if metric not in {"distance_km", "time_hours"} or len(matrix) != size \
                    or any(len(row) != size for row in matrix):
                raise ValueError("snapshot Matrix requiere matrices cuadradas km/h con orden canónico")
            response_digest = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            path = self.root / f"{metric}_{_safe_filename(request_id)}_{response_digest}.csv"
            _write_csv_atomic(path, [
                {"city_id": city_id, **{other_id: ("" if matrix[i][j] is None else str(matrix[i][j]))
                                       for j, other_id in enumerate(city_order)}}
                for i, city_id in enumerate(city_order)
            ], ["city_id", *city_order])
            paths[metric] = str(path.relative_to(self.root))
        raw_record = {"schema_version": 1, "request_id": request_id,
                      "request": safe_request, "response": response,
                      "city_order": city_order, "normalized_matrix_files": paths,
                      "attribution": "© openrouteservice by HeiGIT | Data from OpenStreetMap",
                      "results_license": "CC-BY-SA 4.0 según respuesta HeiGIT del 2026-10-12; confirmar términos vigentes de la cuenta"}
        raw_path = self.raw_dir / f"{_safe_filename(request_id)}_{response_digest}.json"
        _write_text_atomic(raw_path, json.dumps(raw_record, ensure_ascii=False, indent=2) + "\n")
        state = self._state()
        state["requests"][request_id] = {
            "status": "adquirida", "kind": "matrix", "city_count": size,
            "acquired_on": datetime.now(timezone.utc).date().isoformat(),
            "raw_file": str(raw_path), "normalized_matrix_files": paths,
        }
        self._write_state(state)

    def load_alternatives(self) -> tuple[RouteAlternative, ...]:
        return tuple(_row_to_alternative(row) for row in self._read_catalog())

    def _read_catalog(self) -> list[dict[str, str]]:
        if not self.catalog_path.exists():
            return []
        with self.catalog_path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def _write_state(self, state: dict) -> None:
        _write_text_atomic(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _csv_fields() -> list[str]:
    return [field for field in RouteAlternative.__dataclass_fields__]


def _alternative_to_row(route: RouteAlternative) -> dict[str, str]:
    row = {}
    for field in _csv_fields():
        value = getattr(route, field)
        if value is None:
            row[field] = ""
        elif isinstance(value, tuple):
            row[field] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            row[field] = str(value.value if hasattr(value, "value") else value)
    return row


def _same_route_observation(old: dict[str, str], new: dict[str, str]) -> bool:
    """Solo conserva verificaciones económicas si la ruta geométrica no cambió."""
    if old["origin_id"] != new["origin_id"] or old["destination_id"] != new["destination_id"]:
        return False
    if not old.get("geometry_lon_lat") or old["geometry_lon_lat"] != new.get("geometry_lon_lat"):
        return False
    return all(math.isclose(float(old[field]), float(new[field]), rel_tol=0, abs_tol=1e-9)
               for field in ("distance_km", "duration_hours"))


def _preserve_verified_cost_inputs(old: dict[str, str], new: dict[str, str]) -> None:
    toll_fields = ("toll_status", "toll_cost_eur", "toll_source", "toll_currency", "toll_checked_on",
                   "toll_valid_from", "toll_valid_through")
    if old.get("toll_status") in {"verificado_con_peaje", "verificado_sin_peaje"}:
        for field in toll_fields:
            new[field] = old[field]
    fuel_fields = ("fuel_consumption_l_per_100km", "fuel_consumption_source", "fuel_price_eur_per_l",
                   "fuel_price_reference", "vehicle_configuration")
    if old.get("fuel_consumption_l_per_100km") and old.get("fuel_price_eur_per_l"):
        for field in fuel_fields:
            new[field] = old[field]


def _safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def _row_to_alternative(row: dict[str, str]) -> RouteAlternative:
    values: dict = dict(row)
    for field in ("toll_cost_eur", "fuel_consumption_l_per_100km", "fuel_price_eur_per_l"):
        values[field] = float(values[field]) if values.get(field, "") else None
    for field in ("distance_km", "duration_hours"):
        values[field] = float(values[field])
    for field in ("network_data_version", "toll_source", "toll_checked_on", "toll_valid_from",
                  "toll_valid_through", "fuel_consumption_source", "fuel_price_reference",
                  "vehicle_configuration"):
        values[field] = values.get(field) or None
    for field in ("routing_parameters", "road_references", "geometry_lon_lat", "limitations"):
        values[field] = tuple(tuple(x) if field in {"routing_parameters", "geometry_lon_lat"} else x
                              for x in json.loads(values[field])) if values.get(field) else None
        if field == "geometry_lon_lat" and values[field] is None:
            continue
        if values[field] is None:
            values[field] = ()
    return RouteAlternative(**{field: values[field] for field in _csv_fields()})


def _write_csv_atomic(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
