"""Genera una matriz de combustible local, sin construir el costo económico total."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl.economics import load_fuel_economics
from src.tsp.etl.matrices import build_fuel_matrix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance-matrix", type=Path, required=True, help="CSV completo en km")
    parser.add_argument("--output", type=Path, required=True, help="CSV de combustible en EUR")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--economics-config", type=Path, default=Path("configs/tsp_economics.yaml"))
    parser.add_argument("--scenario", choices=("low", "reference", "high"), default="reference")
    args = parser.parse_args()
    cities = load_city_catalog(args.catalog)
    build_fuel_matrix(args.distance_matrix, args.output, [city.city_id for city in cities],
                      load_fuel_economics(args.economics_config), scenario=args.scenario)
    print(f"Matriz de combustible offline guardada en {args.output}; no incluye peajes ni costo total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
