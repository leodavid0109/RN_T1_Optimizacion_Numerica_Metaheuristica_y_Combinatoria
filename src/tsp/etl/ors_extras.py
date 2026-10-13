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

    Dos intervalos que comparten solo el vértice extremo no duplican una arista.
    La distancia en km usa el resumen de ORS cuando está presente; en su
    ausencia queda desconocida, sin estimarla desde la polilínea.
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
        extras = properties.get("extras")
        if extras is None:
            extras = {}
        if not isinstance(extras, dict):
            raise ValueError("extras ORS debe ser un objeto")
        sections_by_key = {}
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
            sections = []
            for item in entry["values"]:
                if (not isinstance(item, list) or len(item) != 3
                        or any(isinstance(value, bool) or not isinstance(value, int) for value in item)):
                    raise ValueError(f"sección ORS mal formada para {requested}")
                start, end, value = item
                if start != cursor or not start < end < len(geometry):
                    raise ValueError(f"intervalos ORS solapados, discontinuos o fuera de geometría: {requested}")
                if ((requested == "tollways" and value not in (0, 1))
                        or (requested in {"osmid", "waycategory"} and value < 0)):
                    raise ValueError(f"valor ORS inválido para {requested}")
                sections.append((start, end, value))
                cursor = end
            if cursor != len(geometry) - 1:
                raise ValueError(f"cobertura ORS incompleta para {requested}")
            sections_by_key[requested] = tuple(sections)
        tolls = sections_by_key.get("tollways")
        toll_distance_km = None
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
                if 1 in distances or not any(value == 1 for _, _, value in tolls):
                    toll_distance_km = distances.get(1, 0.0) / 1000
                else:
                    warnings.append("resumen tollways sin distancia de secciones tarifadas")
            else:
                warnings.append("distancia tollways no informada por ORS")
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
                                  "osm_way_ids": osm_ids, "waycategory_values": categories,
                                  "waycategory_names": sorted({name for category in categories
                                      for name in decode_waycategory_mask(category)})})
        digest = sha256(json.dumps(geometry, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        results.append({"feature_index": feature_index, "geometry_sha256": digest,
                        "geometry_point_count": len(geometry), "distance_km": distance_km,
                        "duration_hours": duration_hours,
                        "coverage": "complete_cartographic" if tolls is not None else "missing_tollways",
                        "toll_distance_km": toll_distance_km,
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
