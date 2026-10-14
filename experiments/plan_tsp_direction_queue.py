"""Crea cola offline de rutas rápidas faltantes; nunca llama a ORS."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tsp.cities import load_city_catalog
from src.tsp.etl.acquisition import AcquisitionRequest
from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.ors_extras import analyze_geojson_extras
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_operation import geometry_sha256


def plan_queue(dataset_dir: Path, route_root: Path) -> list[dict]:
    dataset = load_published_dataset(dataset_dir)
    cities = {city.city_id: city for city in load_city_catalog()}
    order = dataset["city_order"]
    if set(cities) != set(order):
        raise ValueError("catálogo y dataset no contienen las mismas ciudades")
    store = RouteStore(route_root)
    existing = {(r.origin_id, r.destination_id) for r in store.load_alternatives()
                if r.alternative_id == r.fastest_route_id and r.geometry_lon_lat}
    rows = []
    for i, origin in enumerate(order):
        for j, destination in enumerate(order):
            if i == j or (origin, destination) in existing:
                continue
            request = AcquisitionRequest(cities[origin], cities[destination])
            rows.append({"origin_id": origin, "destination_id": destination,
                         "request_id": request.request_id,
                         "duration_hours_matrix": float(dataset["duration_hours"][i, j]),
                         "priority_rule": "duración Matrix descendente; desempate por IDs"})
    rows.sort(key=lambda r: (-r["duration_hours_matrix"], r["origin_id"], r["destination_id"]))
    return rows


def plan_enriched_queue(dataset_dir: Path, route_root: Path, raw_root: Path, *,
                        extra_info: tuple[str, ...] = ("tollways", "waycategory"),
                        endpoint: str = "https://api.heigit.org/openrouteservice/v2/directions") -> list[dict]:
    """Planifica arcos sin snapshot válido que contenga los extras requeridos.

    Una geometría Directions antigua no satisface una adquisición enriquecida.
    Cada respuesta exitosa se vuelve a validar desde el JSON persistido, en modo
    offline, antes de excluir su arco de la cola.
    """
    required = tuple(sorted(set(extra_info)))
    if not required or set(required) - {"tollways", "osmid", "waycategory"}:
        raise ValueError("extra_info debe contener atributos ORS válidos")
    dataset = load_published_dataset(dataset_dir)
    cities = {city.city_id: city for city in load_city_catalog()}
    order = tuple(dataset["city_order"])
    if set(cities) != set(order):
        raise ValueError("catálogo y dataset no contienen las mismas ciudades")

    store = RouteStore(route_root, raw_dir=raw_root)
    routes_by_id = {route.alternative_id: route for route in store.load_alternatives()}
    state = json.loads(store.state_path.read_text(encoding="utf-8")) if store.state_path.exists() else {}
    catalog_rows = store._read_catalog()
    request_rows = {row["request_id"]: row for row in catalog_rows}
    valid_pairs: set[tuple[str, str]] = set()
    endpoint_host = endpoint.rstrip("/")
    for request_key, entry in state.get("requests", {}).items():
        if entry.get("status") != "adquirida" or not entry.get("raw_file"):
            continue
        catalog_row = request_rows.get(request_key)
        if not catalog_row:
            continue
        try:
            raw_path = Path(entry["raw_file"])
            if not raw_path.is_absolute():
                raw_path = Path.cwd() / raw_path
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            request = raw["request"]
            body = request["body"]
            requested = tuple(body.get("extra_info", ()))
            if (request.get("method") != "POST" or not request["url"].startswith(endpoint_host)
                    or body.get("preference") != "fastest" or not set(required) <= set(requested)):
                continue
            analyses = analyze_geojson_extras(raw["response"], required=required)
            origin, destination = catalog_row["origin_id"], catalog_row["destination_id"]
            valid_route = False
            for route in routes_by_id.values():
                if route.origin_id != origin or route.destination_id != destination:
                    continue
                try:
                    feature_index = int(route.alternative_id.rsplit("-", 1)[1])
                    analysis = analyses[feature_index]
                except (ValueError, IndexError):
                    continue
                if (analysis["geometry_sha256"] == geometry_sha256(route)
                        and abs(analysis["distance_km"] - route.distance_km) <= 1e-8
                        and abs(analysis["duration_hours"] - route.duration_hours) <= 1e-8):
                    valid_route = True
                    break
            if valid_route:
                valid_pairs.add((origin, destination))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

    rows = []
    for i, origin in enumerate(order):
        for j, destination in enumerate(order):
            if i == j or (origin, destination) in valid_pairs:
                continue
            request = AcquisitionRequest(cities[origin], cities[destination], extra_info=required)
            rows.append({"origin_id": origin, "destination_id": destination,
                         "request_id": request.request_id,
                         "duration_hours_matrix": float(dataset["duration_hours"][i, j]),
                         "priority_rule": "duración Matrix descendente; desempate por IDs; extras pendientes"})
    rows.sort(key=lambda row: (-row["duration_hours_matrix"], row["origin_id"], row["destination_id"]))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--routes", type=Path)
    parser.add_argument("--raw-routes", type=Path)
    parser.add_argument("--extra-info", default="",
                        help="planifica solo solicitudes pendientes con estos extras ORS")
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/directions_queue.csv"))
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("batch-size debe ser positivo")
    extra_info = tuple(part.strip() for part in args.extra_info.split(",") if part.strip())
    route_root = args.routes or (Path("data/processed/routes/enriched") if extra_info
                                 else Path("data/processed/routes"))
    raw_root = args.raw_routes or (Path("data/raw/routes/enriched") if extra_info
                                   else Path("data/raw/routes"))
    rows = (plan_enriched_queue(args.dataset, route_root, raw_root,
                                extra_info=extra_info) if extra_info
            else plan_queue(args.dataset, route_root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["origin_id", "destination_id", "request_id",
                                                       "duration_hours_matrix", "priority_rule"])
        writer.writeheader()
        writer.writerows(rows)
    first = rows[:args.batch_size]
    print(json.dumps({"universe": 2162, "already_geometries": 2162 - len(rows),
                      "pending": len(rows), "preview_batch_size": len(first),
                      "preview_pairs": ",".join(f"{r['origin_id']}:{r['destination_id']}" for r in first),
                      "output": str(args.output), "http_requests": 0,
                      "extra_info": list(extra_info)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
