"""Genera un informe offline de las rutas rápidas y candidatas del piloto ORS."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl import RouteStore, load_etl_config, load_fuel_economics
from src.tsp.etl.pilot_analysis import analyze_ors_pilot, write_ors_pilot_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/tsp_etl.yaml"))
    parser.add_argument("--economics-config", type=Path, default=Path("configs/tsp_economics.yaml"))
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=Path("data/processed/routes/pilot_analysis"))
    args = parser.parse_args()

    config = load_etl_config(args.config)
    store = RouteStore(config.route_catalog.parent, raw_dir=config.raw_responses)
    rows = analyze_ors_pilot(load_city_catalog(args.catalog), store, load_fuel_economics(args.economics_config))
    csv_path, markdown_path = write_ors_pilot_report(rows, args.output)
    print(f"Comparaciones verificadas: {len(rows)}")
    print(f"CSV local: {csv_path}")
    print(f"Resumen local: {markdown_path}")
    print("Sin consultas de red; los peajes desconocidos permanecen sin importe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
