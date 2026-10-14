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


REQUIRED = ("tollways", "osmid", "waycategory")


def analyze_saved_routes(enriched_root: Path, raw_root: Path, original_root: Path) -> list[dict]:
    """Une CSV y JSON por request_id y contrasta con la geometría original."""
    store = RouteStore(enriched_root, raw_dir=raw_root)
    if not store.catalog_path.exists() or not store.state_path.exists():
        return []
    with store.catalog_path.open(encoding="utf-8", newline="") as stream:
        catalog_rows = list(csv.DictReader(stream))
    routes = {route.alternative_id: route for route in store.load_alternatives()}
    state = json.loads(store.state_path.read_text(encoding="utf-8"))["requests"]
    originals = {(route.origin_id, route.destination_id): route
                 for route in RouteStore(original_root).load_alternatives()
                 if route.alternative_id == route.fastest_route_id}
    response_cache = {}
    result = []
    for catalog_row in catalog_rows:
        request_id = catalog_row["request_id"]
        route = routes[catalog_row["alternative_id"]]
        if request_id not in response_cache:
            entry = state.get(request_id, {})
            if entry.get("status") != "adquirida":
                raise ValueError(f"estado incompleto para {request_id}")
            raw_path = Path(entry["raw_file"])
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if raw.get("request_id") != request_id:
                raise ValueError("respuesta cruda y catálogo no coinciden")
            requested = tuple(raw.get("request", {}).get("body", {}).get("extra_info", ()))
            if set(requested) != set(REQUIRED):
                raise ValueError("snapshot sin los tres extra_info del piloto")
            analyses = analyze_geojson_extras(raw["response"], required=REQUIRED)
            response_cache[request_id] = (analyses, raw_path,
                                          raw["request"].get("acquisition", {}).get("acquired_at"))
        analyses, raw_path, acquired_at = response_cache[request_id]
        try:
            feature_index = int(route.alternative_id.rsplit("-", 1)[1])
            analysis = analyses[feature_index]
        except (ValueError, IndexError) as exc:
            raise ValueError("alternative_id no identifica un feature enriquecido") from exc
        if (analysis["geometry_sha256"] != geometry_sha256(route)
                or abs(analysis["distance_km"] - route.distance_km) > 1e-8
                or abs(analysis["duration_hours"] - route.duration_hours) > 1e-8):
            raise ValueError("snapshot enriquecido no coincide con su registro normalizado")
        previous = originals.get((route.origin_id, route.destination_id))
        old_geometry = previous.geometry_lon_lat if previous else ()
        new_geometry = route.geometry_lon_lat or ()
        first_different = next((index for index, (old, new) in
                                enumerate(zip(old_geometry, new_geometry)) if old != new), None)
        if first_different is None and len(old_geometry) != len(new_geometry):
            first_different = min(len(old_geometry), len(new_geometry))
        result.append({"route_id": route.alternative_id, "origin_id": route.origin_id,
                       "destination_id": route.destination_id, "request_id": request_id,
                       "acquired_at": acquired_at, "raw_sha256": sha256(raw_path.read_bytes()).hexdigest(),
                       "source": route.source, "routing_engine_version": route.routing_engine_version,
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
    rows = analyze_saved_routes(args.enriched_store, args.enriched_raw, args.original_store)
    known = set()
    if args.known_osm.exists():
        with args.known_osm.open(encoding="utf-8-sig", newline="") as stream:
            known = {int(row["osm_id"]) for row in csv.DictReader(stream)
                     if row["osm_type"] == "way"}
    all_ids = {osm_id for row in rows for osm_id in row["osm_way_ids"]}
    way_plan = plan_overpass_way_queries(all_ids, known_way_ids=known, batch_size=20)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "enriched_routes.json").write_text(
        json.dumps({"schema_version": 1, "routes": rows,
                    "warning": "Marcas cartográficas; peajes monetarios desconocidos"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "overpass_way_plan.json").write_text(
        json.dumps({"schema_version": 1, "queries": way_plan, "http_requests_executed": 0},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.output / "enriched_routes.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ("origin_id", "destination_id", "route_id", "acquired_at", "distance_km",
                  "duration_hours", "coverage", "toll_distance_km", "geometry_sha256",
                  "previous_geometry_sha256", "geometry_equal_to_previous",
                  "first_different_coordinate_index", "toll_verification")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)
    print(json.dumps({"analyzed_routes": len(rows), "unique_osm_way_ids": len(all_ids),
                      "pending_overpass_id_queries": len(way_plan), "http_requests_executed": 0,
                      "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
