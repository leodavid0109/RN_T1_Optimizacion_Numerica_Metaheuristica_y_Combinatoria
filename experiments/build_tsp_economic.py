"""Construye componentes económicos parciales desde el dataset y evidencia local."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_operation import (build_economic_arcs, load_route_evidence,
                                         require_complete_economic_matrix, write_economic_arcs)
from src.tsp.etl.toll_tariffs import import_official_tariffs_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"))
    parser.add_argument("--routes", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--tariffs", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--hour-value", required=True, type=float)
    parser.add_argument("--as-of", default="2026-10-12")
    parser.add_argument("--payment-method", default="tarifa_base_sin_descuentos")
    parser.add_argument("--time-rule", default="sin regla horaria indicada en la tabla de ligeros")
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/economic"))
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    dataset = load_published_dataset(args.dataset)
    store = RouteStore(args.routes)
    routes = store.load_alternatives()
    evidence = load_route_evidence(args.evidence)
    tariffs = import_official_tariffs_csv(args.tariffs)
    arcs = build_economic_arcs(
        dataset["city_order"], dataset["duration_hours"], dataset["fuel_reference_eur"],
        routes, evidence, tariffs, hour_value_eur=args.hour_value, as_of=args.as_of,
        payment_method=args.payment_method, time_rule=args.time_rule,
    )
    if args.require_complete:
        require_complete_economic_matrix(dataset["city_order"], arcs)
    args.output.mkdir(parents=True, exist_ok=True)
    write_economic_arcs(args.output / "economic_arcs.csv", arcs)
    counts = dict(Counter(arc.toll_status for arc in arcs))
    summary = {"scenario": "costo económico verificado por arco; matriz nacional parcial",
               "hour_value_eur": args.hour_value, "as_of": args.as_of,
               "directed_arcs": len(arcs), "statuses": counts,
               "complete_economic_arcs": sum(arc.cost_total_eur is not None for arc in arcs),
               "economic_matrix_complete": all(arc.cost_total_eur is not None for arc in arcs),
               "payment_method": args.payment_method, "time_rule": args.time_rule,
               "inputs_sha256": {
                   "dataset_metadata": sha256((args.dataset / "metadata.json").read_bytes()).hexdigest(),
                   "route_catalog": sha256(store.catalog_path.read_bytes()).hexdigest(),
                   "tariffs": sha256(args.tariffs.read_bytes()).hexdigest(),
                   "evidence": sha256(args.evidence.read_bytes()).hexdigest(),
               }}
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
