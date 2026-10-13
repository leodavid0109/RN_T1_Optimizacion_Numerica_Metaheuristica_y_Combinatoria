"""Regenera matrices de distancia y duración desde un snapshot ORS local."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl.matrices import rebuild_matrix_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-snapshot", type=Path, required=True, help="JSON original guardado localmente")
    parser.add_argument("--output-dir", type=Path, required=True, help="directorio local para CSV y manifiesto")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    cities = load_city_catalog(args.catalog)
    paths = rebuild_matrix_snapshot(args.raw_snapshot, args.output_dir,
                                    [city.city_id for city in cities])
    print("Matrices regeneradas sin conexión:")
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(f"Manifiesto: {args.output_dir / f'matrix_manifest_{args.raw_snapshot.stem}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
