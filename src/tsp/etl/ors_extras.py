"""Lectura offline de tramos Directions GeoJSON con extra_info.

Las marcas OSM/ORS son evidencia cartográfica; nunca certifican una tarifa.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Iterable

from .toll_infrastructure import overpass_way_ids_query


EXTRA_RESPONSE_KEYS = {"tollways": "tollways", "osmid": "osmId", "waycategory": "waycategory"}
WAYCATEGORY_BITS = {1: "Highway", 2: "Tollways", 4: "Steps", 8: "Ferry", 16: "Ford"}


def _approximate_chainage_km(geometry: tuple[tuple[float, float], ...], total_km: float) -> tuple[float, ...]:
    """Calcula posiciones acumuladas por Haversine y las calibra al total ORS."""
    earth_radius_km = 6371.0088
    cumulative = [0.0]
    for (lon1, lat1), (lon2, lat2) in zip(geometry, geometry[1:]):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi, dlambda = phi2 - phi1, math.radians(lon2 - lon1)
        hav = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        cumulative.append(cumulative[-1] + 2 * earth_radius_km * math.asin(min(1.0, math.sqrt(hav))))
    shape_length = cumulative[-1]
    if shape_length <= 0:
        raise ValueError("geometría ORS de longitud nula")
    scale = total_km / shape_length
    return tuple(value * scale for value in cumulative)


def decode_waycategory_mask(value: int) -> tuple[str, ...]:
    """Descompone el campo oficial waycategory como máscara de bits."""
    if type(value) is not int or value < 0:
        raise ValueError("waycategory debe ser una máscara entera no negativa")
    names = tuple(name for bit, name in WAYCATEGORY_BITS.items() if value & bit)
    unknown = value & ~sum(WAYCATEGORY_BITS)
    return (*names, *((f"unknown_bit_{bit}" for bit in range(5, max(5, value.bit_length()))
                      if unknown & (1 << bit))))


def analyze_geojson_extras(response: dict, *, required: tuple[str, ...] = ()) -> tuple[dict, ...]:
    """Valida intervalos [inicio, fin] sobre vértices y resume cada feature.

    Dos intervalos que comparten solo el vértice extremo no duplican una
    arista. Los huecos se conservan como cobertura cartográfica parcial; nunca
    significan ausencia de peaje. Solo los solapamientos, el desorden y los
    índices fuera de la geometría invalidan los intervalos. La distancia en km
    usa el resumen ORS únicamente con cobertura completa; en su ausencia queda
    desconocida, sin estimarla desde la polilínea.
    """
    if set(required) - set(EXTRA_RESPONSE_KEYS):
        raise ValueError("extra_info solicitado no soportado")
    features = response.get("features") if isinstance(response, dict) else None
    if not isinstance(features, list) or not features:
        raise ValueError("GeoJSON ORS sin features")
    results = []
    for feature_index, feature in enumerate(features):
        try:
            coordinates = feature["geometry"]["coordinates"]
            properties = feature["properties"]
            summary = properties["summary"]
            distance_km = float(summary["distance"]) / 1000
            duration_hours = float(summary["duration"]) / 3600
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("feature ORS sin geometría, distancia o duración válidas") from exc
        if (not isinstance(coordinates, list) or len(coordinates) < 2
                or not math.isfinite(distance_km) or distance_km <= 0
                or not math.isfinite(duration_hours) or duration_hours <= 0):
            raise ValueError("geometría, distancia o duración ORS inválidas")
        try:
            geometry = tuple((float(point[0]), float(point[1])) for point in coordinates)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("coordenadas GeoJSON inválidas") from exc
        if any(not math.isfinite(lon) or not math.isfinite(lat)
                   or not -180 <= lon <= 180 or not -90 <= lat <= 90 for lon, lat in geometry):
            raise ValueError("coordenadas GeoJSON fuera de rango")
        chainage = _approximate_chainage_km(geometry, distance_km)
        steps = [step for segment in properties.get("segments", [])
                 if isinstance(segment, dict)
                 for step in segment.get("steps", []) if isinstance(step, dict)]
        step_ranges = []
        for step in steps:
            way_points = step.get("way_points")
            if (isinstance(way_points, list) and len(way_points) == 2
                    and all(type(value) is int for value in way_points)
                    and 0 <= way_points[0] < way_points[1] < len(geometry)):
                step_ranges.append((way_points[0], way_points[1], step.get("name"), step.get("ref")))
        extras = properties.get("extras")
        if extras is None:
            extras = {}
        if not isinstance(extras, dict):
            raise ValueError("extras ORS debe ser un objeto")
        sections_by_key = {}
        coverage_by_key = {}
        warnings = []
        for requested, response_key in EXTRA_RESPONSE_KEYS.items():
            entry = extras.get(response_key)
            if requested == "osmid" and entry is None:
                entry = extras.get("osmid")  # tolerancia explícita a versiones anteriores
            if entry is None:
                if requested in required:
                    raise ValueError(f"respuesta ORS sin extra_info solicitado: {requested}")
                warnings.append(f"extra_info ausente: {requested}")
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("values"), list):
                raise ValueError(f"secciones ORS inválidas para {requested}")
            cursor = 0
            complete_coverage = True
            previous_start = -1
            sections = []
            for item in entry["values"]:
                if (not isinstance(item, list) or len(item) != 3
                        or any(isinstance(value, bool) or not isinstance(value, int) for value in item)):
                    raise ValueError(f"sección ORS mal formada para {requested}")
                start, end, value = item
                if start < 0 or not start < end < len(geometry):
                    raise ValueError(f"intervalo ORS fuera de geometría para {requested}")
                if start < previous_start:
                    raise ValueError(f"intervalos ORS desordenados para {requested}")
                if start < cursor:
                    raise ValueError(f"intervalos ORS realmente solapados para {requested}")
                if start > cursor:
                    # ORS indexa secciones mediante vértices y puede dejar
                    # aristas sin clasificar. Se conserva la evidencia parcial,
                    # pero nunca se interpreta el hueco como tollways=0.
                    complete_coverage = False
                if ((requested == "tollways" and value not in (0, 1))
                        or (requested in {"osmid", "waycategory"} and value < 0)):
                    raise ValueError(f"valor ORS inválido para {requested}")
                sections.append((start, end, value))
                cursor = end
                previous_start = start
            if not sections or cursor != len(geometry) - 1:
                complete_coverage = False
            if sections and sections[0][0] != 0:
                complete_coverage = False
            coverage_by_key[requested] = "complete" if complete_coverage else "partial"
            if not complete_coverage:
                warnings.append(f"cobertura de intervalos incompleta para {requested}; tramos no clasificados")
            sections_by_key[requested] = tuple(sections)
        tolls = sections_by_key.get("tollways")
        toll_distance_km = None
        toll_distance_summary_km = None
        if tolls is not None:
            entry = extras["tollways"]
            reported = entry.get("summary")
            if isinstance(reported, list):
                distances = {}
                for item in reported:
                    if not isinstance(item, dict) or item.get("value") not in (0, 1):
                        raise ValueError("resumen tollways ORS inválido")
                    value = item["value"]
                    distance_m = float(item.get("distance", -1))
                    if value in distances or not math.isfinite(distance_m) or distance_m < 0:
                        raise ValueError("distancia tollways ORS duplicada o inválida")
                    distances[value] = distance_m
                if 1 in distances:
                    toll_distance_summary_km = distances[1] / 1000
                if coverage_by_key.get("tollways") == "complete":
                    if 1 in distances or not any(value == 1 for _, _, value in tolls):
                        toll_distance_km = distances.get(1, 0.0) / 1000
                    else:
                        warnings.append("resumen tollways sin distancia de secciones tarifadas")
                elif 1 in distances:
                    warnings.append("distancia resumida tollways disponible, pero su localización está incompleta")
            else:
                warnings.append("distancia tollways no informada por ORS")
            if coverage_by_key.get("tollways") != "complete":
                warnings.append("no se infiere cero de peaje con cobertura tollways incompleta")
        toll_sections = []
        for start, end, value in tolls or ():
            if value != 1:
                continue
            osm_ids = sorted({osm_id for left, right, osm_id in sections_by_key.get("osmid", ())
                              if osm_id > 0 and max(start, left) < min(end, right)})
            categories = sorted({category for left, right, category in sections_by_key.get("waycategory", ())
                                 if max(start, left) < min(end, right)})
            toll_sections.append({"start_index": start, "end_index": end,
                                  "start_lon_lat": geometry[start], "end_lon_lat": geometry[end],
                                  "geometry_coordinates": geometry[start:end + 1],
                                  # ORS extra_info indexa vértices. La fracción es una
                                  # referencia posicional aproximada, no kilometraje.
                                  "start_position_fraction": start / (len(geometry) - 1),
                                  "end_position_fraction": end / (len(geometry) - 1),
                                  "start_position_km_approx": chainage[start],
                                  "end_position_km_approx": chainage[end],
                                  "length_km_approx": chainage[end] - chainage[start],
                                  "position_method": "polilinea_haversine_escalada_al_resumen_ORS",
                                  "instruction_names": sorted({str(name) for left, right, name, _ in step_ranges
                                      if max(start, left) < min(end, right) and name}),
                                  "instruction_refs": sorted({str(ref) for left, right, _, ref in step_ranges
                                      if max(start, left) < min(end, right) and ref}),
                                  "osm_way_ids": osm_ids, "waycategory_values": categories,
                                  "waycategory_names": sorted({name for category in categories
                                      for name in decode_waycategory_mask(category)})})
        digest = sha256(json.dumps(geometry, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        results.append({"feature_index": feature_index, "geometry_sha256": digest,
                        "geometry_point_count": len(geometry), "distance_km": distance_km,
                        "geometry_segment_count": len(geometry) - 1,
                        "toll_segment_count": len(toll_sections),
                        "duration_hours": duration_hours,
                        "coverage": ("complete_cartographic" if coverage_by_key.get("tollways") == "complete"
                                     else "partial_cartographic" if tolls is not None
                                     else "missing_tollways"),
                        "extra_coverage": coverage_by_key,
                        "toll_distance_km": toll_distance_km,
                        "toll_distance_summary_km": toll_distance_summary_km,
                        "toll_sections": toll_sections,
                        "osm_way_ids": sorted({value for _, _, value in sections_by_key.get("osmid", ())
                                                if value > 0}),
                        "waycategory_values": sorted({value for _, _, value in
                                                      sections_by_key.get("waycategory", ())}),
                        "waycategory_names": sorted({name for _, _, value in
                            sections_by_key.get("waycategory", ())
                            for name in decode_waycategory_mask(value)}),
                        "warnings": warnings,
                        "toll_cost_eur": None, "toll_verification": "UNKNOWN"})
    return tuple(results)


def plan_overpass_way_queries(
    osm_way_ids: Iterable[int], *, known_way_ids: Iterable[int] = (), batch_size: int = 20,
) -> tuple[dict, ...]:
    """Planifica consultas pequeñas por ID de *way*; no realiza red.

    La existencia de un ID en el inventario local permite omitirlo. Los nodos
    de estaciones se investigan separadamente: un ID de vía no es una cabina.
    """
    if not 1 <= batch_size <= 50:
        raise ValueError("batch_size de Overpass debe estar entre 1 y 50")
    ids = tuple(osm_way_ids)
    known = set(known_way_ids)
    if any(type(value) is not int or value <= 0 for value in (*ids, *known)):
        raise ValueError("los identificadores OSM de vías deben ser enteros positivos")
    pending = sorted(set(ids) - known)
    batches = []
    for offset in range(0, len(pending), batch_size):
        chunk = pending[offset:offset + batch_size]
        query = overpass_way_ids_query(chunk)
        batches.append({"query_id": sha256(query.encode()).hexdigest()[:20],
                        "osm_type": "way", "osm_way_ids": chunk, "query": query,
                        "status": "pending", "http_budget": 1})
    return tuple(batches)
