"""Genera manifiestos locales para completar datos económicos del TSP.

El comando es estrictamente offline: inspecciona snapshots, catálogo, matriz,
diagnósticos y tarifas ya guardadas; nunca contacta proveedores.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from experiments.plan_tsp_direction_queue import plan_enriched_queue
from src.tsp.cities import load_city_catalog
from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.store import RouteStore


ROOT = Path("data/processed/tolls/acquisition_plan")
DEFAULT_QUARANTINE = Path("data/processed/tolls/prioritized_queue/quarantine_pairs.json")
EXTRA_INFO = "tollways,waycategory"
TARIFF_URLS = {
    "C-32": "https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/peatges-tarifes-descomptes/tarifes-peatges/index.html",
    "A-15": "https://www7.gipuzkoa.net/presupuestos/2026/Ppto2026/pdfs/0/Disposiciones.pdf",
    "AP-15": "https://www.audenasa.es/storage/Tarifas-2026-Recorrido.pdf",
}
TOLL_COLUMNS = [
    "route_id", "origin_id", "destination_id", "road_reference",
    "toll_segment_start_lon", "toll_segment_start_lat",
    "toll_segment_end_lon", "toll_segment_end_lat", "toll_length_km",
    "entry_station_candidate", "exit_station_candidate", "operator",
    "official_tariff_url", "official_tariff_year", "missing_field",
    "recommended_lookup", "confidence", "status", "known_exploratory_amount_eur",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, columns: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_diagnostics(root: Path) -> dict[tuple[str, str], list[dict]]:
    by_pair: dict[tuple[str, str], list[dict]] = {}
    if not root.exists():
        return by_pair
    for path in root.rglob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        origin, destination = record.get("origin_id"), record.get("destination_id")
        if origin and destination and record.get("category"):
            by_pair.setdefault((origin, destination), []).append({**record, "_path": str(path)})
    for records in by_pair.values():
        records.sort(key=lambda row: str(row.get("failed_at", "")))
    return by_pair


def persistence_recovery_rows(root: Path, raw_root: Path) -> list[dict]:
    """List HTTP 200 persistence failures and whether a saved raw response exists."""
    rows = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("category") != "persistence_error":
            continue
        request_id = str(record.get("request_id", ""))
        raw_path_value = record.get("raw_response_file")
        raw_path = Path(raw_path_value) if raw_path_value else None
        if raw_path is not None and not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in request_id)
        candidates = ([raw_path] if raw_path and raw_path.is_file()
                      else list(raw_root.glob(f"{safe_id}_*.json")))
        raw_available = False
        for candidate in candidates:
            try:
                saved = json.loads(candidate.read_text(encoding="utf-8"))
                if saved.get("request_id") == request_id and isinstance(saved.get("response"), dict):
                    raw_path, raw_available = candidate, True
                    break
            except (OSError, json.JSONDecodeError):
                continue
        http_status = record.get("http_status_code")
        rows.append({
            "origin_id": record.get("origin_id", ""),
            "destination_id": record.get("destination_id", ""),
            "request_id": request_id,
            "http_status_code": http_status if http_status is not None else "",
            "response_received": "true" if http_status is not None and 200 <= int(http_status) < 300 else "false",
            "persistence_exception_type": record.get("persistence_exception_type", ""),
            "persistence_message": record.get("persistence_message", record.get("message", "")),
            "persistence_operation": record.get("persistence_operation", ""),
            "persistence_stage": record.get("persistence_stage", record.get("stage", "")),
            "persistence_resource": record.get("persistence_resource", ""),
            "raw_response_file": str(raw_path) if raw_path else "",
            "raw_response_available": "true" if raw_available else "false",
            "offline_recovery_possible": "true" if raw_available else "false",
            "recovery_action": "recover_offline_before_download" if raw_available
            else "redownload_only_after_storage_fix",
            "diagnostic_file": str(path),
        })
    return rows


def load_priority_order(path: Path) -> dict[tuple[str, str], int]:
    return {(row["origin_id"], row["destination_id"]): i
            for i, row in enumerate(read_csv(path))}


def validate_pending_rows(pending: list[dict], quarantined: set[tuple[str, str]],
                          batch_size: int) -> None:
    pairs = [(row["origin_id"], row["destination_id"]) for row in pending]
    if len(pairs) != len(set(pairs)) or any(origin == destination for origin, destination in pairs):
        raise ValueError("la cola contiene pares duplicados o diagonales")
    if set(pairs) & quarantined:
        raise ValueError("la cola general contiene pares en cuarentena")
    if not pending:
        return
    if not 0 < batch_size or batch_size > len(pending):
        raise ValueError("tamaño de lote inválido para la cola disponible")
    for row in pending:
        for key, low, high in (("origin_lon", -180.0, 180.0), ("destination_lon", -180.0, 180.0),
                               ("origin_lat", -90.0, 90.0), ("destination_lat", -90.0, 90.0)):
            value = float(row[key])
            if not low <= value <= high:
                raise ValueError(f"coordenada inválida {key}={value}")
        if row["profile"] != "driving-car" or row["strategy"] != "fastest" \
                or row["extra_info"] != EXTRA_INFO:
            raise ValueError("parámetros inesperados en la cola nacional")


def make_pending_manifest(output_dir: Path, quarantine_path: Path) -> tuple[list[dict], list[dict]]:
    dataset_dir = Path("data/datasets/spain_tsp_2026")
    dataset = load_published_dataset(dataset_dir)
    cities = {city.city_id: city for city in load_city_catalog()}
    order = tuple(dataset["city_order"])
    if set(cities) != set(order):
        raise ValueError("el catálogo IGN y el dataset no contienen los mismos IDs")
    matrix = dataset["distance_km"]
    duration = dataset["duration_hours"]
    if matrix.shape != (47, 47) or duration.shape != (47, 47):
        raise ValueError("el dataset nacional no tiene matrices 47x47")

    pending = plan_enriched_queue(
        dataset_dir,
        Path("data/processed/routes/enriched"),
        Path("data/raw/routes/enriched"),
        extra_info=("tollways", "waycategory"),
        endpoint="https://api.heigit.org/openrouteservice/v2/directions",
    )
    quarantine_data = json.loads(quarantine_path.read_text(encoding="utf-8")) \
        if quarantine_path.exists() else {"pairs": []}
    all_quarantine = {(row["origin_id"], row["destination_id"]): row
                      for row in quarantine_data.get("pairs", [])}
    quarantine = {pair: row for pair, row in all_quarantine.items()
                  if row.get("reason") != "persistence_error"}
    storage_recovery = persistence_recovery_rows(
        Path("data/processed/routes/enriched/diagnostics"),
        Path("data/raw/routes/enriched"),
    )
    priority = load_priority_order(Path("data/processed/tolls/prioritized_queue/directions_priority.csv"))
    pending = [row for row in pending
               if (row["origin_id"], row["destination_id"]) not in quarantine]
    pending.sort(key=lambda row: (
        priority.get((row["origin_id"], row["destination_id"]), 10**9),
        -float(row["duration_hours_matrix"]), row["origin_id"], row["destination_id"],
    ))

    base_routes = RouteStore(Path("data/processed/routes")).load_alternatives()
    base_geometry_pairs = {(r.origin_id, r.destination_id) for r in base_routes
                           if r.alternative_id == r.fastest_route_id and r.geometry_lon_lat}
    diagnostics = load_diagnostics(Path("data/processed/routes/enriched/diagnostics"))
    persistence_pairs = {(row["origin_id"], row["destination_id"])
                         for row in storage_recovery}
    city_rows = []
    for row in pending:
        origin_id, destination_id = row["origin_id"], row["destination_id"]
        origin, destination = cities[origin_id], cities[destination_id]
        errors = diagnostics.get((origin_id, destination_id), [])
        last_error = errors[-1] if errors else {}
        persistence_retry = (origin_id, destination_id) in persistence_pairs
        city_rows.append({
            "priority": len(city_rows) + 1,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "origin_name": origin.name,
            "destination_name": destination.name,
            "origin_lon": origin.longitude,
            "origin_lat": origin.latitude,
            "destination_lon": destination.longitude,
            "destination_lat": destination.latitude,
            "profile": "driving-car",
            "strategy": "fastest",
            "extra_info": EXTRA_INFO,
            "acquisition_status": "PENDING_STORAGE_RETRY" if persistence_retry else "PENDING",
            "existing_snapshot": "fastest_geometry_without_required_extras"
            if (origin_id, destination_id) in base_geometry_pairs else "none",
            "last_error": last_error.get("category", ""),
            "request_required": "true",
        })

    validate_pending_rows(city_rows, set(quarantine), min(100, len(city_rows)))

    quarantine_rows = []
    for pair, quarantine_entry in sorted(quarantine.items()):
        origin_id, destination_id = pair
        origin, destination = cities[origin_id], cities[destination_id]
        attempts = diagnostics.get(pair, [])
        last = attempts[-1] if attempts else {}
        quarantine_rows.append({
            "origin_id": origin_id, "destination_id": destination_id,
            "origin_name": origin.name, "destination_name": destination.name,
            "origin_lon": origin.longitude, "origin_lat": origin.latitude,
            "destination_lon": destination.longitude, "destination_lat": destination.latitude,
            "failed_attempts": len(attempts),
            "last_http_status": last.get("http_status_code", quarantine_entry.get("http_status_code", "")),
            "http_status_history": ";".join(str(row.get("http_status_code")) for row in attempts
                                             if row.get("http_status_code") is not None),
            "error_type": last.get("category", quarantine_entry.get("reason", "unknown")),
            "last_attempt_at": last.get("failed_at", quarantine_entry.get("failed_at", "")),
            "timeout_seconds": last.get("timeout_seconds", ""),
            "previous_geometry": "yes" if (origin_id, destination_id) in base_geometry_pairs else "no",
            "matrix_value_available": "yes",
            "recovery_status": "QUARANTINED_MANUAL_REVIEW",
            "recommended_request": "diagnosticar conectividad/cuota; después reintentar solo este par explícitamente con max-http=1 y retries=0",
            "diagnostic_file": last.get("_path", quarantine_entry.get("diagnostic_file", "")),
        })

    pending_columns = ["priority", "origin_id", "destination_id", "origin_name", "destination_name",
                       "origin_lon", "origin_lat", "destination_lon", "destination_lat", "profile",
                       "strategy", "extra_info", "acquisition_status", "existing_snapshot",
                       "last_error", "request_required"]
    quarantine_columns = ["origin_id", "destination_id", "origin_name", "destination_name",
                          "origin_lon", "origin_lat", "destination_lon", "destination_lat",
                          "failed_attempts", "last_http_status", "error_type", "last_attempt_at",
                          "http_status_history",
                          "timeout_seconds", "previous_geometry", "matrix_value_available",
                          "recovery_status", "recommended_request", "diagnostic_file"]
    storage_recovery_columns = ["origin_id", "destination_id", "request_id", "http_status_code",
                                "response_received", "persistence_exception_type", "persistence_message",
                                "persistence_operation", "persistence_stage", "persistence_resource",
                                "raw_response_file", "raw_response_available",
                                "offline_recovery_possible", "recovery_action", "diagnostic_file"]
    write_csv(output_dir / "ors_fastest_pending.csv", pending_columns, city_rows)
    write_csv(output_dir / "ors_quarantine.csv", quarantine_columns, quarantine_rows)
    write_csv(output_dir / "persistence_recovery.csv", storage_recovery_columns, storage_recovery)
    write_csv(output_dir / "batch_001.csv", pending_columns, city_rows[:100])
    return city_rows, quarantine_rows


def make_tariff_manifest(output_dir: Path) -> list[dict]:
    analyzed_path = Path("data/processed/tolls/ors_extra_info/enriched_routes.json")
    analyzed = json.loads(analyzed_path.read_text(encoding="utf-8"))
    exploratory_rows = read_csv(Path("data/processed/tolls/exploratory/exploratory_route_costs.csv"))
    status_by_pair = {(r["origin_id"], r["destination_id"]): r["toll_status"]
                      for r in exploratory_rows}
    rows = []
    for route in analyzed.get("routes", []):
        pair = (route["origin_id"], route["destination_id"])
        route_status = status_by_pair.get(pair, "UNKNOWN_TARIFF")
        if int(route.get("toll_segment_count") or 0) <= 0:
            continue
        for section in route.get("toll_sections", []):
            refs = section.get("instruction_names", [])
            road_reference = "; ".join(refs) or "no identificado en instrucciones"
            joined = " ".join(refs).upper()
            if "C-32" in joined or "C32" in joined or "CUBELLES" in joined:
                url = TARIFF_URLS["C-32"]
                operator = "Generalitat de Catalunya"
                missing = "barrera/acceso exacto; entrada-salida; categoría 2 aplicable; otros cargos del recorrido"
                lookup = "asociar coordenadas del tramo a barreras C-32 y comprobar el par del tarifario 2026; revisión de vía completa"
            elif "AP-15" in joined or "A-15" in joined:
                url = TARIFF_URLS["AP-15"] if "AP-15" in joined else TARIFF_URLS["A-15"]
                operator = "Audenasa/Navarra; Diputación Foral de Gipuzkoa según tramo"
                missing = "límite A-15/AP-15; entrada-salida AP-15; confirmar ámbito de cobro ligero; cobertura total"
                lookup = "separar A-15 (canon foral de pesados) de AP-15; localizar estaciones de entrada/salida y cotejar tarifa ligera por par"
            else:
                url, operator = "", ""
                missing = "identificar corredor, estaciones, regla para turismo y tarifa oficial"
                lookup = "identificar carretera con cartografía oficial/OSM y luego consultar la tabla oficial del operador"
            if route_status == "OFFICIAL_ROUTE_PAIR_INFERENCE":
                status = "EXPLORATORY_OFFICIAL_PAIR_NEEDS_STATION_MATCH"
                missing = "confirmar estaciones exactas del par nominal, sentido y cobertura de peajes adicionales"
                lookup = "contrastar estaciones terminales de la geometría con matriz AP-68 2026; validar sentido y ruta completa"
                if "AP-68" in joined:
                    url, operator = ("https://www.autopistas.com/wp-content/uploads/2025/12/26_003-Avasa-AP68-Bilbao_Zaragoza-T26.pdf",
                                     "AVASA/Autopistas")
            elif route_status == "OFFICIAL_TARIFF_COMPOSITION_INFERENCE":
                status = "EXPLORATORY_OFFICIAL_COMPONENTS_NEED_STATION_MATCH"
                missing = "estaciones AP-9 de entrada y salida; sentido; confirmar que la composición cubre todo el recorrido tarifado"
                lookup = "mapear puntos de acceso AP-9 y cotejar cada tramo con la matriz AUDASA 2026; revisar cobros adicionales"
                url, operator = ("https://www.audasa.es/wp-content/uploads/pdf/tarifas/2026/Tarifas-20260101.pdf",
                                 "AUDASA")
            else:
                status = "UNKNOWN_TARIFF_NO_STATION_PAIR"
            start, end = section.get("start_lon_lat", [None, None]), section.get("end_lon_lat", [None, None])
            rows.append({
                "route_id": route.get("route_id"), "origin_id": pair[0], "destination_id": pair[1],
                "road_reference": road_reference,
                "toll_segment_start_lon": start[0] if len(start) > 0 else "",
                "toll_segment_start_lat": start[1] if len(start) > 1 else "",
                "toll_segment_end_lon": end[0] if len(end) > 0 else "",
                "toll_segment_end_lat": end[1] if len(end) > 1 else "",
                "toll_length_km": section.get("length_km_approx", ""),
                "entry_station_candidate": "", "exit_station_candidate": "",
                "operator": operator, "official_tariff_url": url, "official_tariff_year": "2026",
                "missing_field": missing, "recommended_lookup": lookup,
                "confidence": "medium_corridor_low_station_pair",
                "status": status,
                "known_exploratory_amount_eur": next((r.get("toll_eur_exploratory")
                    for r in exploratory_rows if (r["origin_id"], r["destination_id"]) == pair), ""),
            })
    write_csv(output_dir / "missing_official_tolls.csv", TOLL_COLUMNS, rows)
    return rows


def render_overpass_query(points: list[tuple[float, float]], radius_m: int = 1200) -> str:
    if radius_m < 100 or not points:
        raise ValueError("se requiere radio >=100 m y al menos un punto")
    selectors = []
    for lon, lat in points:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("coordenada inválida para consulta Overpass")
        center = f"{lat:.6f},{lon:.6f}"
        selectors.extend([
            f'node(around:{radius_m},{center})["barrier"="toll_booth"];',
            f'node(around:{radius_m},{center})["highway"="toll_gantry"];',
            f'nwr(around:{radius_m},{center})["toll"="yes"];',
        ])
    return "[out:json][timeout:30];\n(\n  " + "\n  ".join(selectors) + "\n);\nout center tags geom;\n"


def make_overpass_queries(output_dir: Path, tariff_rows: list[dict], radius_m: int = 1200) -> list[str]:
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    analyzed = json.loads(Path("data/processed/tolls/ors_extra_info/enriched_routes.json").read_text(encoding="utf-8"))
    # AP-68 ya tiene estaciones OSM locales candidatas; las consultas se reservan
    # para AP-9, C-32 y A-15/AP-15, donde aún falta inventario espacial útil.
    wanted = {(row["origin_id"], row["destination_id"]) for row in tariff_rows
              if row["status"] in {"UNKNOWN_TARIFF_NO_STATION_PAIR",
                                   "EXPLORATORY_OFFICIAL_COMPONENTS_NEED_STATION_MATCH"}}
    for route in analyzed.get("routes", []):
        pair = route["origin_id"], route["destination_id"]
        if pair not in wanted:
            continue
        for section in route.get("toll_sections", []):
            coords = section.get("geometry_coordinates", [])
            if not coords:
                continue
            lon, lat = coords[len(coords) // 2][:2]
            points = groups.setdefault(pair, [])
            if all(abs(lon - x) > 0.0001 or abs(lat - y) > 0.0001 for x, y in points):
                points.append((lon, lat))
    outputs = []
    for (origin, destination), points in groups.items():
        query = render_overpass_query(points, radius_m)
        filename = f"overpass_{origin}_{destination}.ql"
        (output_dir / filename).write_text(query, encoding="utf-8")
        outputs.append(filename)
    return outputs


def make_avoid_tolls_manifest(output_dir: Path) -> list[dict]:
    routes = read_csv(Path("data/processed/tolls/exploratory/exploratory_route_costs.csv"))
    alternatives = read_csv(Path("data/processed/routes/route_alternatives.csv"))
    existing = set()
    for row in alternatives:
        try:
            params = json.loads(row.get("routing_parameters") or "[]")
        except json.JSONDecodeError:
            continue
        if any(key == "strategy" and value == "avoid_tolls" for key, value in params):
            existing.add((row["origin_id"], row["destination_id"]))
    rows = []
    priority_by_status = {
        "OFFICIAL_ROUTE_PAIR_INFERENCE": (1, "tarifa oficial nominal; comparar opción sin peaje"),
        "OFFICIAL_TARIFF_COMPOSITION_INFERENCE": (2, "composición AP-9 oficial provisional; comparar opción sin peaje"),
        "UNKNOWN_TARIFF": (3, "tollways detectado y coste sin resolver; alternativa informa el compromiso tiempo-distancia"),
    }
    for route in routes:
        if int(float(route.get("toll_segment_count") or 0)) <= 0:
            continue
        priority, reason = priority_by_status.get(route["toll_status"], (4, "tramo tollways pendiente de valorar"))
        pair = route["origin_id"], route["destination_id"]
        rows.append({
            "origin_id": pair[0], "destination_id": pair[1], "priority": priority,
            "reason": reason,
            "existing_avoid_tolls_geometry": "yes_unclassified" if pair in existing else "no",
            "status": "ENRICHED_AVOID_TOLLS_NEEDED",
            "request_required": "true",
            "extra_info": EXTRA_INFO,
        })
    rows.sort(key=lambda row: (row["priority"], row["origin_id"], row["destination_id"]))
    write_csv(output_dir / "avoid_tolls_pending.csv",
              ["origin_id", "destination_id", "priority", "reason",
               "existing_avoid_tolls_geometry", "status", "request_required", "extra_info"], rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--quarantine-file", type=Path, default=DEFAULT_QUARANTINE)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--overpass-radius-m", type=int, default=1200)
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.overpass_radius_m < 100:
        parser.error("batch-size debe ser positivo y el radio Overpass >=100 m")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pending, quarantine = make_pending_manifest(args.output_dir, args.quarantine_file)
    storage_recovery = persistence_recovery_rows(
        Path("data/processed/routes/enriched/diagnostics"),
        Path("data/raw/routes/enriched"),
    )
    tariffs = make_tariff_manifest(args.output_dir)
    overpass_files = make_overpass_queries(args.output_dir, tariffs, args.overpass_radius_m)
    alternatives = make_avoid_tolls_manifest(args.output_dir)
    write_csv(args.output_dir / "batch_001.csv",
              list(pending[0]) if pending else ["priority", "origin_id", "destination_id"],
              pending[:args.batch_size])
    summary = {
        "http_requests": 0, "directed_arcs": 2162,
        "available_pending": len(pending), "quarantined": len(quarantine),
        "persistence_recovery_records": len(storage_recovery),
        "batch_001_rows": min(args.batch_size, len(pending)),
        "unique_pending_pairs": len({(r["origin_id"], r["destination_id"]) for r in pending}),
        "missing_tariff_segments": len(tariffs), "avoid_tolls_requests_recommended": len(alternatives),
        "overpass_queries_prepared_not_executed": len(overpass_files),
        "overpass_query_files": overpass_files,
        "profile": "driving-car", "strategy": "fastest", "extra_info": EXTRA_INFO,
        "endpoint": "https://api.heigit.org/openrouteservice/v2/directions",
        "pending_csv": str(args.output_dir / "ors_fastest_pending.csv"),
        "batch_csv": str(args.output_dir / "batch_001.csv"),
        "quarantine_csv": str(args.output_dir / "ors_quarantine.csv"),
        "persistence_recovery_csv": str(args.output_dir / "persistence_recovery.csv"),
    }
    (args.output_dir / "acquisition_plan_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
