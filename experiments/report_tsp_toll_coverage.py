"""Genera un informe de cobertura de peajes desde datos locales, sin red."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tsp.etl.dataset_export import load_published_dataset
from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_coverage import build_toll_coverage_report, coverage_report_as_dict
from src.tsp.etl.toll_operation import RouteEvidence, load_route_evidence


VERIFIED_ROUTE_FIELDS = ("origin_id", "destination_id", "route_id", "toll_status",
                         "toll_total_eur", "cost_total_eur", "inventory_source",
                         "no_toll_source", "matrix_equivalence_source", "section_evidence")


def verified_route_rows(economic_rows: list[dict], evidence: tuple[RouteEvidence, ...]) -> list[dict]:
    """Exporta solo importes completos con evidencias revisadas y trazables."""
    by_id = {record.route_id: record for record in evidence}
    result = []
    for row in economic_rows:
        if row["toll_status"] not in {"VERIFIED_ZERO", "VERIFIED_AMOUNT"}:
            continue
        record = by_id.get(row["route_id"])
        if (record is None or record.origin_id != row["origin_id"]
                or record.destination_id != row["destination_id"]
                or not record.inventory_complete or not record.matrix_route_equivalent
                or record.review_status != "revisado" or not row["toll_total_eur"]
                or not row["cost_total_eur"]):
            raise ValueError("costo completo sin evidencia revisada y equivalencia Matrix/ORS")
        if row["toll_status"] == "VERIFIED_ZERO" and (float(row["toll_total_eur"]) != 0
                                                          or not record.no_toll_source):
            raise ValueError("cero de peaje sin evidencia de ausencia")
        if row["toll_status"] == "VERIFIED_AMOUNT" and float(row["toll_total_eur"]) <= 0:
            raise ValueError("peaje positivo sin importe válido")
        result.append({"origin_id": row["origin_id"], "destination_id": row["destination_id"],
                       "route_id": row["route_id"], "toll_status": row["toll_status"],
                       "toll_total_eur": row["toll_total_eur"], "cost_total_eur": row["cost_total_eur"],
                       "inventory_source": record.inventory_source,
                       "no_toll_source": record.no_toll_source,
                       "matrix_equivalence_source": record.matrix_equivalence_source,
                       "section_evidence": "; ".join(ref for section in record.sections
                                                      for ref in section.evidence)})
    return result


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
    parser.add_argument("--economic-arcs", type=Path,
                        default=Path("data/processed/tolls/economic/economic_arcs.csv"))
    parser.add_argument("--evidence", type=Path,
                        default=Path("data/processed/tolls/ap68_route_evidence.json"))
    args = parser.parse_args(argv)
    report = generate_report(
        dataset_dir=args.dataset_dir,
        route_root=args.route_root,
        raw_route_root=args.raw_route_root,
        matches_csv=args.matches_csv,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = coverage_report_as_dict(report)
    if args.economic_arcs.exists():
        with args.economic_arcs.open(encoding="utf-8", newline="") as stream:
            economic_rows = list(csv.DictReader(stream))
        verified = verified_route_rows(
            economic_rows, load_route_evidence(args.evidence) if args.evidence.exists() else ())
        verified_path = args.output_dir / "verified_real_routes.csv"
        with verified_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=VERIFIED_ROUTE_FIELDS)
            writer.writeheader()
            writer.writerows(verified)
        by_pair = {(row["origin_id"], row["destination_id"]): row for row in economic_rows}
        if len(economic_rows) != report.expected_directed_arcs or len(by_pair) != len(economic_rows):
            raise ValueError("el reporte económico no cubre una vez cada arco dirigido")
        if set(by_pair) != {(r.origin_id, r.destination_id) for r in report.rows}:
            raise ValueError("el reporte económico tiene arcos ajenos al catálogo")
        statuses = {status: sum(row["toll_status"] == status for row in economic_rows)
                    for status in ("UNKNOWN", "PARTIAL", "VERIFIED_ZERO", "VERIFIED_AMOUNT")}
        if sum(statuses.values()) != len(economic_rows):
            raise ValueError("estado económico desconocido")
        payload["coverage"].update({
            "arcs_with_verified_sections": sum(bool(row["verified_section_eur"])
                                               for row in economic_rows),
            "arcs_with_partial_tariff": statuses["PARTIAL"],
            "arcs_with_verified_total_toll": statuses["VERIFIED_ZERO"] + statuses["VERIFIED_AMOUNT"],
            "arcs_with_verified_zero_toll": statuses["VERIFIED_ZERO"],
            "arcs_with_unknown_toll": statuses["UNKNOWN"] + statuses["PARTIAL"],
            "arcs_with_complete_economic_cost": sum(bool(row["cost_total_eur"]) for row in economic_rows),
        })
        for row in payload["rows"]:
            economic = by_pair[(row["origin_id"], row["destination_id"])]
            row["toll_status"] = economic["toll_status"]
            row["pending_reason"] = economic["reason"]
        pending = [row for row in payload["rows"] if row["toll_status"] in {"UNKNOWN", "PARTIAL"}]
        pending.sort(key=lambda row: (
            0 if row["toll_status"] == "PARTIAL" else 1,
            -row["infrastructure_candidate_count"], -row["route_geometry_count"],
            row["origin_id"], row["destination_id"],
        ))
        pending_path = args.output_dir / "toll_pending_priority.csv"
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with pending_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(pending[0]) if pending else list(payload["rows"][0]))
            writer.writeheader()
            writer.writerows(pending)
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
