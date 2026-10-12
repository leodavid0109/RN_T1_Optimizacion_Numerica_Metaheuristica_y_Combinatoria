"""Reconstruye matrices TSP solo desde alternativas locales; no accede a internet."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl.matrices import build_matrix_files
from src.tsp.etl import RouteStore, load_etl_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/tsp_etl.yaml"))
    parser.add_argument("--store", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--mode", choices=("fastest", "economic"), default="fastest")
    parser.add_argument("--hour-value", type=float)
    args = parser.parse_args()
    config = load_etl_config(args.config)
    report = build_matrix_files(
        load_city_catalog(args.catalog),
        RouteStore(args.store or config.route_catalog.parent,
                   raw_dir=args.raw_dir or config.raw_responses).load_alternatives(),
        args.output or config.matrices,
        mode=args.mode, hour_value_eur_per_hour=args.hour_value,
    )
    print(f"Arcos con distancia/tiempo: {report.routed_arcs} "
          f"de {report.directed_arc_count}; matriz económica: {report.economic_matrix_written}")
    print(f"Pendientes o no verificables: {len(report.missing_arcs)}; consulte matrix_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
