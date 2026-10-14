"""Extracción y cruce offline de estaciones OSM con geometrías de ruta.

La proximidad solo produce candidatos. El módulo no certifica cobros ni
asigna tarifas.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from ..alternatives import RouteAlternative


STATION_TYPES = {"toll_booth", "toll_gantry"}
MATCH_STATES = {"CANDIDATE_NEAR_ROUTE", "MATCHED_ROAD", "POSSIBLE_PASSAGE", "PASSAGE_VERIFIED"}


def load_station_records(path: str | Path) -> tuple[dict, ...]:
    """Carga objetos de peaje del GeoJSON consolidado sin perder etiquetas.

    Los nodos conservan su coordenada exacta. Para instalaciones no puntuales
    se conserva la geometría original; lat/lon queda vacío y no se inventa un
    punto representativo.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("inventario OSM debe ser GeoJSON FeatureCollection")
    rows = {}
    for feature in payload["features"]:
        props = feature.get("properties") or {}
        if props.get("infrastructure_type") not in STATION_TYPES:
            continue
        osm_type, osm_id = props.get("osm_type"), props.get("osm_id")
        if osm_type not in {"node", "way", "relation"} or type(osm_id) is not int or osm_id <= 0:
            raise ValueError("estación con tipo o ID OSM inválido")
        geometry = feature.get("geometry") or {}
        geometry_type, coordinates = geometry.get("type"), geometry.get("coordinates")
        if geometry_type == "Point":
            points = (coordinates,)
            longitude, latitude = _coordinate(coordinates)
            coordinate_kind = "nodo_osm_exacto" if osm_type == "node" else "punto_geometrico_osm"
        else:
            points = _flatten_coordinates(geometry_type, coordinates)
            longitude = latitude = None
            coordinate_kind = "geometria_original_sin_centro_calculado"
        tags = props.get("tags") or {}
        if not isinstance(tags, dict):
            raise ValueError("etiquetas OSM deben ser un objeto")
        key = (osm_type, osm_id)
        if key in rows:
            # Un mismo objeto repetido en la entrada se consolida por identidad.
            previous = rows[key]
            if previous["tags"] != tags or previous["geometry"] != geometry:
                raise ValueError(f"objeto OSM conflictivo duplicado: {osm_type}/{osm_id}")
            continue
        rows[key] = {
            "osm_type": osm_type, "osm_id": osm_id,
            "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "infrastructure_type": props.get("infrastructure_type"),
            "name": props.get("name") or tags.get("name"),
            "operator": props.get("operator") or tags.get("operator"),
            "ref": props.get("road_reference") or tags.get("ref"),
            "highway": tags.get("highway"),
            "direction": props.get("direction") or tags.get("direction") or tags.get("oneway"),
            "address_tags": {key: value for key, value in tags.items() if key.startswith("addr:")},
            "tags": tags, "geometry_type": geometry_type,
            "geometry": geometry, "geometry_points": points,
            "longitude": longitude, "latitude": latitude,
            "coordinate_kind": coordinate_kind,
            "source": props.get("source"), "license": props.get("license"),
            "observed_in": props.get("observed_in", []),
            "acquired_at_values": props.get("acquired_at_values", []),
            "osm_data_timestamps": props.get("osm_data_timestamps", []),
            "source_bounding_boxes": props.get("source_bounding_boxes", []),
        }
    return tuple(rows[key] for key in sorted(rows))


def match_stations_to_routes(
    stations: Iterable[dict], routes: Iterable[RouteAlternative], *, candidate_radius_m: float = 100.0,
    toll_segments_by_route_id: dict[str, tuple[tuple[tuple[float, float], ...], ...]] | None = None,
) -> tuple[dict, ...]:
    """Calcula distancia, punto más próximo y posición relativa en cada ruta.

    `MATCHED_ROAD` requiere coincidencia explícita entre `ref` de OSM y una
    referencia de ruta. `POSSIBLE_PASSAGE` y `PASSAGE_VERIFIED` se reservan
    para evidencia adicional revisada; esta rutina nunca los asigna.
    """
    if not math.isfinite(candidate_radius_m) or candidate_radius_m <= 0:
        raise ValueError("candidate_radius_m debe ser finito y positivo")
    output = []
    for route in routes:
        geometry = route.geometry_lon_lat or ()
        if len(geometry) < 2:
            raise ValueError(f"geometría ausente para {route.alternative_id}")
        for station in stations:
            point = (station.get("longitude"), station.get("latitude"))
            point_geom = station.get("geometry_points") or ()
            if point[0] is None or point[1] is None:
                if not point_geom or len(point_geom) != 1:
                    continue
                point = tuple(point_geom[0])
            distance, nearest, fraction = _nearest_point_on_route(point, geometry)
            scope = "full_route_no_ors_toll_sections"
            if toll_segments_by_route_id is not None and route.alternative_id in toll_segments_by_route_id:
                segments = toll_segments_by_route_id[route.alternative_id]
                if not segments:
                    continue
                scoped = [_nearest_point_on_route(point, segment) for segment in segments if len(segment) >= 2]
                if not scoped:
                    continue
                distance, nearest, _ = min(scoped, key=lambda item: item[0])
                scope = "ors_tollways_segments_same_geometry_hash"
            if distance > candidate_radius_m:
                continue
            route_refs = {value.casefold().strip() for value in route.road_references if value.strip()}
            station_ref = str(station.get("ref") or "").casefold().strip()
            state = "MATCHED_ROAD" if station_ref and station_ref in route_refs else "CANDIDATE_NEAR_ROUTE"
            output.append({
                "station_id": f"osm:{station['osm_type']}/{station['osm_id']}",
                "osm_type": station["osm_type"], "osm_id": station["osm_id"],
                "route_id": route.alternative_id, "origin_id": route.origin_id,
                "destination_id": route.destination_id,
                "distance_to_route_m": distance,
                "nearest_route_lon": nearest[0], "nearest_route_lat": nearest[1],
                "station_lon": point[0], "station_lat": point[1],
                "route_fraction": fraction, "distance_scope": scope,
                "route_distance_km": route.distance_km,
                "name": station.get("name"), "operator": station.get("operator"),
                "road_ref": station.get("ref"), "route_road_refs": sorted(route_refs),
                "state": state,
                "evidence": "proximidad solamente" if state == "CANDIDATE_NEAR_ROUTE"
                else "ref OSM coincide con referencia de ruta; no demuestra paso ni cobro",
                "toll_amount_eur": None, "toll_verification": "UNKNOWN",
            })
    return tuple(sorted(output, key=lambda row: (row["route_id"], row["route_fraction"], row["station_id"])))


def _coordinate(value) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("coordenada puntual debe ser [lon, lat]")
    lon, lat = float(value[0]), float(value[1])
    if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("coordenada puntual fuera de WGS84")
    return lon, lat


def _flatten_coordinates(geometry_type, coordinates) -> tuple[tuple[tuple[float, float], ...], ...]:
    if geometry_type == "LineString" and isinstance(coordinates, list):
        parts = [coordinates]
    elif geometry_type == "MultiLineString" and isinstance(coordinates, list):
        parts = coordinates
    else:
        raise ValueError(f"geometría OSM no soportada: {geometry_type}")
    return tuple(tuple(_coordinate(point) for point in part) for part in parts if part)


def _nearest_point_on_route(point, route):
    lat0 = math.radians((point[1] + sum(lat for _, lat in route) / len(route)) / 2)
    scale_x, scale_y = 6_371_000 * math.cos(lat0), 6_371_000

    def xy(coord):
        return math.radians(coord[0]) * scale_x, math.radians(coord[1]) * scale_y

    p = xy(point)
    projected = tuple(xy(coord) for coord in route)
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(projected, projected[1:])]
    total = sum(lengths)
    best = (math.inf, route[0], 0.0)
    passed = 0.0
    for index, (a, b) in enumerate(zip(projected, projected[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        denominator = dx * dx + dy * dy
        t = 0.0 if denominator == 0 else max(0.0, min(1.0,
            ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / denominator))
        nearest_xy = a[0] + t * dx, a[1] + t * dy
        distance = math.hypot(p[0] - nearest_xy[0], p[1] - nearest_xy[1])
        if distance < best[0]:
            lon = route[index][0] + t * (route[index + 1][0] - route[index][0])
            lat = route[index][1] + t * (route[index + 1][1] - route[index][1])
            fraction = 0.0 if total == 0 else (passed + t * lengths[index]) / total
            best = distance, (lon, lat), fraction
        passed += lengths[index]
    return best
