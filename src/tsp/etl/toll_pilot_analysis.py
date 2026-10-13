"""Consolida y analiza localmente el piloto Overpass contra rutas ORS.

El módulo no realiza llamadas de red. Todos los informes se generan desde los
JSON y GeoJSON persistidos por el piloto y el almacén local de rutas.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Iterable

from ..cities import load_city_catalog
from .store import RouteStore
from .toll_infrastructure import (
    TollInfrastructure,
    load_infrastructure_catalog,
    match_route_alternatives_to_infrastructure,
    parse_overpass_response,
)


DEFAULT_RAW_DIR = Path("data/raw/tolls")
DEFAULT_PROCESSED_DIR = Path("data/processed/tolls")
DEFAULT_ROUTE_ROOT = Path("data/processed/routes")
DEFAULT_RAW_ROUTE_ROOT = Path("data/raw/routes")


@dataclass(frozen=True)
class InventoryEntry:
    record: TollInfrastructure
    observed_in: tuple[str, ...]
    acquired_at_values: tuple[str, ...]
    osm_timestamps: tuple[str, ...]
    source_boxes: tuple[str, ...]
    conflicting_snapshots: bool


def consolidate_overpass_snapshots(raw_dir: str | Path, processed_dir: str | Path) -> tuple[InventoryEntry, ...]:
    """Lee todos los JSON originales y deduplica por (tipo OSM, ID OSM).

    Las observaciones repetidas conservan todos los nombres de archivo y fechas.
    Ante etiquetas/geometrías distintas se selecciona la observación más
    reciente para el GeoJSON, pero el conflicto queda marcado y auditable.
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    metadata_by_raw: dict[str, dict] = {}
    for metadata_path in sorted(processed_dir.glob("infrastructure_*.metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("raw_file"):
                metadata_by_raw[Path(metadata["raw_file"]).name] = metadata
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"metadatos Overpass inválidos: {metadata_path.name}") from exc

    observations: dict[tuple[str, int], list[tuple[TollInfrastructure, str, str, str, str]]] = {}
    for raw_path in sorted(raw_dir.glob("overpass_*.json")):
        try:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"respuesta Overpass inválida: {raw_path.name}") from exc
        metadata = metadata_by_raw.get(raw_path.name, {})
        acquired_at = str(metadata.get("acquired_at") or "")
        if not acquired_at:
            raise ValueError(f"falta acquired_at en metadatos para {raw_path.name}")
        osm_timestamp = str(payload.get("osm3s", {}).get("timestamp_osm_base") or "")
        bbox = metadata.get("bbox_south_west_north_east", [])
        source_box = ",".join(str(value) for value in bbox)
        for record in parse_overpass_response(payload, acquired_at=acquired_at):
            key = (record.osm_type, record.osm_id)
            observations.setdefault(key, []).append((record, raw_path.name, acquired_at, osm_timestamp, source_box))

    entries = []
    for key, found in sorted(observations.items()):
        found.sort(key=lambda item: (item[2], item[1]))
        canonical = found[-1][0]
        signatures = {(item[0].infrastructure_type,
                       item[0].geometry_parts_lon_lat or (item[0].geometry_lon_lat,), item[0].tags)
                      for item in found}
        entries.append(InventoryEntry(
            canonical,
            tuple(sorted({item[1] for item in found})),
            tuple(sorted({item[2] for item in found})),
            tuple(sorted({item[3] for item in found if item[3]})),
            tuple(sorted({item[4] for item in found if item[4]})),
            len(signatures) > 1,
        ))
    return tuple(entries)


def summarize_query_state(manifest_path: str | Path, state_path: str | Path) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    if state.get("plan_sha256") != manifest.get("plan_sha256"):
        raise ValueError("el estado Overpass y el manifiesto no corresponden al mismo plan")
    regions = state.get("regions", {})
    status_counts = {status: sum(1 for item in regions.values() if item.get("status") == status)
                     for status in ("adquirida", "error")}
    planned = int(manifest.get("query_count", len(manifest.get("regions", []))))
    status_counts["pendiente"] = max(0, planned - sum(status_counts.values()))
    last = state.get("last_execution", {})
    return {
        "planned": planned,
        "acquired": status_counts["adquirida"],
        "failed": status_counts["error"],
        "pending": status_counts["pendiente"],
        "http_requests_last_execution": int(last.get("http_requests", 0)),
        "http_504_count": sum(1 for item in regions.values() if item.get("http_status") == 504),
        "http_429_count": sum(1 for item in regions.values() if item.get("http_status") == 429),
        "regions": regions,
        "manifest": manifest,
    }


def analyze_overpass_pilot(
    *, raw_dir: str | Path = DEFAULT_RAW_DIR,
    processed_dir: str | Path = DEFAULT_PROCESSED_DIR,
    manifest_path: str | Path | None = None,
    state_path: str | Path | None = None,
    route_root: str | Path = DEFAULT_ROUTE_ROOT,
    raw_route_root: str | Path = DEFAULT_RAW_ROUTE_ROOT,
    radius_m: float = 35.0,
) -> tuple[dict, tuple[InventoryEntry, ...], list[dict], list[dict]]:
    processed_dir = Path(processed_dir)
    manifest_path = Path(manifest_path or processed_dir / "overpass_pilot_manifest.json")
    state_path = Path(state_path or processed_dir / "overpass_pilot_state.json")
    state_summary = summarize_query_state(manifest_path, state_path)
    inventory = consolidate_overpass_snapshots(raw_dir, processed_dir)
    routes = RouteStore(route_root, raw_dir=raw_route_root).load_alternatives()
    if len(routes) != 12:
        raise ValueError(f"se esperaban las 12 alternativas ORS locales; se encontraron {len(routes)}")
    city_names = {city.city_id: city.name for city in load_city_catalog()}
    strategy_by_route = _load_route_strategies(route_root, raw_route_root)
    records = tuple(entry.record for entry in inventory)
    matches = match_route_alternatives_to_infrastructure(routes, records, radius_m=radius_m)
    match_by_route: dict[str, list] = {}
    for match in matches:
        match_by_route.setdefault(match.route_id, []).append(match)

    inventory_rows = []
    for entry in inventory:
        record = entry.record
        tags = dict(record.tags)
        inventory_rows.append({
            "osm_type": record.osm_type, "osm_id": record.osm_id,
            "stable_id": record.stable_id, "infrastructure_type": record.infrastructure_type,
            "name": record.name or "", "operator": record.operator or "",
            "road_reference": record.road_reference or "", "direction": record.direction or "",
            "toll_tag": tags.get("toll", ""),
            "source": record.source, "license": "ODbL",
            "attribution": "© OpenStreetMap contributors",
            "first_longitude": record.geometry_lon_lat[0][0], "first_latitude": record.geometry_lon_lat[0][1],
            "geometry_vertex_count": sum(len(part) for part in (record.geometry_parts_lon_lat or (record.geometry_lon_lat,))),
            "observations": len(entry.observed_in), "observed_in": ";".join(entry.observed_in),
            "acquired_at_values": ";".join(entry.acquired_at_values),
            "osm_data_timestamps": ";".join(entry.osm_timestamps),
            "source_bounding_boxes": ";".join(entry.source_boxes),
            "conflicting_snapshots": entry.conflicting_snapshots,
        })

    route_rows = []
    manifest_regions = {region["region_id"]: region for region in state_summary["manifest"].get("regions", [])}
    for route in sorted(routes, key=lambda r: (r.origin_id, r.destination_id, strategy_by_route.get(r.alternative_id, ""))):
        strategy = strategy_by_route.get(route.alternative_id, "desconocida")
        relevant_regions = [region for region in manifest_regions.values()
                            if route.alternative_id in region.get("route_ids", [])]
        acquired_region_ids = {region_id for region_id, value in state_summary["regions"].items()
                               if value.get("status") == "adquirida"}
        covered = sum(1 for region in relevant_regions if region.get("region_id") in acquired_region_ids)
        route_matches = sorted(match_by_route.get(route.alternative_id, []),
                               key=lambda match: (match.route_fraction, match.infrastructure_id))
        candidates = route_matches or [None]
        for match in candidates:
            record = next((item.record for item in inventory if match and item.record.stable_id == match.infrastructure_id), None)
            tags = dict(record.tags) if record else {}
            route_rows.append({
                "route_id": route.alternative_id,
                "origin_id": route.origin_id, "origin_name": city_names.get(route.origin_id, route.origin_id),
                "destination_id": route.destination_id,
                "destination_name": city_names.get(route.destination_id, route.destination_id),
                "strategy": strategy, "geometry_points": len(route.geometry_lon_lat or ()),
                "planned_regions_for_route": len(relevant_regions),
                "acquired_regions_for_route": covered,
                "region_coverage_fraction": covered / len(relevant_regions) if relevant_regions else 0.0,
                "infrastructure_id": match.infrastructure_id if match else "",
                "infrastructure_type": record.infrastructure_type if record else "",
                "name": record.name or "" if record else "",
                "operator": record.operator or "" if record else "",
                "road_reference": record.road_reference or "" if record else "",
                "toll_tag": tags.get("toll", ""),
                "minimum_distance_m": match.minimum_distance_m if match else "",
                "route_fraction": match.route_fraction if match else "",
                "aligned_route_length_m": match.aligned_route_length_m if match else "",
                "evidence_level": match.confidence if match else "sin_candidato_en_inventario_adquirido",
                "evidence": ";".join(match.evidence) if match else "ningún elemento adquirido dentro del radio",
                "direction_evidence": match.direction_evidence if match else "no aplica",
                "toll_confirmed": False,
                "manual_review_required": True if match else covered < len(relevant_regions),
                "ap68_reference_match": bool(record and (record.road_reference or "").upper().replace(" ", "") == "AP-68"),
            })

    type_counts: dict[str, int] = {}
    operator_counts: dict[str, int] = {}
    road_counts: dict[str, int] = {}
    for row in inventory_rows:
        for mapping, key in ((type_counts, row["infrastructure_type"]),
                             (operator_counts, row["operator"] or "sin_operador"),
                             (road_counts, row["road_reference"] or "sin_referencia")):
            mapping[key] = mapping.get(key, 0) + 1
    summary = {
        "query_state": state_summary,
        "raw_response_files": len(list(Path(raw_dir).glob("overpass_*.json"))),
        "raw_elements_total": _count_raw_elements(raw_dir),
        "normalized_observations": sum(row["observations"] for row in inventory_rows),
        "unique_infrastructure": len(inventory_rows),
        "duplicates_removed": sum(row["observations"] - 1 for row in inventory_rows),
        "snapshot_conflicts": sum(bool(row["conflicting_snapshots"]) for row in inventory_rows),
        "types": type_counts, "operators": operator_counts, "roads": road_counts,
        "route_alternatives": len(routes), "route_matches": len(matches),
        "route_matches_by_level": _count_by(matches, "confidence"),
        "ors_routes_with_extra_info": _count_ors_extra_info(raw_route_root),
        "ap68_matches_by_route": {
            route_id: sorted({row["infrastructure_id"] for row in route_rows
                              if row["route_id"] == route_id and row["ap68_reference_match"]})
            for route_id in sorted({row["route_id"] for row in route_rows if row["ap68_reference_match"]})
        },
        "radius_m": radius_m,
        "source_note": "OSM/Overpass; inventario parcial limitado a respuestas persistidas",
    }
    return summary, inventory, inventory_rows, route_rows


def write_overpass_pilot_report(summary: dict, inventory: Iterable[InventoryEntry], inventory_rows: list[dict],
                                route_rows: list[dict], output_dir: str | Path) -> tuple[Path, Path, Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inventory_csv = output / "overpass_inventory.csv"
    matches_csv = output / "overpass_route_matches.csv"
    catalog_geojson = output / "overpass_inventory.geojson"
    report_md = output / "overpass_pilot_analysis.md"
    _write_csv(inventory_csv, inventory_rows)
    _write_csv(matches_csv, route_rows)
    features = []
    for entry in inventory:
        record = entry.record
        parts = record.geometry_parts_lon_lat or (record.geometry_lon_lat,)
        is_point = len(record.geometry_lon_lat) == 1 and len(parts) == 1
        features.append({
            "type": "Feature", "id": record.stable_id,
            "geometry": ({"type": "Point", "coordinates": record.geometry_lon_lat[0]} if is_point else
                         {"type": "LineString", "coordinates": parts[0]} if len(parts) == 1 else
                         {"type": "MultiLineString", "coordinates": parts}),
            "properties": {
                "osm_type": record.osm_type, "osm_id": record.osm_id,
                "infrastructure_type": record.infrastructure_type, "name": record.name,
                "operator": record.operator, "road_reference": record.road_reference,
                "direction": record.direction, "tags": dict(record.tags),
                "source": record.source, "license": "ODbL",
                "attribution": "© OpenStreetMap contributors", "observed_in": list(entry.observed_in),
                "acquired_at_values": list(entry.acquired_at_values),
                "osm_data_timestamps": list(entry.osm_timestamps),
                "source_bounding_boxes": list(entry.source_boxes),
                "conflicting_snapshots": entry.conflicting_snapshots,
            },
        })
    catalog_geojson.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(_render_markdown(summary, route_rows), encoding="utf-8")
    return inventory_csv, matches_csv, catalog_geojson, report_md


def _load_route_strategies(route_root: str | Path, raw_route_root: str | Path) -> dict[str, str]:
    store = RouteStore(route_root, raw_dir=raw_route_root)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    strategies = {}
    for entry in state.get("requests", {}).values():
        if entry.get("status") != "adquirida":
            continue
        raw_path = Path(entry["raw_file"])
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        body = raw.get("request", {}).get("body", {})
        avoided = body.get("options", {}).get("avoid_features", [])
        strategy = "avoid_tolls" if "tollways" in avoided else str(body.get("options", {}).get("profile_params", {}).get("weighting", "fastest"))
        for alternative_id in entry.get("active_alternative_ids", []):
            if alternative_id in strategies:
                raise ValueError(f"estrategia duplicada para {alternative_id}")
            strategies[alternative_id] = strategy
    return strategies


def _count_raw_elements(raw_dir: str | Path) -> int:
    total = 0
    for path in Path(raw_dir).glob("overpass_*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        total += len(payload.get("elements", []))
    return total


def _count_ors_extra_info(raw_route_root: str | Path) -> int:
    count = 0
    for path in Path(raw_route_root).glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for feature in payload.get("response", {}).get("features", []):
            if "extras" in feature.get("properties", {}):
                count += 1
    return count


def _count_by(records, field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        key = str(getattr(record, field))
        result[key] = result.get(key, 0) + 1
    return result


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def _render_markdown(summary: dict, route_rows: list[dict]) -> str:
    state = summary["query_state"]
    remaining_regions = state["failed"] + state["pending"]
    ap68_coverage: dict[str, tuple[int, int]] = {}
    for row in route_rows:
        if ({row["origin_id"], row["destination_id"]} == {"bizkaia", "zaragoza"}
                and row["strategy"] == "fastest"):
            pair = f"{row['origin_name']} → {row['destination_name']}"
            ap68_coverage[pair] = (int(row["acquired_regions_for_route"]),
                                   int(row["planned_regions_for_route"]))
    if ap68_coverage:
        coverage_text = "; ".join(
            f"{pair}: {acquired}/{planned} celdas"
            for pair, (acquired, planned) in sorted(ap68_coverage.items())
        )
    else:
        coverage_text = "sin cobertura AP-68 identificada en las rutas rápidas"
    lines = [
        "# Análisis offline del piloto geográfico de peajes",
        "",
        "Generado desde archivos locales; el script no consulta APIs. El catálogo y los CSV contienen datos derivados de OpenStreetMap y permanecen en rutas ignoradas por Git mientras se revisa la redistribución.",
        "",
        "## Estado de las consultas",
        "",
        f"- Consultas previstas: {state['planned']}",
        f"- Regiones completadas: {state['acquired']}",
        f"- Regiones fallidas: {state['failed']}",
        f"- Regiones pendientes: {state['pending']}",
        f"- Solicitudes HTTP registradas en la última ejecución: {state['http_requests_last_execution']}",
        f"- Fallos HTTP 504: {state['http_504_count']}; HTTP 429: {state['http_429_count']}",
        "",
        f"El estado local registra {state['acquired']} regiones completadas, {state['failed']} fallidas y {state['pending']} pendientes; no acredita que terminara el plan de {state['planned']} consultas. Se encontraron {summary['raw_response_files']} respuestas crudas locales.",
        "",
        "## Inventario consolidado",
        "",
        f"- Elementos crudos recibidos: {summary['raw_elements_total']} en {summary['raw_response_files']} archivo(s).",
        f"- Observaciones normalizadas: {summary['normalized_observations']}; IDs OSM únicos: {summary['unique_infrastructure']}; duplicados eliminados: {summary['duplicates_removed']}.",
        f"- Snapshots con atributos/geometría discordantes: {summary['snapshot_conflicts']}.",
        "- Tipos: " + ", ".join(f"`{k}` {v}" for k, v in sorted(summary["types"].items())),
        "- Operadores: " + ", ".join(f"`{k}` {v}" for k, v in sorted(summary["operators"].items())),
        "- Referencias viales: " + ", ".join(f"`{k}` {v}" for k, v in sorted(summary["roads"].items())),
        "",
        "El inventario describe objetos OSM etiquetados y cubiertos por las cajas ya adquiridas; no constituye un censo de estaciones ni prueba de completitud en España.",
        "",
        "## Cruce con rutas ORS",
        "",
        f"Se compararon {summary['route_alternatives']} geometrías locales con un radio de {summary['radius_m']:.0f} m. Se encontraron {summary['route_matches']} relaciones ruta–objeto: "
        + ", ".join(f"`{k}` {v}" for k, v in sorted(summary["route_matches_by_level"].items())) + ".",
        f"Las respuestas ORS locales con `extra_info` son {summary['ors_routes_with_extra_info']}/{summary['route_alternatives']}; el análisis se basa en geometrías y etiquetas OSM del snapshot, no en IDs de vía retornados por ORS.",
        "- `candidato_proximidad`: solo cercanía geométrica; no demuestra tránsito.",
        "- `coincidencia_vial_probable`: vía `toll=yes` alineada con parte de la geometría dentro de 10 m durante al menos 250 m; todavía requiere verificar calzada, sentido y conexión.",
        "- No se asignan tarifas: la geometría y las etiquetas OSM no prueban estaciones de entrada/salida ni cobertura completa del trayecto.",
        "",
        "### Rutas con candidatos",
        "",
        "| Origen → destino | Estrategia | Objeto | Ref. | Distancia mínima | Alineamiento aprox. | Evidencia | Cobertura de celdas |",
        "|---|---|---|---|---:|---:|---|---:|",
    ]
    seen = set()
    for row in route_rows:
        if not row["infrastructure_id"]:
            continue
        key = (row["route_id"], row["infrastructure_id"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"| {row['origin_name']} → {row['destination_name']} | {row['strategy']} | {row['infrastructure_id']} | {row['road_reference'] or '—'} | "
            f"{float(row['minimum_distance_m']):.1f} m | {float(row['aligned_route_length_m']):.0f} m | {row['evidence_level']} | "
            f"{row['acquired_regions_for_route']}/{row['planned_regions_for_route']} |"
        )
    lines.extend([
        "",
        "Los detalles por alternativa, incluidos los casos sin candidato en el inventario adquirido, están en `overpass_route_matches.csv`. Un caso sin candidato solo significa que ninguna geometría presente en las regiones adquiridas quedó dentro del radio; no significa ruta sin peaje.",
        "",
        "## Prioridad AP-68: Bilbao ↔ Zaragoza",
        "",
    ])
    ap68 = [row for row in route_rows if row["origin_id"] in {"bizkaia", "zaragoza"}
            and row["destination_id"] in {"bizkaia", "zaragoza"} and row["ap68_reference_match"]]
    if ap68:
        for row in ap68:
            lines.append(f"- {row['origin_name']} → {row['destination_name']} ({row['strategy']}): {row['infrastructure_id']}, "
                         f"distancia mínima {float(row['minimum_distance_m']):.1f} m, alineamiento aproximado "
                         f"{float(row['aligned_route_length_m']):.0f} m, nivel `{row['evidence_level']}`.")
    else:
        lines.append("No hay coincidencias AP-68 identificadas para estos arcos dentro de las regiones descargadas.")
    lines.extend([
        "",
        "Las geometrías `fastest` se alinean aproximadamente 290,9 km con la relación AP-68 en ambos sentidos. Las candidatas `avoid_tolls` también muestran alineamientos locales de unos 332 m y 259 m, respectivamente. Es una señal consistente con uso extenso de AP-68 en `fastest` y una intersección breve en `avoid_tolls`; esa intersección puede corresponder a un enlace o tramo de incorporación y necesita revisión cartográfica. El valor es longitud geométrica aproximada, no longitud tarifada.",
        "El objeto relation AP-68 y sus vías miembro pueden describir partes coincidentes del mismo corredor; son IDs OSM diferentes, así que se conservan en el inventario, pero no deben sumarse como cobros independientes.",
        f"El resultado no demuestra que una ruta use o evite toda la AP-68: cobertura observada de las rutas rápidas: {coverage_text}. No se identificaron accesos, salidas, sentido tarifario ni recorrido completo sujeto a cobro.",
        "",
        "## Conclusión sobre utilidad",
        "",
        "Overpass sirve para formar un inventario geográfico reutilizable y generar candidatos de asociación. No entrega tarifas ni garantiza que las etiquetas estén completas o vigentes. El cruce espacial puede reducir la revisión manual, pero calcular el peaje requiere resolver segmentos y accesos/salidas contra tarifarios oficiales y demostrar que la ruta quedó cubierta de extremo a extremo.",
        "",
        f"Para 47 ciudades, no conviene consultar Overpass por cada arco dirigido. Conviene adquirir y versionar una sola vez el inventario de infraestructura por regiones/corredores, reutilizarlo para ambos sentidos y todas las alternativas, y conservar el estado desconocido cuando falten cobertura o evidencia. Quedan {remaining_regions} regiones no completadas ({state['failed']} fallida(s) y {state['pending']} pendiente(s)); se deben reanudar con lotes pequeños, revisar cobertura y deduplicar las respuestas.",
        "",
        "## Archivos regenerables",
        "",
        "- `overpass_inventory.geojson`: catálogo único con procedencia de todos los snapshots disponibles.",
        "- `overpass_inventory.csv`: clasificación por tipo, operador y referencia vial.",
        "- `overpass_route_matches.csv`: cruce detallado de las 12 alternativas, también con rutas sin candidato.",
        "- `overpass_pilot_analysis.md`: este resumen.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consolida el piloto Overpass y lo cruza offline con rutas ORS.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--route-root", type=Path, default=DEFAULT_ROUTE_ROOT)
    parser.add_argument("--raw-route-root", type=Path, default=DEFAULT_RAW_ROUTE_ROOT)
    parser.add_argument("--radius-m", type=float, default=35.0)
    args = parser.parse_args(argv)
    try:
        summary, inventory, inventory_rows, route_rows = analyze_overpass_pilot(
            raw_dir=args.raw_dir, processed_dir=args.processed_dir,
            route_root=args.route_root, raw_route_root=args.raw_route_root, radius_m=args.radius_m,
        )
        outputs = write_overpass_pilot_report(summary, inventory, inventory_rows, route_rows, args.processed_dir)
        print(json.dumps({
            "planned": summary["query_state"]["planned"], "acquired": summary["query_state"]["acquired"],
            "failed": summary["query_state"]["failed"], "pending": summary["query_state"]["pending"],
            "unique_infrastructure": summary["unique_infrastructure"], "route_matches": summary["route_matches"],
            "outputs": [str(path) for path in outputs],
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI smoke tested
    raise SystemExit(main())
