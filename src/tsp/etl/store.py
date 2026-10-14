"""Almacén local de alternativas y respuestas crudas, con escritura atómica."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Iterable

from ..alternatives import RouteAlternative


class PersistenceError(OSError):
    """Write failure with safe operation context and recoverability details."""

    def __init__(self, operation: str, resource: Path, stage: str,
                 cause: BaseException, *, raw_response_file: Path | None = None) -> None:
        self.operation = operation
        self.resource = str(resource)
        self.stage = stage
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause)
        self.raw_response_file = str(raw_response_file) if raw_response_file else None
        self.raw_response_available = bool(raw_response_file and raw_response_file.is_file())
        super().__init__(f"{operation} falló para {resource.name} ({self.cause_type}): "
                         f"{self.cause_message}")


class RouteStore:
    """Mantiene catálogo CSV, estados de solicitudes y JSON crudo sin credenciales."""

    def __init__(self, root: str | Path, *, raw_dir: str | Path | None = None,
                 matrix_dir: str | Path | None = None) -> None:
        self.root = Path(root)
        self.raw_dir = Path(raw_dir) if raw_dir is not None else self.root / "raw"
        self.matrix_dir = Path(matrix_dir) if matrix_dir is not None else self.root
        self.catalog_path = self.root / "route_alternatives.csv"
        self.state_path = self.root / "acquisition_state.json"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.matrix_dir.mkdir(parents=True, exist_ok=True)
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

    def count_http_requests_on(self, day: str, request_prefix: str = "") -> int:
        """Count persisted HTTP attempts for a UTC day and provider namespace.

        Successful snapshots retain the attempt count in their raw response
        metadata. Failed attempts are append-only diagnostic records. Legacy
        successful state entries without raw metadata conservatively count as
        one request; failed state entries are only a fallback when their
        diagnostic file is unavailable, preventing a diagnostic from being
        counted twice.
        """
        state = self._state()
        total = 0
        for request_id, entry in state.get("requests", {}).items():
            if not request_id.startswith(request_prefix):
                continue
            if entry.get("status") != "adquirida" or entry.get("acquired_on") != day:
                continue
            attempts = None
            raw_value = entry.get("raw_file")
            if raw_value:
                raw_path = Path(raw_value)
                if not raw_path.is_absolute() and not raw_path.exists():
                    rooted_path = self.root / raw_path
                    if rooted_path.exists():
                        raw_path = rooted_path
                if not raw_path.is_file():
                    raise ValueError(
                        f"historial incompleto: falta la respuesta cruda de {request_id}"
                    )
                try:
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    recorded_attempts = raw.get("request", {}).get("acquisition", {}).get("http_requests")
                    attempts = int(recorded_attempts) if recorded_attempts is not None else None
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    if isinstance(exc, ValueError) and str(exc).startswith("historial incompleto:"):
                        raise
                    raise ValueError(
                        f"historial incompleto: no se puede contar la respuesta de {request_id}"
                    ) from exc
                # Older snapshots without attempt metadata count as one HTTP
                # request, the conservative minimum for a successful route.
            total += max(1, attempts) if attempts is not None else 1

        diagnosed_request_ids: set[str] = set()
        diagnostics_dir = self.root / "diagnostics"
        if diagnostics_dir.is_dir():
            for diagnostic_path in diagnostics_dir.glob("*.json"):
                try:
                    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    request_id = str(diagnostic.get("request_id", ""))
                    if (request_id.startswith(request_prefix)
                            and str(diagnostic.get("failed_at", "")).startswith(day)):
                        total += max(0, int(diagnostic.get("http_requests", 0)))
                        diagnosed_request_ids.add(request_id)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"historial incompleto: no se puede leer el diagnóstico {diagnostic_path.name}"
                    ) from exc

        for request_id, entry in state.get("requests", {}).items():
            if (request_id.startswith(request_prefix) and entry.get("status") == "error"
                    and str(entry.get("failed_at", "")).startswith(day)
                    and request_id not in diagnosed_request_ids):
                try:
                    total += max(0, int(entry.get("http_requests", 0)))
                except (TypeError, ValueError):
                    continue
        return total

    def count_http_requests_since(self, since: datetime, request_prefix: str = "") -> int:
        """Count persisted attempts since a UTC instant, including failures.

        HeiGIT's public daily quota is a rolling 24-hour window, not a UTC
        calendar day. Success timestamps come from raw snapshots; failed
        attempts come from append-only diagnostics. Legacy success entries
        without timestamps are included conservatively when their stored date
        could overlap the requested window.
        """
        if since.tzinfo is None:
            raise ValueError("since debe incluir zona horaria")
        since = since.astimezone(timezone.utc)
        state = self._state()
        total = 0
        for request_id, entry in state.get("requests", {}).items():
            if (not request_id.startswith(request_prefix)
                    or entry.get("status") != "adquirida"):
                continue
            attempts = 1
            acquired_at = None
            raw_value = entry.get("raw_file")
            if raw_value:
                raw_path = Path(raw_value)
                if not raw_path.is_absolute() and not raw_path.exists():
                    rooted_path = self.root / raw_path
                    if rooted_path.exists():
                        raw_path = rooted_path
                if not raw_path.is_file():
                    raise ValueError(
                        f"historial incompleto: falta la respuesta cruda de {request_id}"
                    )
                try:
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    acquisition = raw.get("request", {}).get("acquisition", {})
                    acquired_at = acquisition.get("acquired_at")
                    recorded_attempts = acquisition.get("http_requests")
                    if recorded_attempts is not None:
                        attempts = max(1, int(recorded_attempts))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"historial incompleto: no se puede contar la respuesta de {request_id}"
                    ) from exc
            if acquired_at:
                try:
                    timestamp = datetime.fromisoformat(str(acquired_at).replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        raise ValueError("timestamp sin zona horaria")
                    if timestamp.astimezone(timezone.utc) >= since:
                        total += attempts
                except ValueError as exc:
                    raise ValueError(
                        f"historial incompleto: fecha inválida en respuesta de {request_id}"
                    ) from exc
            else:
                acquired_on = entry.get("acquired_on")
                if acquired_on and str(acquired_on) >= since.date().isoformat():
                    total += attempts

        diagnosed_request_ids: set[str] = set()
        diagnostics_dir = self.root / "diagnostics"
        if diagnostics_dir.is_dir():
            for diagnostic_path in diagnostics_dir.glob("*.json"):
                try:
                    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    request_id = str(diagnostic.get("request_id", ""))
                    if not request_id.startswith(request_prefix):
                        continue
                    failed_at = datetime.fromisoformat(
                        str(diagnostic.get("failed_at", "")).replace("Z", "+00:00")
                    )
                    if failed_at.tzinfo is None:
                        raise ValueError("timestamp sin zona horaria")
                    diagnosed_request_ids.add(request_id)
                    if failed_at.astimezone(timezone.utc) >= since:
                        total += max(0, int(diagnostic.get("http_requests", 0)))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"historial incompleto: no se puede leer el diagnóstico {diagnostic_path.name}"
                    ) from exc

        for request_id, entry in state.get("requests", {}).items():
            if not (request_id.startswith(request_prefix)
                    and entry.get("status") == "error"
                    and request_id not in diagnosed_request_ids):
                continue
            failed_at = entry.get("failed_at")
            if not failed_at:
                continue
            try:
                timestamp = datetime.fromisoformat(str(failed_at).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("timestamp sin zona horaria")
                if timestamp.astimezone(timezone.utc) >= since:
                    total += max(0, int(entry.get("http_requests", 0)))
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"historial incompleto: fecha inválida en error de {request_id}"
                ) from exc
        return total

    def save_success(
        self, request_id: str, safe_request: dict, response: dict,
        alternatives: Iterable[RouteAlternative],
    ) -> None:
        alternatives = tuple(alternatives)
        if not alternatives:
            raise ValueError("no se puede persistir una solicitud sin rutas válidas")
        response_digest = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        raw_record = {
            "schema_version": 1,
            "request_id": request_id,
            "request": safe_request,
            "response": response,
            "response_sha256": response_digest,
            "attribution": "© openrouteservice by HeiGIT | Data © OpenStreetMap contributors",
            "results_license": "CC-BY-SA 4.0 según respuesta HeiGIT del 2026-10-12; confirmar términos vigentes de la cuenta",
        }
        raw_path = self.raw_dir / f"{_safe_filename(request_id)}_{response_digest}.json"
        try:
            raw_text = json.dumps(raw_record, ensure_ascii=False, indent=2) + "\n"
            if raw_path.exists():
                existing = json.loads(raw_path.read_text(encoding="utf-8"))
                if existing.get("request_id") != request_id or existing.get("response_sha256") != response_digest:
                    raise ValueError("el archivo crudo existente no coincide con la solicitud o su hash")
            else:
                _write_text_atomic(raw_path, raw_text)
        except Exception as exc:
            if isinstance(exc, PersistenceError):
                raise
            raise PersistenceError("write_raw_response", raw_path, "raw_response_write", exc) from exc

        # Guardar primero la respuesta inmutable permite reconstruir el índice si
        # una escritura posterior falla (especialmente importante en Windows).
        try:
            rows = self._read_catalog()
        except Exception as exc:
            raise PersistenceError("read_route_index", self.catalog_path, "index_read", exc,
                                   raw_response_file=raw_path) from exc
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
            archive_path = archive_dir / f"{_safe_filename(request_id)}_{archive_id}.csv"
            try:
                _write_csv_atomic(archive_path, archived, ["request_id", *_csv_fields()])
            except Exception as exc:
                raise PersistenceError("archive_route_index", archive_path, "index_history_write", exc,
                                       raw_response_file=raw_path) from exc
        try:
            _write_csv_atomic(self.catalog_path, [*current, *incoming], ["request_id", *_csv_fields()])
        except Exception as exc:
            raise PersistenceError("update_route_index", self.catalog_path, "index_write", exc,
                                   raw_response_file=raw_path) from exc
        try:
            state = self._state()
        except Exception as exc:
            raise PersistenceError("read_acquisition_state", self.state_path, "state_read", exc,
                                   raw_response_file=raw_path) from exc
        state["requests"][request_id] = {
            "status": "adquirida", "alternative_count": len(alternatives),
            "acquired_on": datetime.now(timezone.utc).date().isoformat(),
            "raw_file": str(raw_path),
            "active_alternative_ids": [route.alternative_id for route in alternatives],
        }
        try:
            self._write_state(state)
        except Exception as exc:
            raise PersistenceError("update_acquisition_state", self.state_path, "state_write", exc,
                                   raw_response_file=raw_path) from exc

    def save_failure(
        self, request_id: str, error_type: str, *, http_requests: int = 0,
        http_status_codes: Iterable[int] = (),
        diagnostic: dict | None = None,
    ) -> str:
        failed_at = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        diagnostic_path = self.root / "diagnostics" / f"{_safe_filename(request_id)}_{stamp}.json"
        record = {"schema_version": 1, "request_id": request_id, "error_type": error_type,
                  "http_requests": http_requests, "http_status_codes": list(http_status_codes),
                  "failed_at": failed_at, **(diagnostic or {})}
        _write_text_atomic(diagnostic_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        state = self._state()
        state["requests"][request_id] = {
            "status": "error", "error_type": error_type,
            "http_requests": http_requests, "http_status_codes": list(http_status_codes),
            "failed_at": failed_at, "diagnostic_file": str(diagnostic_path.relative_to(self.root)),
            "diagnostic_category": (diagnostic or {}).get("category"),
            "diagnostic_stage": (diagnostic or {}).get("stage"),
        }
        self._write_state(state)
        return str(diagnostic_path)

    def save_matrix_snapshot(
        self, request_id: str, safe_request: dict, response: dict,
        normalized: dict, city_order: list[str],
    ) -> None:
        """Persiste respuesta Matrix y matrices numéricas locales etiquetadas."""
        size = len(city_order)
        if size < 2 or len(set(city_order)) != size:
            raise ValueError("el orden de ciudades del snapshot debe ser único y contener al menos dos ids")
        if set(normalized) != {"distance_km", "time_hours"}:
            raise ValueError("snapshot Matrix requiere distancia y tiempo normalizados")
        for metric, matrix in normalized.items():
            if (len(matrix) != size or any(len(row) != size for row in matrix)):
                raise ValueError("snapshot Matrix requiere matrices cuadradas km/h con orden canónico")
            try:
                valid_values = all(math.isfinite(float(value)) and float(value) >= 0
                                   for row in matrix for value in row)
                valid_diagonal = all(float(matrix[i][i]) == 0.0 for i in range(size))
            except (TypeError, ValueError, IndexError):
                valid_values, valid_diagonal = False, False
            if not valid_values or not valid_diagonal:
                raise ValueError("snapshot Matrix contiene celdas no finitas/negativas o diagonal distinta de cero")
        paths = {}
        response_digest = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshots_dir = self.matrix_dir / "ors_snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        for metric, matrix in normalized.items():
            path = snapshots_dir / f"{metric}_{_safe_filename(request_id)}_{response_digest[:16]}.csv"
            _write_csv_atomic(path, [
                {"city_id": city_id, **{other_id: ("" if matrix[i][j] is None else str(matrix[i][j]))
                                       for j, other_id in enumerate(city_order)}}
                for i, city_id in enumerate(city_order)
            ], ["city_id", *city_order])
            paths[metric] = str(path.relative_to(self.matrix_dir))
        acquired_at = datetime.now(timezone.utc).isoformat()
        raw_record = {"schema_version": 1, "request_id": request_id,
                      "request": safe_request, "response": response,
                      "city_order": city_order, "normalized_matrix_files": paths,
                      "acquired_at": acquired_at, "response_sha256": response_digest,
                      "provider": "openrouteservice",
                      "attribution": "© openrouteservice by HeiGIT | Data from OpenStreetMap",
                      "results_license": "CC-BY-SA 4.0 según respuesta HeiGIT del 2026-10-12; confirmar términos vigentes de la cuenta"}
        raw_path = self.raw_dir / f"{_safe_filename(request_id)}_{response_digest}.json"
        _write_text_atomic(raw_path, json.dumps(raw_record, ensure_ascii=False, indent=2) + "\n")
        state = self._state()
        state["requests"][request_id] = {
            "status": "adquirida", "kind": "matrix", "city_count": size,
            "acquired_on": acquired_at[:10], "acquired_at": acquired_at,
            "response_sha256": response_digest,
            "raw_file": str(raw_path), "normalized_matrix_files": paths,
            "matrix_directory": str(self.matrix_dir), "city_order": city_order,
        }
        self._write_state(state)

    def load_alternatives(self) -> tuple[RouteAlternative, ...]:
        return tuple(_row_to_alternative(row) for row in self._read_catalog())

    def _read_catalog(self) -> list[dict[str, str]]:
        if not self.catalog_path.exists():
            return []
        _raise_csv_field_limit()
        with self.catalog_path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def recover_unindexed_raw_snapshots(self) -> dict[str, int]:
        """Rebuild route-index/state entries from self-describing saved responses.

        Historical files without route identity metadata are left untouched and
        reported as skipped; this operation never performs network access.
        """
        from .ors import parse_ors_geojson

        recovered = skipped_existing = skipped_legacy = invalid = 0
        for raw_path in sorted(self.raw_dir.glob("*.json")):
            try:
                record = json.loads(raw_path.read_text(encoding="utf-8"))
                request_id = record["request_id"]
                request = record["request"]
                metadata = request.get("acquisition", {})
                origin_id = metadata.get("origin_id")
                destination_id = metadata.get("destination_id")
                profile = metadata.get("profile")
                fastest_route_id = metadata.get("fastest_route_id")
                response = record["response"]
                if not (request_id and origin_id and destination_id and profile and fastest_route_id):
                    skipped_legacy += 1
                    continue
                existing_rows = self._read_catalog()
                if any(row.get("request_id") == request_id for row in existing_rows) \
                        and self.request_succeeded(request_id):
                    skipped_existing += 1
                    continue
                acquired_at = metadata.get("acquired_at")
                routes = parse_ors_geojson(
                    response, origin_id=origin_id, destination_id=destination_id,
                    request_id=request_id.split(":")[-1], fastest_route_id=fastest_route_id,
                    is_primary_fastest=bool(metadata.get("is_primary_fastest")),
                    strategy=metadata.get("strategy", "fastest"), profile=profile,
                    source=request.get("url", ""),
                    acquired_on=(acquired_at[:10] if acquired_at else datetime.now(timezone.utc).date().isoformat()),
                    extra_info=tuple(metadata.get("extra_info", ())),
                )
                self.save_success(request_id, request, response, routes)
                recovered += 1
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                invalid += 1
        return {"recovered": recovered, "skipped_existing": skipped_existing,
                "skipped_legacy": skipped_legacy, "invalid": invalid}

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


def _raise_csv_field_limit() -> None:
    """Raise csv's 128 KiB default, with an int range safe on Windows builds."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10
