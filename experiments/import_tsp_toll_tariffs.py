"""Valida y normaliza una transcripción CSV oficial de tarifas; sin red."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from src.tsp.etl.toll_tariffs import export_official_tariffs_csv, import_official_tariffs_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    tariffs = import_official_tariffs_csv(args.input)
    if not tariffs:
        parser.error("el tarifario no contiene filas")
    for tariff in tariffs:
        if (not tariff.source_url.startswith("https://") or not tariff.source_document
                or not tariff.source_page or tariff.payment_method == "unknown"
                or tariff.direction.casefold() in {"unknown", "desconocido", ""}):
            raise ValueError(f"procedencia, sentido o modalidad insuficiente: {tariff.tariff_id}")
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "tariffs_normalized.csv"
    export_official_tariffs_csv(target, tariffs)
    if import_official_tariffs_csv(target) != tariffs:
        raise ValueError("la normalización no conserva los registros originales")
    manifest = {
        "schema_version": 1, "source_file": args.input.name,
        "source_sha256": sha256(args.input.read_bytes()).hexdigest(),
        "normalized_file": target.name, "normalized_sha256": sha256(target.read_bytes()).hexdigest(),
        "tariff_count": len(tariffs), "currency": "EUR",
    }
    (args.output / "tariffs_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
