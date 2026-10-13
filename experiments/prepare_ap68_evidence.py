"""Prepara revisión AP-68 de ambos sentidos desde las geometrías ORS locales."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_operation import geometry_sha256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--matches", type=Path,
                        default=Path("data/processed/tolls/overpass_route_matches.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/ap68_route_evidence.json"))
    args = parser.parse_args(argv)
    records = RouteStore(args.routes).load_alternatives()
    local_matches: dict[str, list[dict[str, str]]] = {}
    if args.matches.exists():
        with args.matches.open(encoding="utf-8-sig", newline="") as stream:
            for match in csv.DictReader(stream):
                if match.get("road_reference") == "AP-68" and match.get("infrastructure_id"):
                    local_matches.setdefault(match["route_id"], []).append(match)
    pairs = (("bizkaia", "zaragoza"), ("zaragoza", "bizkaia"))
    rows = []
    prepared_on = datetime.now(ZoneInfo("America/Bogota")).date().isoformat()
    for origin, destination in pairs:
        candidates = [r for r in records if r.origin_id == origin and r.destination_id == destination
                      and r.alternative_id == r.fastest_route_id]
        if len(candidates) != 1:
            raise ValueError(f"se esperaba una ruta rápida única para {origin}->{destination}")
        route = candidates[0]
        refs = {ref.upper().replace(" ", "") for ref in route.road_references}
        if "AP-68" not in refs and "AP68" not in refs:
            raise ValueError(f"la ruta {route.alternative_id} no menciona AP-68")
        evidence = ["referencia AP-68 en respuesta ORS; accesos aún no verificados"]
        relation = next((match for match in local_matches.get(route.alternative_id, ())
                         if match["infrastructure_id"] == "osm:relation/283102"), None)
        if relation:
            evidence.append("OSM relation/283102: alineamiento aproximado "
                            f"{float(relation['aligned_route_length_m']) / 1000:.3f} km; "
                            f"cobertura de celdas {relation['region_coverage_fraction']}; "
                            "no confirma tránsito ni cobro")
        booths = sorted({match["infrastructure_id"] for match in local_matches.get(route.alternative_id, ())
                         if match["infrastructure_type"] == "toll_booth"})
        if booths:
            evidence.append("estaciones cercanas OSM " + ",".join(booths)
                            + "; proximidad no prueba acceso, calzada ni sentido")
        rows.append({
            "route_id": route.alternative_id, "origin_id": origin, "destination_id": destination,
            "geometry_sha256": geometry_sha256(route),
            "sections": [{"section_id": f"{route.alternative_id}:ap68-candidate",
                          "operator": "Autopistas/AVASA", "road": "AP-68",
                          "entry_station": None, "exit_station": None, "direction": None,
                          "route_match_verified": False,
                          "evidence": evidence}],
            "inventory_complete": False, "inventory_source": "", "no_toll_source": "",
            "review_status": "pendiente", "reviewed_on": prepared_on,
            "matrix_route_equivalent": False, "matrix_equivalence_source": "",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": 1, "routes": rows}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"routes": len(rows), "status": "pendiente", "file": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
