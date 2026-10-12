"""Planifica o ejecuta un lote explícito de solicitudes ORS, con reanudación.

Sin --execute solo imprime el plan y no requiere clave ni realiza red.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl import (AcquisitionManager, AcquisitionRequest, OpenRouteServiceProvider,
                         RouteStore, load_etl_config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", required=True,
                        help="arcos dirigidos separados por coma, p. ej. madrid:toledo,toledo:madrid")
    parser.add_argument("--strategy", choices=("fastest", "avoid_tolls", "alternatives"), default="fastest")
    parser.add_argument("--alternatives", type=int, default=0, help="número total de rutas candidatas que solicita ORS")
    parser.add_argument("--max-requests", type=int, required=True,
                        help="límite explícito de llamadas de esta ejecución")
    parser.add_argument("--daily-quota", type=int,
                        help="cuota diaria Directions configurada para la cuenta (predeterminada: config YAML)")
    parser.add_argument("--execute", action="store_true", help="habilita llamadas de red a ORS")
    parser.add_argument("--refresh", action="store_true", help="reconsulta registros ya adquiridos")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--config", type=Path, default=Path("configs/tsp_etl.yaml"))
    parser.add_argument("--profile")
    parser.add_argument("--minimum-interval", type=float)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args()
    config = load_etl_config(args.config)
    profile = args.profile or config.profile
    if args.alternatives < 0 or args.alternatives > 3:
        parser.error("--alternatives debe estar entre 0 y 3")
    if args.strategy == "alternatives" and args.alternatives == 0:
        parser.error("--strategy alternatives requiere --alternatives entre 1 y 3")
    cities = {city.city_id: city for city in load_city_catalog(args.catalog)}
    requests = []
    for item in args.pairs.split(","):
        try:
            origin, destination = (part.strip() for part in item.split(":"))
            requests.append(AcquisitionRequest(
                cities[origin], cities[destination], args.strategy,
                args.alternatives, args.strategy == "avoid_tolls",
            ))
        except (ValueError, KeyError) as exc:
            parser.error(f"par dirigido no válido {item!r}: {exc}")
    if len(requests) > args.max_requests:
        parser.error(f"el lote ({len(requests)}) excede --max-requests={args.max_requests}")
    if not args.execute:
        print(json.dumps({"execution": "plan_only", "requests": [
            {"request_id": request.request_id, "origin": request.origin.city_id,
             "destination": request.destination.city_id, "strategy": request.strategy}
            for request in requests
        ]}, ensure_ascii=False, indent=2))
        return 0
    provider = OpenRouteServiceProvider(
        profile=profile,
        endpoint=config.directions_endpoint,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        min_interval_seconds=(args.minimum_interval if args.minimum_interval is not None
                              else config.minimum_seconds_between_requests),
    )
    summary = AcquisitionManager(
        provider,
        RouteStore(args.store or config.route_catalog.parent,
                   raw_dir=args.raw_dir or config.raw_responses),
        daily_quota=(args.daily_quota if args.daily_quota is not None
                     else config.standard_plan_daily_directions_limit),
    ).run(
        requests, max_requests=args.max_requests, refresh=args.refresh,
    )
    print(summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
