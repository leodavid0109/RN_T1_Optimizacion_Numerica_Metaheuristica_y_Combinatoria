"""Planifica o consulta explícitamente una Matrix ORS y la conserva localmente."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl import OpenRouteServiceProvider, RouteStore, load_etl_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--city-ids", help="ids canónicos, en el orden de filas/columnas")
    selection.add_argument("--all-cities", action="store_true",
                           help="usa el catálogo canónico completo en su orden de archivo")
    parser.add_argument("--max-cells", type=int, required=True,
                        help="límite explícito sobre N×N, incluida la diagonal")
    parser.add_argument("--daily-quota", type=int,
                        help="cuota Matrix diaria de la cuenta (predeterminada: config YAML)")
    parser.add_argument("--execute", action="store_true", help="habilita una llamada real de Matrix a ORS")
    parser.add_argument("--max-http-requests", type=int,
                        help="límite total de intentos HTTP; obligatorio con --execute")
    parser.add_argument("--max-retries", type=int, default=0,
                        help="reintentos máximos; por seguridad Matrix usa 0 por defecto")
    parser.add_argument("--refresh", action="store_true", help="consulta de nuevo la misma matriz")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--config", type=Path, default=Path("configs/tsp_etl.yaml"))
    parser.add_argument("--profile")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args()
    config = load_etl_config(args.config)
    profile = args.profile or config.profile
    catalog = load_city_catalog(args.catalog)
    by_id = {city.city_id: city for city in catalog}
    ids = (tuple(city.city_id for city in catalog) if args.all_cities else
           tuple(part.strip() for part in args.city_ids.split(",") if part.strip()))
    if len(ids) < 2 or len(set(ids)) != len(ids) or any(city_id not in by_id for city_id in ids):
        parser.error("--city-ids debe contener al menos dos ids canónicos únicos")
    cells = len(ids) ** 2
    if args.max_cells < 1 or cells > args.max_cells:
        parser.error(f"la matriz requiere {cells} celdas y excede --max-cells={args.max_cells}")
    if args.max_retries < 0:
        parser.error("--max-retries no puede ser negativo")
    if args.execute and (args.max_http_requests is None or args.max_http_requests < 1):
        parser.error("--execute requiere --max-http-requests positivo")
    if args.execute and args.max_http_requests != 1:
        parser.error("la adquisición nacional inicial admite exactamente una solicitud HTTP")
    if args.execute and args.max_retries != 0:
        parser.error("la adquisición nacional inicial requiere --max-retries 0")
    cities = tuple(by_id[city_id] for city_id in ids)
    signature = json.dumps({"profile": profile, "city_order": ids,
                            "coordinates_lon_lat": [[c.longitude, c.latitude] for c in cities]},
                           sort_keys=True)
    request_id = f"openrouteservice:{profile}:matrix:" + sha256(
        (config.matrix_endpoint + signature + "units=m;metrics=distance,duration").encode()
    ).hexdigest()[:20]
    store = RouteStore(args.store or config.route_catalog.parent,
                       raw_dir=args.raw_dir or config.raw_responses,
                       matrix_dir=config.matrices)
    if store.request_succeeded(request_id) and not args.refresh:
        print(f"Matriz ya adquirida; no se consulta de nuevo: {request_id}")
        return 0
    if not args.execute:
        print(json.dumps({"execution": "plan_only", "request_id": request_id,
                          "endpoint": f"{config.matrix_endpoint}/{profile}",
                          "method": "POST", "http_requests": 1,
                          "max_http_requests": args.max_http_requests,
                          "max_retries": args.max_retries,
                          "city_order": ids, "dimensions": [len(ids), len(ids)],
                          "cell_count_including_diagonal": cells,
                          "directed_arcs_excluding_diagonal": cells - len(ids),
                          "metrics": ["distance", "duration"], "distance_request_unit": "m",
                          "duration_response_unit": "s", "normalized_units": {"distance": "km", "duration": "h"},
                          "sources_and_destinations": "all locations (parameters omitted)",
                          "raw_response_directory": str(args.raw_dir or config.raw_responses),
                          "normalized_matrix_directory": str(config.matrices / "ors_snapshots"),
                          "request_body": {
                              "locations_lon_lat": [[city.longitude, city.latitude] for city in cities],
                              "metrics": ["distance", "duration"], "units": "m",
                              "resolve_locations": True,
                              "sources": "omitted (all)", "destinations": "omitted (all)",
                              "preference": "omitted (public Matrix API compatibility)",
                          },
                          "network_access_performed": False}, ensure_ascii=False, indent=2))
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    daily_quota = (args.daily_quota if args.daily_quota is not None
                   else config.standard_plan_daily_matrix_limit)
    if daily_quota < 1 or store.count_acquired_on(today, f"openrouteservice:{profile}:matrix:") >= daily_quota:
        parser.error("se alcanzó la cuota Matrix diaria configurada")
    try:
        safe_request, response, normalized = OpenRouteServiceProvider(
            profile=profile, endpoint=config.directions_endpoint, matrix_endpoint=config.matrix_endpoint,
            timeout_seconds=config.timeout_seconds, max_retries=args.max_retries,
            max_http_requests=args.max_http_requests,
            min_interval_seconds=config.minimum_seconds_between_requests,
        ).fetch_matrix(cities)
        store.save_matrix_snapshot(request_id, safe_request, response, normalized, list(ids))
    except Exception as exc:
        store.save_failure(request_id, type(exc).__name__)
        raise
    print(f"Matriz guardada en {store.matrix_dir / 'ors_snapshots'}; celdas: {cells}; orden: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
