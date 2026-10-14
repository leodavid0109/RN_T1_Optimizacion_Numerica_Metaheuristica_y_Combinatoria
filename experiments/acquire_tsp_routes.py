"""Planifica o ejecuta un lote explícito de solicitudes ORS, con reanudación.

Sin --execute solo imprime el plan y no requiere clave ni realiza red.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
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
    parser.add_argument("--extra-info", default="",
                        help="atributos Directions separados por comas: tollways,osmid,waycategory")
    parser.add_argument("--max-requests", type=int, required=True,
                        help="límite explícito de llamadas de esta ejecución")
    parser.add_argument("--max-http-requests", type=int,
                        help="límite total de intentos HTTP, incluidos reintentos; obligatorio con --execute")
    parser.add_argument("--max-retries", type=int,
                        help="reintentos máximos por solicitud (por defecto: configuración YAML; 0 los desactiva)")
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
    extra_info = tuple(part.strip() for part in args.extra_info.split(",") if part.strip())
    if args.extra_info and not extra_info:
        parser.error("--extra-info requiere al menos un atributo válido")
    store_root = args.store or (config.route_catalog.parent / "enriched" if extra_info
                                else config.route_catalog.parent)
    raw_root = args.raw_dir or (config.raw_responses / "enriched" if extra_info
                                else config.raw_responses)
    if extra_info and (store_root.resolve() == config.route_catalog.parent.resolve()
                       or raw_root.resolve() == config.raw_responses.resolve()):
        parser.error("las respuestas enriquecidas requieren un almacén distinto al piloto original")
    cities = {city.city_id: city for city in load_city_catalog(args.catalog)}
    requests = []
    for item in args.pairs.split(","):
        try:
            origin, destination = (part.strip() for part in item.split(":"))
            requests.append(AcquisitionRequest(
                cities[origin], cities[destination], args.strategy,
                args.alternatives, args.strategy == "avoid_tolls", extra_info,
            ))
        except (ValueError, KeyError) as exc:
            parser.error(f"par dirigido no válido {item!r}: {exc}")
    if len(requests) > args.max_requests:
        parser.error(f"el lote ({len(requests)}) excede --max-requests={args.max_requests}")
    if args.execute and (args.max_http_requests is None or args.max_http_requests < 1):
        parser.error("--execute requiere --max-http-requests positivo, contando cada reintento")
    if args.max_retries is not None and args.max_retries < 0:
        parser.error("--max-retries no puede ser negativo")
    if not args.execute:
        namespace = (f"openrouteservice:{profile}:endpoint-"
                     f"{sha256(config.directions_endpoint.rstrip('/').encode()).hexdigest()[:10]}")
        state_path = store_root / "acquisition_state.json"
        acquired = (json.loads(state_path.read_text(encoding="utf-8")).get("requests", {})
                    if state_path.exists() else {})
        print(json.dumps({"execution": "plan_only", "requests": [
            {"request_id": request.request_id, "origin": request.origin.city_id,
             "destination": request.destination.city_id, "strategy": request.strategy,
             "extra_info": list(request.extra_info),
             "already_acquired": (acquired.get(f"{namespace}:{request.request_id}", {}).get("status")
                                  == "adquirida"),
             "legacy_request_id": (AcquisitionRequest(request.origin, request.destination,
                                                       request.strategy, request.request_alternatives,
                                                       request.avoid_tolls).request_id
                                   if request.extra_info else request.request_id)}
            for request in requests
        ], "endpoint": config.directions_endpoint,
          "effective_endpoint": f"{config.directions_endpoint.rstrip('/')}/{profile}/geojson",
          "timeout_seconds": config.timeout_seconds,
          "store": str(store_root), "raw_dir": str(raw_root),
          "max_requests": args.max_requests, "max_http_requests": args.max_http_requests,
          "max_retries": args.max_retries}, ensure_ascii=False, indent=2))
        return 0
    provider = OpenRouteServiceProvider(
        profile=profile,
        endpoint=config.directions_endpoint,
        timeout_seconds=config.timeout_seconds,
        max_retries=(config.max_retries if args.max_retries is None else args.max_retries),
        max_http_requests=args.max_http_requests,
        min_interval_seconds=(args.minimum_interval if args.minimum_interval is not None
                              else config.minimum_seconds_between_requests),
    )
    summary = AcquisitionManager(
        provider,
        RouteStore(store_root, raw_dir=raw_root),
        daily_quota=(args.daily_quota if args.daily_quota is not None
                     else config.standard_plan_daily_directions_limit),
    ).run(
        requests, max_requests=args.max_requests, refresh=args.refresh,
    )
    print(summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
