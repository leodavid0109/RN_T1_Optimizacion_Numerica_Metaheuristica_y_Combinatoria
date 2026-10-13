"""Genera un informe de cobertura de peajes desde datos locales, sin red."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_coverage import build_toll_coverage_report, coverage_report_as_dict


def generate_report(
    *,
    dataset_dir: str | Path = "data/datasets/spain_tsp_2026",
    route_root: str | Path = "data/processed/routes",
    raw_route_root: str | Path = "data/raw/routes",
    matches_csv: str | Path = "data/processed/tolls/overpass_route_matches.csv",
):
    dataset = load_published_dataset(dataset_dir)
    city_order = tuple(dataset["city_order"])
    size = len(city_order)
    matrix_arcs = {
        (city_order[i], city_order[j])
        for i in range(size) for j in range(size) if i != j
        and dataset["distance_km"][i, j] >= 0
        and dataset["duration_hours"][i, j] >= 0
    }

    route_store = RouteStore(route_root, raw_dir=raw_route_root)
    alternatives = route_store.load_alternatives() if route_store.catalog_path.exists() else ()
    match_rows = []
    matches_path = Path(matches_csv)
    if matches_path.exists():
        with matches_path.open(encoding="utf-8-sig", newline="") as stream:
            match_rows = list(csv.DictReader(stream))

    provenance = dataset["metadata"]["provenance"]
    consumption = provenance["consumption_l_per_100km"]["reference"]
    price = provenance["fuel_price_eur_l"]
    return build_toll_coverage_report(
        city_order,
        distance_duration_arcs=matrix_arcs,
        alternatives=alternatives,
        infrastructure_matches=match_rows,
        fuel_consumption_l_per_100km=consumption,
        fuel_price_eur_per_l=price,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--route-root", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--raw-route-root", type=Path, default=Path("data/raw/routes"))
    parser.add_argument("--matches-csv", type=Path, default=Path("data/processed/tolls/overpass_route_matches.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/tolls"))
    args = parser.parse_args(argv)
    report = generate_report(
        dataset_dir=args.dataset_dir,
        route_root=args.route_root,
        raw_route_root=args.raw_route_root,
        matches_csv=args.matches_csv,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = coverage_report_as_dict(report)
    json_path = args.output_dir / "toll_coverage_national.json"
    csv_path = args.output_dir / "toll_coverage_arcs.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(payload["rows"][0]) if payload["rows"] else []
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(payload["rows"])
    print(json.dumps({**payload["coverage"], "expected_directed_arcs": payload["expected_directed_arcs"],
                      "alternative_inventory_exhaustive": payload["alternative_inventory_exhaustive"],
                      "outputs": [str(json_path), str(csv_path)]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by integration command
    raise SystemExit(main())
