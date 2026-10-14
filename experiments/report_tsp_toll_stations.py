"""Genera CSV, resumen y GeoJSON offline de estaciones OSM y rutas piloto."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.tsp.etl.store import RouteStore
from src.tsp.etl.toll_stations import load_station_records, match_stations_to_routes


PILOT_PAIRS = {("madrid", "toledo"), ("bizkaia", "zaragoza"), ("zaragoza", "bizkaia")}
OFFICIAL_AP68_STATIONS = (
    "Bilbao", "Arrigorriaga", "Llodio", "Ziorroga", "Altube", "Subijana",
    "Enlace AP-1", "Zambrana", "Haro", "Cenicero", "Navarrete", "Logroño",
    "Recajo", "Agoncillo", "Lodosa", "Calahorra", "Alfaro", "Enlace AP-15",
    "Tudela", "Gallur", "Alagón 272", "Zaragoza",
)


def run_report(inventory: Path, route_store: Path, output: Path, *, radius_m: float = 100.0,
               enriched_routes: Path | None = None) -> dict:
    stations = load_station_records(inventory)
    routes = tuple(route for route in RouteStore(route_store).load_alternatives()
                   if (route.origin_id, route.destination_id) in PILOT_PAIRS
                   and dict(route.routing_parameters).get("strategy") == "fastest"
                   and route.geometry_lon_lat)
    routes = tuple(sorted(routes, key=lambda route: (route.origin_id, route.destination_id)))
    enriched_path = enriched_routes or Path("data/processed/tolls/ors_extra_info/enriched_routes.json")
    enriched = _load_enriched(enriched_path)
    segments_by_route = {row["previous_route_id"]: tuple(
                            tuple(tuple(point) for point in section["geometry_coordinates"])
                            for section in row.get("toll_sections", [])
                            if len(section.get("geometry_coordinates", [])) >= 2)
                         for row in enriched
                         if row.get("geometry_equal_to_previous") is True and row.get("previous_route_id")}
    matches = match_stations_to_routes(stations, routes, candidate_radius_m=radius_m,
                                       toll_segments_by_route_id=segments_by_route or None)
    output.mkdir(parents=True, exist_ok=True)
    _write_stations(output / "toll_stations.csv", stations)
    _write_matches(output / "station_route_candidates.csv", matches)
    _write_review_geojson(output / "toll_station_review.geojson", stations, routes, matches, enriched)
    _write_overpass_plan(output / "overpass_station_followup_plan.json", stations, matches)
    summary = _make_summary(stations, routes, matches, radius_m)
    (output / "toll_stations_summary.md").write_text(summary, encoding="utf-8")
    return {"stations": len(stations), "routes": len(routes), "route_station_candidates": len(matches),
            "output": str(output)}


def _write_overpass_plan(path: Path, stations, matches) -> None:
    ids = sorted({row["osm_id"] for row in stations if row["osm_type"] == "node"})
    known_query = f"[out:json][timeout:25];node(id:{','.join(map(str, ids))});out body;"
    ap68_matches = [row for row in matches if row["origin_id"] in {"bizkaia", "zaragoza"}
                    and row["destination_id"] in {"bizkaia", "zaragoza"}]
    centers = sorted({(round(row["station_lat"], 6), round(row["station_lon"], 6))
                      for row in ap68_matches})
    around_terms = "".join(
        f'nwr(around:100,{lat:.6f},{lon:.6f})["barrier"="toll_booth"];'
        f'nwr(around:100,{lat:.6f},{lon:.6f})["highway"="toll_gantry"];'
        f'nwr(around:100,{lat:.6f},{lon:.6f})["toll"="yes"];'
        for lat, lon in centers
    )
    local_query = f"[out:json][timeout:25];({around_terms});out body geom;"
    payload = {"schema_version": 1, "execution": "plan_only", "requests_planned": 2,
        "max_http_requests": 2, "automatic_retries": 0,
        "queries": [
            {"purpose": "refrescar etiquetas completas de IDs de nodos existentes", "query": known_query,
             "osm_node_ids": ids, "http_budget": 1, "status": "pending"},
            {"purpose": "buscar puestos/gantries/vías en áreas AP-68 cercanas a candidatos",
             "query": local_query, "centers_lat_lon": [list(center) for center in centers],
             "radius_m": 100, "http_budget": 1, "status": "pending"},
        ],
        "limitations": ["No se ejecutaron consultas.",
            "Las respuestas ORS actuales no contienen osmId porque no fue solicitado; solo aportan tollways y waycategory.",
            "Una búsqueda alrededor de estaciones no confirma el paso ni cubre todos los accesos."],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_stations(path: Path, stations: tuple[dict, ...]) -> None:
    columns = ("osm_type", "osm_id", "osm_url", "infrastructure_type", "name", "operator", "ref",
               "highway", "direction", "longitude", "latitude", "coordinate_kind", "address_tags",
               "tags", "geometry_type", "source", "license", "observed_in", "acquired_at_values",
               "osm_data_timestamps", "source_bounding_boxes")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in stations:
            writer.writerow({key: json.dumps(row.get(key), ensure_ascii=False, sort_keys=True)
                             if isinstance(row.get(key), (dict, list)) else row.get(key)
                             for key in columns})


def _write_matches(path: Path, matches: tuple[dict, ...]) -> None:
    columns = ("origin_id", "destination_id", "route_id", "station_id", "name", "operator", "road_ref",
               "station_lon", "station_lat", "distance_to_route_m", "nearest_route_lon", "nearest_route_lat",
               "route_fraction", "distance_scope", "route_distance_km", "route_road_refs", "state", "evidence",
               "toll_amount_eur", "toll_verification")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in matches:
            writer.writerow({key: json.dumps(row.get(key), ensure_ascii=False) if isinstance(row.get(key), list)
                             else row.get(key) for key in columns})


def _write_review_geojson(path: Path, stations, routes, matches, enriched) -> None:
    by_station = {}
    for match in matches:
        by_station.setdefault(match["station_id"], []).append({
            "route_id": match["route_id"], "origin_id": match["origin_id"],
            "destination_id": match["destination_id"], "distance_m": round(match["distance_to_route_m"], 2),
            "fraction": round(match["route_fraction"], 6), "state": match["state"],
        })
    features = []
    enriched_by_previous = {row.get("previous_route_id"): row for row in enriched
                            if row.get("previous_route_id")}
    for route in routes:
        extra_row = enriched_by_previous.get(route.alternative_id)
        if extra_row and extra_row.get("geometry_equal_to_previous") is True:
            extra_status = "ORS extra_info real; geometría igual a la anterior"
        elif extra_row:
            extra_status = "ORS extra_info real; geometría distinta, no se vincula"
        else:
            extra_status = "sin respuesta ORS enriquecida real disponible"
        features.append({"type": "Feature", "geometry": {"type": "LineString",
            "coordinates": [list(point) for point in route.geometry_lon_lat]},
            "properties": {"kind": "route", "route_id": route.alternative_id,
                "origin_id": route.origin_id, "destination_id": route.destination_id,
                "strategy": dict(route.routing_parameters).get("strategy"),
                "distance_km": route.distance_km, "duration_hours": route.duration_hours,
                "road_references": list(route.road_references),
                "extra_info": extra_status,
                "toll_verification": "UNKNOWN"}})
    for row in enriched:
        previous_route_id = row.get("previous_route_id")
        same_geometry = row.get("geometry_equal_to_previous") is True
        for segment_index, section in enumerate(row.get("toll_sections", [])):
            coords = section.get("geometry_coordinates") or []
            if len(coords) < 2:
                continue
            features.append({"type": "Feature", "geometry": {"type": "LineString",
                "coordinates": coords}, "properties": {
                    "kind": "ors_tollways_segment", "route_id": row.get("route_id"),
                    "previous_route_id": previous_route_id, "geometry_matches_previous": same_geometry,
                    "segment_index": segment_index, "start_index": section.get("start_index"),
                    "end_index": section.get("end_index"), "osm_way_ids": section.get("osm_way_ids", []),
                    "waycategory_names": section.get("waycategory_names", []),
                    "instruction_names": section.get("instruction_names", []),
                    "instruction_refs": section.get("instruction_refs", []),
                    "start_position_km_approx": section.get("start_position_km_approx"),
                    "end_position_km_approx": section.get("end_position_km_approx"),
                    "length_km_approx": section.get("length_km_approx"),
                    "position_method": section.get("position_method"),
                    "classification": "ORS tollways=1; cartographic evidence only",
                    "toll_verification": "UNKNOWN"}})
    for station in stations:
        props = {key: station.get(key) for key in ("osm_type", "osm_id", "osm_url", "name", "operator",
                "ref", "highway", "direction", "tags", "source", "license", "coordinate_kind")}
        props.update({"kind": "toll_station", "match_status": "CANDIDATE_NEAR_ROUTE"
                      if by_station.get(f"osm:{station['osm_type']}/{station['osm_id']}") else "NOT_NEAR_PILOT",
                      "route_candidates": by_station.get(f"osm:{station['osm_type']}/{station['osm_id']}", []),
                      "toll_verification": "UNKNOWN"})
        features.append({"type": "Feature", "geometry": station["geometry"], "properties": props})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_summary(stations, routes, matches, radius_m: float) -> str:
    booths = [row for row in stations if row["infrastructure_type"] == "toll_booth"]
    named = sum(bool(row["name"]) for row in booths)
    operators = sum(bool(row["operator"]) for row in booths)
    references = sum(bool(row["ref"]) for row in booths)
    coordinates = sum(row["longitude"] is not None and row["latitude"] is not None for row in booths)
    addresses = sum(bool(row["address_tags"]) for row in booths)
    ids = [row["osm_id"] for row in booths]
    alagon = [row for row in booths if (row["name"] or "").casefold().replace("ó", "o") == "peaje de alagon"]
    route_table = []
    for route in routes:
        matches_for_route = [match for match in matches if match["route_id"] == route.alternative_id]
        closest = min(matches_for_route, key=lambda row: row["distance_to_route_m"]) if matches_for_route else None
        nearest_distance = f"{closest['distance_to_route_m']:.1f} m" if closest else "—"
        route_table.append(f"| {route.origin_id} → {route.destination_id} | {route.distance_km:.2f} | "
                           f"{', '.join(route.road_references) or 'sin refs'} | "
                           f"{closest['station_id'] if closest else '—'} | "
                           f"{nearest_distance} | "
                           f"{closest['state'] if closest else 'sin candidata'} | UNKNOWN |")
    lines = ["# Estaciones de peaje OSM: inspección local", "",
        "Informe generado desde el GeoJSON consolidado local y las geometrías Directions ya guardadas; sin llamadas de red.", "",
        f"- Estaciones toll_booth: **{len(booths)}**.", f"- Con nombre: **{named}**; operador: **{operators}**; referencia: **{references}**.",
        f"- Coordenadas puntuales WGS84 válidas: **{coordinates}**; etiquetas addr:*: **{addresses}**.",
        f"- Identificadores OSM repetidos: **{len(ids) - len(set(ids))}**.",
        f"- Candidatos route–station dentro de {radius_m:g} m: **{len(matches)}**.",
        f"- Respuestas ORS enriquecidas presentes: **{_real_enriched_count()}** (no se infiere ausencia de peaje).", "",
        "## Estaciones",
        "| OSM | Nombre | Operador | Ref. | Highway | Sentido | Coordenadas (lon, lat) | Dirección postal | Enlace |",
        "|---|---|---|---|---|---|---|---|---|"]
    for row in booths:
        address = "; ".join(f"{key}={value}" for key, value in row["address_tags"].items()) or "—"
        coords = (f"{row['longitude']:.7f}, {row['latitude']:.7f}" if row["longitude"] is not None else "geometría")
        lines.append(f"| {row['osm_type']}/{row['osm_id']} | {row['name'] or '—'} | {row['operator'] or '—'} | "
                     f"{row['ref'] or '—'} | {row['highway'] or '—'} | {row['direction'] or '—'} | "
                     f"{coords} | {address} | [OSM]({row['osm_url']}) |")
    lines.extend(["", "Los dos nodos llamados **Peaje de Alagon** se conservan por separado: "
        + (", ".join(f"{row['osm_id']} ({row['longitude']:.6f}, {row['latitude']:.6f})" for row in alagon)
          if alagon else "no aparecen con ese nombre en este snapshot") + ". Sus IDs distintos y posiciones cercanas pueden corresponder a instalaciones/carriles diferentes; no se agrupan sin comprobar relaciones y geometría vial.",
        "", "## Todos los candidatos por proximidad", "",
        "Cada fila es una relación espacial candidata. La distancia de 0 m indica que la geometría guardada pasa por la coordenada del nodo, no que el vehículo haya usado una cabina o pagado en ella.", "",
        "| Ruta rápida | Nodo OSM | Nombre | Coordenadas (lon, lat) | Distancia | Fracción de ruta | Estado |",
        "|---|---|---|---|---:|---:|---|"])
    for match in matches:
        lines.append(
            f"| {match['origin_id']} → {match['destination_id']} | {match['station_id']} | "
            f"{match['name'] or '—'} | {match['station_lon']:.7f}, {match['station_lat']:.7f} | "
            f"{match['distance_to_route_m']:.2f} m | {match['route_fraction']:.6f} | {match['state']} |"
        )
    lines.extend([
        "", "## Rutas piloto y estaciones cercanas", "",
        "La distancia se calcula al trazado completo; no demuestra que se haya pasado por una cabina. Los estados son candidatos, no certificaciones.", "",
        "| Origen → destino | Ruta km | Referencias de ruta | Estación más cercana | Distancia | Estado | Peaje |",
        "|---|---:|---|---|---:|---|---|"])
    lines.extend(route_table)
    lines.extend(["", "## Tarifario AP-68", "",
        "El tarifario oficial lista estaciones de referencia para la matriz de ligeros: "
        + ", ".join(OFFICIAL_AP68_STATIONS) + ". El PDF publica 39,90 € para Bilbao–Zaragoza en esa tabla, vigente desde 2026-01-01; el valor es la tarifa del par nominal, no una tarifa asignada automáticamente a estas geometrías.",
        "En el snapshot local, solo dos objetos OSM tienen nombre: ambos dicen Peaje de Alagon. La semejanza con ‘Alagón 272’ es candidata de nombre y zona, no correspondencia validada de entrada/salida. Los otros nodos no tienen nombre ni referencia, por lo que requieren consulta puntual de etiquetas y contraste con mapa oficial/operador.",
        "", "## Madrid–Toledo", "",
        "ORS extra_info real marca toda la geometría de Madrid–Toledo con tollways=0 (0.00 km señalados como peaje). Esto es evidencia cartográfica útil para análisis exploratorio, pero no certifica peaje monetario cero: faltan cobertura independiente completa de concesiones/accesos y verificación documental del recorrido.",
        "", "## Limitaciones y siguiente evidencia", "",
        "- El inventario cubre solo las regiones Overpass adquiridas: no es un censo. Hay una región fallida HTTP 504 y 32 pendientes según el manifiesto persistido.",
        "- La proximidad se computa al polyline completa con radio de búsqueda configurable; no se adjudica tránsito a partir de esa distancia.",
        "- ORS extra_info está disponible para las tres rutas. Marca segmentos tollways y categorías, pero no devuelve estaciones ni tarifas; osmId no fue solicitado en estos snapshots.",
        "- Para verificar cobro: vincular vía/estación con entrada, salida, sentido, clase ligera, tarifa ordinaria, vigencia (2026-10-12), y confirmar que no haya otro peaje fuera de AP-68.",
        "- No se asigna tarifa monetaria ni `VERIFIED_ZERO` a ninguna ruta.",
        "- Las filas OSM se derivan de OpenStreetMap y permanecen en directorios locales ignorados por Git hasta cerrar la revisión de licencia/redistribución.", ""])
    return "\n".join(lines)


def _real_enriched_count() -> int:
    path = Path("data/processed/routes/enriched/route_alternatives.csv")
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def _load_enriched(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("routes"), list):
        raise ValueError("informe de rutas ORS enriquecidas inválido")
    return payload["routes"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=Path("data/processed/tolls/overpass_inventory.geojson"))
    parser.add_argument("--route-store", type=Path, default=Path("data/processed/routes"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/tolls/station_review"))
    parser.add_argument("--radius-m", type=float, default=100.0)
    parser.add_argument("--enriched-routes", type=Path,
                        default=Path("data/processed/tolls/ors_extra_info/enriched_routes.json"))
    args = parser.parse_args(argv)
    print(json.dumps(run_report(args.inventory, args.route_store, args.output,
                                radius_m=args.radius_m, enriched_routes=args.enriched_routes),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
