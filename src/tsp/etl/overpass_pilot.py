"""Planificación y ejecución explícita de un inventario Overpass por corredores.

El modo predeterminado solo lee rutas locales y produce un manifiesto. La red
solo se usa con ``--execute``. Las cajas forman una cuadrícula de celdas
pequeñas sobre el corredor ensanchado, en vez de cubrir cada ruta con su gran
rectángulo envolvente.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import time
from typing import Iterable

from ..alternatives import RouteAlternative
from .store import RouteStore
from .toll_infrastructure import BoundingBox, OverpassCatalogStore, OverpassClient, OverpassError


DEFAULT_ROUTE_ROOT = Path("data/processed/routes")
DEFAULT_RAW_ROUTE_ROOT = Path("data/raw/routes")
DEFAULT_PLAN_PATH = Path("data/processed/tolls/overpass_pilot_manifest.json")
DEFAULT_STATE_PATH = Path("data/processed/tolls/overpass_pilot_state.json")
PILOT_PAIRS = {
    ("madrid", "toledo"), ("toledo", "madrid"),
    ("bizkaia", "zaragoza"), ("zaragoza", "bizkaia"),
    ("madrid", "a_coruna"), ("barcelona", "girona"),
}


@dataclass(frozen=True)
class PlannedRegion:
    """Una caja Overpass estable y los corredores cubiertos por ella."""

    region_id: str
    bbox: BoundingBox
    route_ids: tuple[str, ...]
    priority: int

    def as_dict(self) -> dict:
        return {
            "region_id": self.region_id,
            "bbox_south_west_north_east": [
                self.bbox.south, self.bbox.west, self.bbox.north, self.bbox.east,
            ],
            "route_ids": list(self.route_ids),
            "priority": self.priority,
            "query": self.bbox.overpass_query(),
        }


@dataclass(frozen=True)
class OverpassPilotPlan:
    """Manifiesto reproducible derivado de las geometrías locales."""

    regions: tuple[PlannedRegion, ...]
    route_ids: tuple[str, ...]
    route_pair_count: int
    geometry_point_count: int
    segment_count: int
    coverage_sample_count: int
    route_geometry_sha256: tuple[tuple[str, str], ...]
    cell_degrees: float
    margin_m: float

    @property
    def planned_requests(self) -> int:
        return len(self.regions)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({
            "route_ids": self.route_ids,
            "route_geometry_sha256": self.route_geometry_sha256,
            "cell_degrees": self.cell_degrees,
            "margin_m": self.margin_m,
            "regions": [region.as_dict() for region in self.regions],
        }, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {
            "schema_version": 1,
            "plan_sha256": self.fingerprint,
            "source": "geometrías ORS persistidas localmente; plan sin consultas de red",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "route_ids": list(self.route_ids),
            "route_geometry_sha256": dict(self.route_geometry_sha256),
            "route_pair_count": self.route_pair_count,
            "geometry_count": len(self.route_ids),
            "geometry_point_count": self.geometry_point_count,
            "segment_count": self.segment_count,
            "coverage_sample_count": self.coverage_sample_count,
            "coverage_verified": True,
            "cell_degrees": self.cell_degrees,
            "margin_m": self.margin_m,
            "query_count": self.planned_requests,
            "request_policy": {
                "sequential": True,
                "minimum_seconds_between_requests": 2.0,
                "automatic_retries": 0,
                "on_http_429": "guardar estado, detener; esperar al menos 30 s antes de reanudar",
            },
            "regions": [region.as_dict() for region in self.regions],
        }


def plan_overpass_regions(
    routes: Iterable[RouteAlternative],
    *,
    cell_degrees: float = 0.5,
    margin_m: float = 2_000.0,
) -> OverpassPilotPlan:
    """Cubre todas las polilíneas mediante celdas deduplicadas y acotadas.

    Para cada segmento se ensancha su caja local por ``margin_m`` y se incluyen
    las celdas de la cuadrícula que intersectan esa caja. Es conservador: puede
    incluir celdas que no tocan la línea, pero no crea una única caja extensa
    para todo un corredor.
    """
    routes = tuple(routes)
    if not routes:
        raise ValueError("no hay rutas locales para planificar")
    if not math.isfinite(cell_degrees) or not 0 < cell_degrees <= 1:
        raise ValueError("cell_degrees debe estar en (0, 1]")
    if not math.isfinite(margin_m) or margin_m < 0:
        raise ValueError("margin_m debe ser finito y no negativo")

    by_cell: dict[tuple[int, int], set[str]] = {}
    route_ids: list[str] = []
    route_by_id: dict[str, RouteAlternative] = {}
    geometry_digests: list[tuple[str, str]] = []
    point_count = 0
    segment_count = 0
    pair_keys: set[tuple[str, str]] = set()
    for route in routes:
        geometry = route.geometry_lon_lat
        if geometry is None or len(geometry) < 2:
            raise ValueError(f"la ruta {route.alternative_id} no tiene geometría lineal válida")
        route_ids.append(route.alternative_id)
        route_by_id[route.alternative_id] = route
        geometry_json = json.dumps(geometry, separators=(",", ":"), ensure_ascii=True)
        geometry_digests.append((route.alternative_id, sha256(geometry_json.encode("ascii")).hexdigest()))
        pair_keys.add((route.origin_id, route.destination_id))
        point_count += len(geometry)
        segments = tuple(zip(geometry, geometry[1:]))
        segment_count += len(segments)
        for (lon1, lat1), (lon2, lat2) in segments:
            max_abs_lat = min(89.0, max(abs(lat1), abs(lat2)))
            lat_pad = margin_m / 110_574.0
            lon_pad = margin_m / (111_320.0 * math.cos(math.radians(max_abs_lat)))
            min_x = min(lon1, lon2) - lon_pad
            max_x = max(lon1, lon2) + lon_pad
            min_y = min(lat1, lat2) - lat_pad
            max_y = max(lat1, lat2) + lat_pad
            ix0, ix1 = math.floor(min_x / cell_degrees), math.floor(max_x / cell_degrees)
            iy0, iy1 = math.floor(min_y / cell_degrees), math.floor(max_y / cell_degrees)
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    by_cell.setdefault((ix, iy), set()).add(route.alternative_id)

    if len(route_ids) != len(set(route_ids)):
        raise ValueError("el catálogo contiene alternative_id duplicados")
    regions = []
    for ix, iy in by_cell:
        west, south = ix * cell_degrees, iy * cell_degrees
        east, north = west + cell_degrees, south + cell_degrees
        # Recortar solo por rango WGS84; las geometrías piloto están en España.
        south, north = max(-90.0, south), min(90.0, north)
        west, east = max(-180.0, west), min(180.0, east)
        bbox = BoundingBox(south, west, north, east)
        covered = tuple(sorted(by_cell[(ix, iy)]))
        priority = 0 if any(_is_bilbao_zaragoza(route_by_id[route_id]) for route_id in covered) else 1
        region_id = f"cell-{ix:+05d}-{iy:+05d}"
        regions.append(PlannedRegion(region_id, bbox, covered, priority))

    regions.sort(key=lambda region: (region.priority, region.region_id))
    planned_route_ids = {route_id for region in regions for route_id in region.route_ids}
    missing = set(route_ids) - planned_route_ids
    if missing:
        raise ValueError("el plan no cubre estas rutas: " + ", ".join(sorted(missing)))
    boxes_by_route = {
        route_id: tuple(region.bbox for region in regions if route_id in region.route_ids)
        for route_id in route_ids
    }
    coverage_samples = 0
    for route in routes:
        geometry = route.geometry_lon_lat or ()
        route_boxes = boxes_by_route[route.alternative_id]
        samples = [*geometry]
        samples.extend(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                       for a, b in zip(geometry, geometry[1:]))
        for lon, lat in samples:
            if not any(box.west <= lon <= box.east and box.south <= lat <= box.north
                       for box in route_boxes):
                raise ValueError(f"la cobertura de celdas dejó fuera un punto de {route.alternative_id}")
        coverage_samples += len(samples)
    return OverpassPilotPlan(
        tuple(regions), tuple(sorted(route_ids)), len(pair_keys), point_count,
        segment_count, coverage_samples, tuple(sorted(geometry_digests)), cell_degrees, margin_m,
    )


def _is_bilbao_zaragoza(route: RouteAlternative) -> bool:
    return {route.origin_id, route.destination_id} == {"bizkaia", "zaragoza"}


def load_local_pilot_routes(
    route_root: str | Path = DEFAULT_ROUTE_ROOT,
    raw_route_root: str | Path = DEFAULT_RAW_ROUTE_ROOT,
) -> tuple[RouteAlternative, ...]:
    """Carga el catálogo local sin hacer llamadas a proveedores."""
    routes = RouteStore(route_root, raw_dir=raw_route_root).load_alternatives()
    if not routes:
        raise ValueError(f"no hay alternativas locales en {Path(route_root) / 'route_alternatives.csv'}")
    pilot_routes = tuple(
        route for route in routes
        if (route.origin_id, route.destination_id) in PILOT_PAIRS
        and dict(route.routing_parameters).get("strategy") in {"fastest", "avoid_tolls"}
    )
    strategies = {
        (route.origin_id, route.destination_id, dict(route.routing_parameters)["strategy"])
        for route in pilot_routes
    }
    expected = {(origin, destination, strategy) for origin, destination in PILOT_PAIRS
                for strategy in ("fastest", "avoid_tolls")}
    if strategies != expected or len(pilot_routes) != len(expected):
        missing = sorted(expected - strategies)
        extra = sorted(strategies - expected)
        raise ValueError(f"el piloto local debe tener una ruta por arco y estrategia; faltan={missing}, extra={extra}")
    routes = pilot_routes
    if any(route.geometry_lon_lat is None for route in routes):
        raise ValueError("el catálogo incluye alternativas sin geometría")
    return routes


def write_plan(plan: OverpassPilotPlan, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_plan(
    plan: OverpassPilotPlan,
    *,
    max_requests: int,
    minimum_interval_seconds: float = 2.0,
    store: OverpassCatalogStore | None = None,
    client: OverpassClient | None = None,
    state_path: str | Path = DEFAULT_STATE_PATH,
    priorities: set[int] | None = None,
    sleep=time.sleep,
) -> dict:
    """Ejecuta un lote secuencial con presupuesto duro y reanudación local.

    ``max_requests`` limita intentos HTTP de esta invocación. Cada región
    puede causar como máximo una solicitud; no hay reintentos automáticos.
    ``priorities`` restringe el alcance sin cambiar la huella del manifiesto.
    Ante cualquier error se guarda el estado y se detiene el lote.
    """
    if max_requests < 0:
        raise ValueError("max_requests no puede ser negativo")
    if not math.isfinite(minimum_interval_seconds) or minimum_interval_seconds < 0:
        raise ValueError("minimum_interval_seconds debe ser finito y no negativo")
    unknown_priorities = (priorities or set()) - {region.priority for region in plan.regions}
    if unknown_priorities:
        raise ValueError(f"prioridades inexistentes en el plan: {sorted(unknown_priorities)}")
    store = store or OverpassCatalogStore("data")
    client = client or OverpassClient()
    target = Path(state_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    state = _load_state(target, plan)
    cooldown_until = state.get("cooldown_until_utc")
    if cooldown_until:
        ready_at = datetime.fromisoformat(cooldown_until)
        if datetime.now(timezone.utc) < ready_at:
            raise ValueError(f"Overpass indicó HTTP 429; reanude después de {cooldown_until}")
        state.pop("cooldown_until_utc", None)
    state.pop("stop_reason", None)
    http_requests = 0
    skipped_cached = 0
    failed = 0
    attempted_regions = 0
    last_request_at: float | None = None
    selected_regions = tuple(
        region for region in plan.regions
        if priorities is None or region.priority in priorities
    )
    # Un presupuesto de N solicitudes permite intentar como máximo N regiones
    # pendientes; cada consulta regional genera cero o una llamada, nunca más.
    unresolved = tuple(
        region for region in selected_regions
        if state["regions"].get(region.region_id, {}).get("status") != "adquirida"
    )
    batch_region_ids = {region.region_id for region in unresolved[:max_requests]}
    for region in selected_regions:
        entry = state["regions"].get(region.region_id, {})
        if entry.get("status") == "adquirida":
            skipped_cached += 1
            continue
        if region.region_id not in batch_region_ids:
            continue
        attempted_regions += 1
        if last_request_at is not None:
            remaining = minimum_interval_seconds - (time.monotonic() - last_request_at)
            if remaining > 0:
                sleep(remaining)
        http_before = getattr(client, "http_attempts", None)
        try:
            _, fetched = store.get_or_fetch(client, region.bbox)
            if fetched:
                http_after = getattr(client, "http_attempts", None)
                measured = (http_after - http_before) if http_before is not None and http_after is not None else None
                http_requests += measured if measured is not None else 1
                last_request_at = time.monotonic()
            else:
                skipped_cached += 1
            state["regions"][region.region_id] = {
                "status": "adquirida", "bbox": region.as_dict()["bbox_south_west_north_east"],
                "route_ids": list(region.route_ids), "queried_now": fetched,
                "acquired_at_utc": datetime.now(timezone.utc).isoformat() if fetched else entry.get("acquired_at_utc"),
            }
            _save_state(target, state)
        except OverpassError as exc:
            failed += 1
            http_after = getattr(client, "http_attempts", None)
            measured = (http_after - http_before) if http_before is not None and http_after is not None else None
            attempts = measured if measured is not None else 1
            http_requests += attempts
            failure_count = int(entry.get("failure_count", 0)) + 1
            repeated_server_error = (
                int(entry.get("http_status") or 0) >= 500
                and int(exc.status_code or 0) >= 500
            )
            if exc.status_code == 429:
                stop_reason = "HTTP 429: limitación de frecuencia/cuota; detener y esperar antes de reanudar"
            elif exc.status_code is not None and exc.status_code >= 500:
                stop_reason = f"HTTP {exc.status_code}: timeout/error del servidor; lote detenido sin reintentos"
            else:
                stop_reason = f"HTTP {exc.status_code}: error de transporte; lote detenido sin reintentos"
            if repeated_server_error:
                stop_reason = f"HTTP {exc.status_code} recurrente en {region.region_id}; pausa y reduzca la caja antes de reanudar"
            state["regions"][region.region_id] = {
                "status": "error", "bbox": region.as_dict()["bbox_south_west_north_east"],
                "route_ids": list(region.route_ids), "http_status": exc.status_code,
                "error": str(exc), "failure_count": failure_count,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            _save_state(target, state)
            if exc.status_code == 429:
                state["stop_reason"] = "HTTP 429: esperar al menos 30 segundos y reanudar manualmente"
                state["cooldown_until_utc"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=30)
                ).isoformat()
                _save_state(target, state)
            else:
                state["stop_reason"] = stop_reason
                _save_state(target, state)
            break
        except Exception as exc:  # conservar el progreso si parser/escritura/transporte falla
            failed += 1
            http_after = getattr(client, "http_attempts", None)
            measured = (http_after - http_before) if http_before is not None and http_after is not None else None
            attempts = measured if measured is not None else 1
            http_requests += attempts
            state["regions"][region.region_id] = {
                "status": "error", "bbox": region.as_dict()["bbox_south_west_north_east"],
                "route_ids": list(region.route_ids), "error": type(exc).__name__,
                "failure_count": int(entry.get("failure_count", 0)) + 1,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            state["stop_reason"] = f"{type(exc).__name__}: lote detenido para preservar el progreso; sin reintentos"
            _save_state(target, state)
            break
    statuses = [state["regions"].get(region.region_id, {}).get("status") for region in plan.regions]
    result = {
        "planned_requests": plan.planned_requests, "http_requests": http_requests,
        "selected_regions": len(selected_regions), "attempted_regions": attempted_regions,
        "completed_total": sum(status == "adquirida" for status in statuses),
        "failed_total": sum(status == "error" for status in statuses),
        "pending_total": sum(status not in {"adquirida", "error"} for status in statuses),
        "skipped_cached": skipped_cached, "failed": failed,
        "stop_reason": state.get("stop_reason"),
        "state_file": str(target), "raw_directory": str(store.raw_dir),
        "processed_directory": str(store.processed_dir),
    }
    state["last_execution"] = result
    _save_state(target, state)
    return result


def _load_state(path: Path, plan: OverpassPilotPlan) -> dict:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("plan_sha256") != plan.fingerprint:
            raise ValueError("el estado existente corresponde a otro plan; conserve el archivo y revise el manifiesto")
        return state
    return {"schema_version": 1, "plan_sha256": plan.fingerprint,
            "plan_route_ids": list(plan.route_ids), "regions": {}}


def _save_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planifica el inventario Overpass desde rutas ORS locales.")
    parser.add_argument("--route-root", type=Path, default=DEFAULT_ROUTE_ROOT)
    parser.add_argument("--raw-route-root", type=Path, default=DEFAULT_RAW_ROUTE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--cell-degrees", type=float, default=0.5)
    parser.add_argument("--margin-m", type=float, default=2_000.0)
    parser.add_argument("--execute", action="store_true", help="habilita explícitamente llamadas Overpass")
    parser.add_argument("--max-requests", type=int, default=0,
                        help="límite duro de solicitudes HTTP en esta invocación; permite lotes parciales")
    parser.add_argument("--priority", type=int, action="append", choices=(0, 1),
                        help="ejecuta solo regiones de esta prioridad; 0 prioriza Bilbao–Zaragoza")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)
    try:
        routes = load_local_pilot_routes(args.route_root, args.raw_route_root)
        plan = plan_overpass_regions(routes, cell_degrees=args.cell_degrees, margin_m=args.margin_m)
        write_plan(plan, args.manifest)
        print(f"Rutas con geometría: {len(plan.route_ids)}; arcos dirigidos: {plan.route_pair_count}")
        print(f"Puntos: {plan.geometry_point_count}; segmentos: {plan.segment_count}")
        print(f"Puntos y centros de segmento cubiertos: {plan.coverage_sample_count}")
        print(f"Celdas/cajas únicas planificadas: {plan.planned_requests}")
        print(f"Manifiesto: {args.manifest}")
        for region in plan.regions:
            box = region.bbox
            print(f"{region.priority} {region.region_id}: [{box.south:.6f},{box.west:.6f},{box.north:.6f},{box.east:.6f}] rutas={len(region.route_ids)}")
        if not args.execute:
            print("Modo planificación: no se hizo ninguna solicitud de red.")
            return 0
        result = execute_plan(plan, max_requests=args.max_requests,
                              minimum_interval_seconds=args.interval_seconds, state_path=args.state,
                              priorities=set(args.priority) if args.priority is not None else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["failed"] == 0 else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke tests
    raise SystemExit(main())
