"""Crea cola offline de rutas rápidas faltantes; nunca llama a ORS."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tsp.cities import load_city_catalog
from src.tsp.etl.acquisition import AcquisitionRequest
from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.store import RouteStore


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--routes", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/directions_queue.csv"))
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("batch-size debe ser positivo")
    rows = plan_queue(args.dataset, args.routes)
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
                      "output": str(args.output), "http_requests": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
