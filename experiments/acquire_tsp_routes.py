"""Planifica o ejecuta un lote explícito de solicitudes ORS, con reanudación.

Sin --execute solo imprime el plan y no requiere clave ni realiza red.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from datetime import datetime, timezone

from experiments.plan_tsp_direction_queue import plan_enriched_queue
from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl import (AcquisitionManager, AcquisitionRequest, OpenRouteServiceProvider,
                         RouteStore, load_etl_config)


def record_quarantined_failures(path: Path, failures: tuple[dict, ...]) -> None:
    """Retira fallas del flujo general sin borrarlas de diagnósticos ni del universo."""
    if not failures:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"schema_version": 1, "pairs": []}
    pairs = {(row.get("origin_id"), row.get("destination_id")): row
             for row in data.get("pairs", [])}
    for failure in failures:
        origin, destination = failure.get("origin_id"), failure.get("destination_id")
        # Una respuesta 200 que no pudo persistirse es un problema local de
        # almacenamiento, no un fallo geográfico que deba cuarentenarse.
        if origin and destination and failure.get("category") != "persistence_error":
            pairs[(origin, destination)] = {
                "origin_id": origin, "destination_id": destination,
                "reason": failure.get("category", "acquisition_failed"),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "diagnostic_file": failure.get("diagnostic_file"),
                "http_status_code": failure.get("http_status_code"),
            }
    data["schema_version"] = 1
    data["pairs"] = list(pairs.values())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--pairs",
                           help="arcos dirigidos separados por coma, p. ej. madrid:toledo,toledo:madrid")
    selection.add_argument("--queue-file", type=Path,
                           help="CSV priorizado; selecciona los primeros arcos aún no adquiridos")
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
                        help="guardarraíl local opcional; agrega el historial del endpoint y perfil, "
                             "no es el saldo de ORS ni se aplica por defecto")
    parser.add_argument("--execute", action="store_true", help="habilita llamadas de red a ORS")
    parser.add_argument("--refresh", action="store_true", help="reconsulta registros ya adquiridos")
    parser.add_argument("--retry-failed", action="store_true",
                        help="permite reintentar errores guardados al leer --queue-file")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--dataset", type=Path, default=Path("data/datasets/spain_tsp_2026"),
                        help="dataset canónico usado para validar la cola enriquecida")
    parser.add_argument("--config", type=Path, default=Path("configs/tsp_etl.yaml"))
    parser.add_argument("--profile")
    parser.add_argument("--minimum-interval", type=float)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--quarantine-file", type=Path,
                        default=Path("data/processed/tolls/prioritized_queue/quarantine_pairs.json"),
                        help="registra aquí los pares fallidos para excluirlos de lotes generales posteriores")
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
    queue_rows = None
    if args.pairs is not None:
        items = args.pairs.split(",")
    else:
        if not args.queue_file.is_file():
            parser.error(f"no existe el archivo de cola: {args.queue_file}")
        try:
            with args.queue_file.open(encoding="utf-8-sig", newline="") as stream:
                queue_rows = list(csv.DictReader(stream))
                items = [f"{row['origin_id']}:{row['destination_id']}" for row in queue_rows]
        except (OSError, KeyError, csv.Error) as exc:
            parser.error(f"no se pudo leer la cola CSV: {exc}")
    requests = []
    for item in items:
        try:
            origin, destination = (part.strip() for part in item.split(":"))
            requests.append(AcquisitionRequest(
                cities[origin], cities[destination], args.strategy,
                args.alternatives, args.strategy == "avoid_tolls", extra_info,
            ))
        except (ValueError, KeyError) as exc:
            parser.error(f"par dirigido no válido {item!r}: {exc}")
    if args.queue_file is not None:
        namespace = (f"openrouteservice:{profile}:endpoint-"
                     f"{sha256(config.directions_endpoint.rstrip('/').encode()).hexdigest()[:10]}")
        state_path = store_root / "acquisition_state.json"
        acquired = (json.loads(state_path.read_text(encoding="utf-8")).get("requests", {})
                    if state_path.exists() else {})
        queue_refresh = False
        if extra_info and not args.refresh and args.strategy == "fastest":
            pending_pairs = {(row["origin_id"], row["destination_id"])
                             for row in plan_enriched_queue(
                                 args.dataset, store_root, raw_root, extra_info=extra_info,
                                 endpoint=config.directions_endpoint)}
            requests = [request for request in requests
                        if (request.origin.city_id, request.destination.city_id) in pending_pairs]
        elif not args.refresh:
            quarantine_path = args.quarantine_file
            quarantined_pairs = set()
            if quarantine_path.is_file():
                try:
                    quarantine_data = json.loads(quarantine_path.read_text(encoding="utf-8"))
                    quarantined_pairs = {
                        (row.get("origin_id"), row.get("destination_id"))
                        for row in quarantine_data.get("pairs", [])
                    }
                except (OSError, json.JSONDecodeError, TypeError) as exc:
                    parser.error(f"no se pudo leer la cuarentena {quarantine_path}: {exc}")
            filtered = []
            for request in requests:
                pair = (request.origin.city_id, request.destination.city_id)
                entry = acquired.get(f"{namespace}:{request.request_id}", {})
                if entry.get("status") == "adquirida":
                    continue
                if pair in quarantined_pairs:
                    continue
                if entry.get("status") == "error" and not args.retry_failed:
                    continue
                filtered.append(request)
            requests = filtered
        requests = requests[:args.max_requests]
        if extra_info and queue_rows is not None:
            queue_refresh = any(acquired.get(f"{namespace}:{request.request_id}", {}).get("status")
                                == "adquirida" for request in requests)
    else:
        queue_refresh = False
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
          "max_retries": args.max_retries, "selected_request_count": len(requests),
          "invalid_existing_snapshots_to_refresh": queue_refresh,
          "selection_source": str(args.queue_file) if args.queue_file else "explicit_pairs"},
          ensure_ascii=False, indent=2))
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
        # No mezclar automáticamente historiales de credenciales distintas:
        # el saldo efectivo se controla con la respuesta del proveedor y el
        # presupuesto HTTP estricto requerido por --execute.
        daily_quota=args.daily_quota,
    ).run(
        requests, max_requests=args.max_requests, refresh=args.refresh or queue_refresh,
    )
    failures = tuple(getattr(summary, "failures", ()))
    if failures:
        try:
            record_quarantined_failures(args.quarantine_file, failures)
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            parser.error(f"no se pudo actualizar la cuarentena; diagnósticos preservados: {exc}")
    print(summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
