"""Analiza offline snapshots Directions enriquecidos sin certificar peajes."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

from src.tsp.etl.ors_extras import analyze_geojson_extras, plan_overpass_way_queries
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_operation import geometry_sha256


EXTRA_NAMES = ("tollways", "osmid", "waycategory")
RESPONSE_KEYS = {"tollways": "tollways", "osmid": "osmId", "waycategory": "waycategory"}


def analyze_saved_routes(enriched_root: Path, raw_root: Path, original_root: Path,
                         skipped_snapshots: list[dict] | None = None) -> list[dict]:
    """Analiza snapshots válidos, clasificando los antiguos o incompletos sin abortar el lote."""
    store = RouteStore(enriched_root, raw_dir=raw_root)
    if not store.catalog_path.exists() or not store.state_path.exists():
        return []
    # El catálogo contiene geometrías serializadas que pueden superar el límite
    # CSV predeterminado de 128 KiB en rutas nacionales largas.
    catalog_rows = store._read_catalog()
    routes = {route.alternative_id: route for route in store.load_alternatives()}
    state = json.loads(store.state_path.read_text(encoding="utf-8"))["requests"]
    originals = {(route.origin_id, route.destination_id): route
                 for route in RouteStore(original_root).load_alternatives()
                 if route.alternative_id == route.fastest_route_id}
    response_cache: dict[str, dict] = {}
    skipped = skipped_snapshots if skipped_snapshots is not None else []
    result = []
    for catalog_row in catalog_rows:
        request_id = catalog_row["request_id"]
        route = routes.get(catalog_row["alternative_id"])
        if route is None:
            skipped.append({"request_id": request_id, "status": "corrupt_snapshot",
                            "reason": "alternativa ausente del catálogo normalizado"})
            continue
        if request_id not in response_cache:
            try:
                entry = state.get(request_id, {})
                if entry.get("status") != "adquirida":
                    response_cache[request_id] = {"skip": {
                        "request_id": request_id, "status": "incomplete_snapshot",
                        "reason": f"estado de adquisición: {entry.get('status', 'ausente')}"}}
                else:
                    raw_path = Path(entry["raw_file"])
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    if raw.get("request_id") != request_id:
                        raise ValueError("respuesta cruda y catálogo no coinciden")
                    safe_request = raw.get("request", {})
                    body = safe_request.get("body", {}) if isinstance(safe_request, dict) else {}
                    requested = tuple(body.get("extra_info", ()))
                    if not requested:
                        response_cache[request_id] = {"skip": {
                            "request_id": request_id, "status": "legacy_snapshot_without_extras",
                            "reason": "la petición original no solicitó extra_info"}}
                    elif len(set(requested)) != len(requested) or set(requested) - set(EXTRA_NAMES):
                        raise ValueError("lista extra_info inválida en metadatos de petición")
                    else:
                        response = raw.get("response")
                        features = response.get("features") if isinstance(response, dict) else None
                        if not isinstance(features, list) or not features:
                            raise ValueError("respuesta cruda sin features GeoJSON")
                        first_props = features[0].get("properties", {})
                        extras = first_props.get("extras", {}) if isinstance(first_props, dict) else {}
                        if extras is None:
                            extras = {}
                        if not isinstance(extras, dict):
                            raise ValueError("extras de respuesta corruptos")
                        present = tuple(name for name in EXTRA_NAMES
                                        if RESPONSE_KEYS[name] in extras
                                        or (name == "osmid" and "osmid" in extras))
                        missing_requested = sorted(set(requested) - set(present))
                        if missing_requested:
                            response_cache[request_id] = {"skip": {
                                "request_id": request_id,
                                "status": "requested_attribute_missing",
                                "reason": "faltan extras solicitados: " + ", ".join(missing_requested)}}
                        else:
                            analyses = analyze_geojson_extras(response, required=requested)
                            # Match RouteStore's response serialization so its
                            # persisted digest can validate the response offline.
                            response_sha256 = sha256(json.dumps(
                                response, sort_keys=True, ensure_ascii=False
                            ).encode("utf-8")).hexdigest()
                            # Historical snapshots kept the 16-hex digest only
                            # in the filename; newer ones also store it in JSON.
                            stored_response_hash = (raw.get("response_sha256")
                                                    or raw_path.stem.rsplit("_", 1)[-1])
                            if stored_response_hash and not response_sha256.startswith(
                                    str(stored_response_hash)):
                                raise ValueError("hash de respuesta cruda no coincide")
                            provider_info = response.get("metadata", response.get("info", {}))
                            warnings = (provider_info.get("warnings", [])
                                        if isinstance(provider_info, dict) else [])
                            response_cache[request_id] = {
                                "analyses": analyses, "raw_path": raw_path,
                                "response_sha256": response_sha256,
                                "response_hash_verified": bool(stored_response_hash),
                                "response_hash_source": ("metadata" if raw.get("response_sha256")
                                                         else "filename_suffix"),
                                "acquired_at": safe_request.get("acquisition", {}).get("acquired_at"),
                                "requested": requested, "present": present,
                                "provider_warnings": warnings,
                            }
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                response_cache[request_id] = {"skip": {
                    "request_id": request_id, "status": "corrupt_snapshot",
                    "reason": str(exc)}}
        snapshot = response_cache[request_id]
        if "skip" in snapshot:
            issue = snapshot["skip"]
            if issue not in skipped:
                skipped.append(issue)
            continue
        analyses = snapshot["analyses"]
        raw_path = snapshot["raw_path"]
        acquired_at = snapshot["acquired_at"]
        requested = snapshot["requested"]
        present = snapshot["present"]
        try:
            feature_index = int(route.alternative_id.rsplit("-", 1)[1])
            analysis = analyses[feature_index]
        except (ValueError, IndexError) as exc:
            skipped.append({"request_id": request_id, "route_id": route.alternative_id,
                            "status": "corrupt_snapshot",
                            "reason": "alternative_id no identifica un feature enriquecido"})
            continue
        if (analysis["geometry_sha256"] != geometry_sha256(route)
                or abs(analysis["distance_km"] - route.distance_km) > 1e-8
                or abs(analysis["duration_hours"] - route.duration_hours) > 1e-8):
            skipped.append({"request_id": request_id, "route_id": route.alternative_id,
                            "status": "corrupt_snapshot",
                            "reason": "snapshot no coincide con geometría/métricas normalizadas"})
            continue
        previous = originals.get((route.origin_id, route.destination_id))
        old_geometry = previous.geometry_lon_lat if previous else ()
        new_geometry = route.geometry_lon_lat or ()
        first_different = next((index for index, (old, new) in
                                enumerate(zip(old_geometry, new_geometry)) if old != new), None)
        if first_different is None and len(old_geometry) != len(new_geometry):
            first_different = min(len(old_geometry), len(new_geometry))
        attribute_status = {
            name: ("solicitado_y_presente" if name in requested and name in present else
                   "solicitado_y_ausente" if name in requested else
                   "no_solicitado_pero_presente" if name in present else "no_solicitado_ausente")
            for name in EXTRA_NAMES
        }
        result.append({"route_id": route.alternative_id, "origin_id": route.origin_id,
                       "destination_id": route.destination_id, "request_id": request_id,
                       "acquired_at": acquired_at, "raw_sha256": sha256(raw_path.read_bytes()).hexdigest(),
                       "response_sha256": snapshot["response_sha256"],
                       "source": route.source, "routing_engine_version": route.routing_engine_version,
                       "extra_info_requested": list(requested), "extra_info_present": list(present),
                       "extra_info_status": attribute_status,
                       "response_hash_verified": snapshot["response_hash_verified"],
                       "response_hash_source": snapshot["response_hash_source"],
                       "provider_warnings": snapshot["provider_warnings"],
                       **analysis,
                       "previous_route_id": previous.alternative_id if previous else None,
                       "previous_geometry_sha256": geometry_sha256(previous) if previous else None,
                       "geometry_equal_to_previous": old_geometry == new_geometry if previous else None,
                       "first_different_coordinate_index": first_different,
                       "distance_difference_km": route.distance_km - previous.distance_km if previous else None,
                       "duration_difference_hours": route.duration_hours - previous.duration_hours if previous else None})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enriched-store", type=Path, default=Path("data/processed/routes/enriched"))
    parser.add_argument("--enriched-raw", type=Path, default=Path("data/raw/routes/enriched"))
    parser.add_argument("--original-store", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--known-osm", type=Path, default=Path("data/processed/tolls/overpass_inventory.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/ors_extra_info"))
    args = parser.parse_args(argv)
    skipped_snapshots: list[dict] = []
    rows = analyze_saved_routes(args.enriched_store, args.enriched_raw, args.original_store,
                                skipped_snapshots)
    known = set()
    if args.known_osm.exists():
        with args.known_osm.open(encoding="utf-8-sig", newline="") as stream:
            known = {int(row["osm_id"]) for row in csv.DictReader(stream)
                     if row["osm_type"] == "way"}
    all_ids = {osm_id for row in rows for osm_id in row["osm_way_ids"]}
    way_plan = plan_overpass_way_queries(all_ids, known_way_ids=known, batch_size=20)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "enriched_routes.json").write_text(
        json.dumps({"schema_version": 2, "routes": rows,
                    "skipped_snapshots": skipped_snapshots,
                    "warning": "Marcas cartográficas; peajes monetarios desconocidos"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "overpass_way_plan.json").write_text(
        json.dumps({"schema_version": 1, "queries": way_plan, "http_requests_executed": 0},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output / "enriched_routes.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ("origin_id", "destination_id", "route_id", "acquired_at", "distance_km",
                  "duration_hours", "geometry_segment_count", "toll_segment_count",
                  "extra_info_requested", "extra_info_present", "extra_info_status",
                  "response_hash_verified",
                  "response_hash_source",
                  "coverage", "toll_distance_km", "toll_sections", "osm_way_ids",
                  "extra_coverage", "toll_distance_summary_km",
                  "waycategory_names", "toll_instruction_names", "toll_instruction_refs",
                  "warnings", "provider_warnings", "geometry_sha256",
                  "response_sha256", "raw_sha256",
                  "previous_geometry_sha256", "geometry_equal_to_previous",
                  "first_different_coordinate_index", "toll_verification")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: json.dumps(row.get(field), ensure_ascii=False)
                          if isinstance(row.get(field), (dict, list)) else row.get(field)
                          for field in fields} | {
                              "toll_instruction_names": json.dumps(sorted({name
                                  for section in row.get("toll_sections", [])
                                  for name in section.get("instruction_names", [])}), ensure_ascii=False),
                              "toll_instruction_refs": json.dumps(sorted({ref
                                  for section in row.get("toll_sections", [])
                                  for ref in section.get("instruction_refs", [])}), ensure_ascii=False),
                          } for row in rows)
    status_counts = {}
    for issue in skipped_snapshots:
        status_counts[issue["status"]] = status_counts.get(issue["status"], 0) + 1
    print(json.dumps({"analyzed_routes": len(rows), "skipped_snapshots": len(skipped_snapshots),
                      "skip_status_counts": status_counts,
                      "unique_osm_way_ids": len(all_ids),
                      "pending_overpass_id_queries": len(way_plan), "http_requests_executed": 0,
                      "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
