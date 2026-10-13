"""Prepara localmente el paquete CSV nacional desde un snapshot ORS, sin red."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.tsp.cities import CATALOG_PATH
from src.tsp.etl.dataset_export import export_spain_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True,
                        help="respuesta ORS Matrix local ya validada")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--economics", type=Path, default=Path("configs/tsp_economics.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    args = parser.parse_args()
    metadata = export_spain_dataset(args.snapshot, args.catalog, args.economics, args.output)
    print(f"Preparado localmente: {args.output}")
    print(f"Ciudades: {metadata['city_count']}; arcos: {metadata['directed_non_diagonal_arcs']}")
    print(f"Licencia de resultados ORS: {metadata['redistribution']['ors_results_license']}; "
          "consulte LICENSE-DATA.md para ODbL y atribución por componente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
