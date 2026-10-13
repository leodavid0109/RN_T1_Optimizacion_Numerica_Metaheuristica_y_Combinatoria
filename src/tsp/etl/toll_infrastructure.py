"""Inventario espacial de peajes y candidatos de cruce con rutas.

Este módulo no consulta internet al importarse. ``OverpassClient.fetch_bbox``
solo hace una petición cuando se invoca explícitamente y exige una caja limitada.
La proximidad resultante es una pista cartográfica, nunca una confirmación de
tránsito ni una tarifa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from hashlib import sha256
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..alternatives import RouteAlternative


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
OVERPASS_SOURCE = "OpenStreetMap/Overpass API"


@dataclass(frozen=True)
class BoundingBox:
    """Caja geográfica WGS84, en orden sur, oeste, norte, este."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        values = (self.south, self.west, self.north, self.east)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("el bounding box debe contener coordenadas finitas")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("latitudes inválidas en bounding box")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("longitudes inválidas en bounding box")
        if (self.north - self.south) * (self.east - self.west) > 1.0:
            raise ValueError("bounding box demasiado amplio; divídalo en regiones pequeñas")

    def overpass_query(self) -> str:
        bbox = f"{self.south},{self.west},{self.north},{self.east}"
        return (
            "[out:json][timeout:25];("
            f'nwr["barrier"="toll_booth"]({bbox});'
            f'nwr["highway"="toll_gantry"]({bbox});'
            f'nwr["toll"="yes"]({bbox});'
            ");out body geom;"
        )


@dataclass(frozen=True)
class TollInfrastructure:
    """Elemento OSM inmutable con geometría WGS84 y etiquetas originales."""

    osm_type: str
    osm_id: int
    infrastructure_type: str
    geometry_lon_lat: tuple[tuple[float, float], ...]
    name: str | None
    operator: str | None
    road_reference: str | None
    direction: str | None
    tags: tuple[tuple[str, str], ...]
    source: str
    acquired_at: str

    @property
    def stable_id(self) -> str:
        return f"osm:{self.osm_type}/{self.osm_id}"


@dataclass(frozen=True)
class RouteMatchCandidate:
    """Coincidencia espacial candidata, no confirmación de cobro o tránsito."""

    infrastructure_id: str
    route_id: str
    minimum_distance_m: float
    route_fraction: float
    confidence: str
    evidence: tuple[str, ...]
    direction_evidence: str


class OverpassError(RuntimeError):
    """Fallo de transporte o estructura de Overpass."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OverpassClient:
    """Cliente acotado de Overpass; no divide una consulta regional automáticamente."""

    def __init__(
        self,
        endpoint: str = OVERPASS_ENDPOINT,
        *,
        timeout_seconds: float = 45.0,
        opener: Callable = urlopen,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Overpass debe consultarse mediante HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser positivo")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    def fetch_bbox(self, bbox: BoundingBox) -> tuple[TollInfrastructure, ...]:
        """Ejecuta una sola consulta para la caja indicada; sin reintentos implícitos."""
        return parse_overpass_response(self.fetch_bbox_payload(bbox))

    def fetch_bbox_payload(self, bbox: BoundingBox) -> dict:
        """Devuelve el JSON original de una única consulta acotada."""
        query = bbox.overpass_query()
        request = Request(
            self.endpoint,
            data=urlencode({"data": query}).encode("utf-8"),
            headers={"User-Agent": "RN-T1-TSP toll inventory/1.0", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OverpassError(
                f"Overpass respondió HTTP {exc.code}", status_code=exc.code
            ) from exc
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OverpassError(f"falló la consulta Overpass: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
            raise OverpassError("respuesta Overpass inválida")
        return payload


class OverpassCatalogStore:
    """Caché local por bounding box con reutilización y persistencia offline."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw" / "tolls"
        self.processed_dir = self.root / "processed" / "tolls"

    def get_or_fetch(
        self,
        client: OverpassClient,
        bbox: BoundingBox,
        *,
        refresh: bool = False,
        max_age_days: int = 30,
    ) -> tuple[tuple[TollInfrastructure, ...], bool]:
        """Devuelve catálogo cacheado vigente o hace una petición si se invoca.

        El segundo valor indica si se consultó la red. No hay reintentos. El
        `max_age_days` es una regla local que debe quedar en el manifiesto del
        experimento, no una vigencia declarada por OSM.
        """
        if max_age_days < 0:
            raise ValueError("max_age_days no puede ser negativo")
        query = bbox.overpass_query()
        fingerprint = sha256(query.encode("utf-8")).hexdigest()[:20]
        metadata_path = self.processed_dir / f"infrastructure_{fingerprint}.metadata.json"
        if not refresh and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            acquired_at = datetime.fromisoformat(metadata["acquired_at"])
            age_days = (datetime.now(timezone.utc) - acquired_at.astimezone(timezone.utc)).total_seconds() / 86400
            raw_path = self.raw_dir / metadata["raw_file"]
            geojson_path = self.processed_dir / metadata["catalog_file"]
            if age_days <= max_age_days and raw_path.exists() and geojson_path.exists():
                return load_infrastructure_catalog(geojson_path), False
        payload = client.fetch_bbox_payload(bbox)
        acquired_at = datetime.now(timezone.utc).isoformat()
        records = parse_overpass_response(payload, acquired_at=acquired_at)
        payload_digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
        raw_path = self.raw_dir / f"overpass_{fingerprint}_{payload_digest}.json"
        geojson_path = self.processed_dir / f"infrastructure_{fingerprint}_{payload_digest}.geojson"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        save_infrastructure_catalog(geojson_path, records)
        metadata_path.write_text(json.dumps({
            "schema_version": 1, "source": OVERPASS_SOURCE, "query_sha256": sha256(query.encode()).hexdigest(),
            "query": query, "bbox_south_west_north_east": [bbox.south, bbox.west, bbox.north, bbox.east],
            "acquired_at": acquired_at, "raw_file": str(raw_path.name), "catalog_file": str(geojson_path.name),
            "attribution": "© OpenStreetMap contributors", "license": "ODbL",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return records, True


def parse_overpass_response(payload: dict, *, acquired_at: str | None = None) -> tuple[TollInfrastructure, ...]:
    """Normaliza respuestas Overpass a inventario espacial deduplicado."""
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("respuesta Overpass inválida: falta elements")
    acquired = acquired_at or datetime.now(timezone.utc).isoformat()
    # Validar fecha ISO sin imponer que la hora tenga una zona específica.
    datetime.fromisoformat(acquired.replace("Z", "+00:00"))
    results: dict[tuple[str, int], TollInfrastructure] = {}
    for element in payload["elements"]:
        if not isinstance(element, dict):
            continue
        osm_type, osm_id = element.get("type"), element.get("id")
        tags = element.get("tags") or {}
        if osm_type not in {"node", "way", "relation"} or not isinstance(osm_id, int) or not isinstance(tags, dict):
            continue
        kind = _classify_tags(tags)
        if kind is None:
            continue
        geometry = _element_geometry(element)
        if not geometry:
            continue
        canonical_tags = tuple(sorted((str(key), str(value)) for key, value in tags.items()))
        result = TollInfrastructure(
            osm_type=osm_type,
            osm_id=osm_id,
            infrastructure_type=kind,
            geometry_lon_lat=geometry,
            name=_optional_tag(tags, "name"),
            operator=_optional_tag(tags, "operator"),
            road_reference=_optional_tag(tags, "ref"),
            direction=_optional_tag(tags, "direction") or _optional_tag(tags, "oneway"),
            tags=canonical_tags,
            source=OVERPASS_SOURCE,
            acquired_at=acquired,
        )
        results[(osm_type, osm_id)] = result
    return tuple(results[key] for key in sorted(results))


def save_infrastructure_catalog(path: str | Path, records: Iterable[TollInfrastructure]) -> None:
    """Guarda el inventario local como GeoJSON FeatureCollection."""
    features = []
    seen: set[str] = set()
    for record in records:
        if record.stable_id in seen:
            raise ValueError(f"infraestructura duplicada: {record.stable_id}")
        seen.add(record.stable_id)
        geometry_type = "Point" if len(record.geometry_lon_lat) == 1 else "LineString"
        coords = record.geometry_lon_lat[0] if geometry_type == "Point" else record.geometry_lon_lat
        features.append({
            "type": "Feature",
            "id": record.stable_id,
            "geometry": {"type": geometry_type, "coordinates": coords},
            "properties": {
                "osm_type": record.osm_type, "osm_id": record.osm_id,
                "infrastructure_type": record.infrastructure_type, "name": record.name,
                "operator": record.operator, "road_reference": record.road_reference,
                "direction": record.direction, "tags": dict(record.tags),
                "source": record.source, "acquired_at": record.acquired_at,
            },
        })
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_infrastructure_catalog(path: str | Path) -> tuple[TollInfrastructure, ...]:
    """Carga un GeoJSON persistido sin red y conserva identidad, etiquetas y fechas."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("el catálogo local debe ser GeoJSON FeatureCollection")
    records = []
    for feature in payload.get("features", []):
        properties, geometry = feature.get("properties", {}), feature.get("geometry", {})
        geometry_type, coordinates = geometry.get("type"), geometry.get("coordinates")
        if geometry_type == "Point":
            points = (coordinates,)
        elif geometry_type == "LineString":
            points = tuple(coordinates or ())
        else:
            raise ValueError(f"geometría de infraestructura no soportada: {geometry_type}")
        osm_type, osm_id = properties.get("osm_type"), properties.get("osm_id")
        if feature.get("id") != f"osm:{osm_type}/{osm_id}":
            raise ValueError("el ID GeoJSON no coincide con el ID OSM")
        normalized = tuple((float(point[0]), float(point[1])) for point in points)
        if not normalized or any(not _valid_lon_lat(point) for point in normalized):
            raise ValueError("geometría vacía o fuera de rango")
        tags = properties.get("tags", {})
        if not isinstance(tags, dict):
            raise ValueError("tags del catálogo local debe ser un objeto")
        records.append(TollInfrastructure(
            osm_type, int(osm_id), properties["infrastructure_type"], normalized,
            properties.get("name"), properties.get("operator"), properties.get("road_reference"),
            properties.get("direction"), tuple(sorted((str(k), str(v)) for k, v in tags.items())),
            properties["source"], properties["acquired_at"],
        ))
    ids = [record.stable_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("el catálogo local contiene IDs OSM duplicados")
    return tuple(records)


def match_infrastructure_to_route(
    route_id: str,
    route_geometry_lon_lat: Iterable[tuple[float, float]],
    infrastructure: Iterable[TollInfrastructure],
    *,
    radius_m: float = 35.0,
) -> tuple[RouteMatchCandidate, ...]:
    """Devuelve candidatos cercanos a una geometría, sin afirmar tránsito confirmado.

    La fracción 0..1 es la posición aproximada sobre la polilínea. La distancia
    usa una proyección local equirectangular, adecuada para radios urbanos cortos.
    """
    if not route_id.strip() or not math.isfinite(radius_m) or radius_m <= 0:
        raise ValueError("route_id y radius_m positivo son obligatorios")
    route = tuple((float(lon), float(lat)) for lon, lat in route_geometry_lon_lat)
    if len(route) < 2 or any(not _valid_lon_lat(p) for p in route):
        raise ValueError("la ruta debe tener al menos dos coordenadas WGS84 válidas")
    lengths = [_distance_m(a, b) for a, b in zip(route, route[1:])]
    total_length = sum(lengths)
    if total_length <= 0:
        raise ValueError("la geometría de ruta no puede tener longitud cero")
    matches = []
    for feature in infrastructure:
        best = _nearest_geometry_pair(route, lengths, total_length, feature.geometry_lon_lat)
        distance, fraction = best
        if distance <= radius_m:
            tags = dict(feature.tags)
            direction = "sin evidencia direccional; validar calzada y sentido"
            if feature.direction:
                direction = f"etiqueta OSM direction/oneway={feature.direction}; no prueba el sentido de cobro"
            elif tags.get("oneway"):
                direction = f"etiqueta OSM oneway={tags['oneway']}; no prueba el sentido de cobro"
            matches.append(RouteMatchCandidate(
                feature.stable_id, route_id, distance, fraction,
                "candidato_proximidad", (f"distancia_geometrica<={radius_m:g}m",), direction,
            ))
    return tuple(sorted(matches, key=lambda item: (item.route_fraction, item.infrastructure_id)))


def match_route_alternatives_to_infrastructure(
    routes: Iterable[RouteAlternative],
    infrastructure: Iterable[TollInfrastructure],
    *,
    radius_m: float = 35.0,
) -> tuple[RouteMatchCandidate, ...]:
    """Cruza el catálogo local de alternativas con un inventario OSM cargado.

    El método es offline y falla explícitamente si una alternativa no conserva
    geometría, en lugar de presentar una cobertura parcial como análisis final.
    """
    routes, infrastructure = tuple(routes), tuple(infrastructure)
    missing_geometry = [route.alternative_id for route in routes if route.geometry_lon_lat is None]
    if missing_geometry:
        raise ValueError("faltan geometrías para: " + ", ".join(missing_geometry))
    return tuple(
        candidate
        for route in routes
        for candidate in match_infrastructure_to_route(
            route.alternative_id, route.geometry_lon_lat or (), infrastructure, radius_m=radius_m
        )
    )


def _classify_tags(tags: dict) -> str | None:
    if tags.get("barrier") == "toll_booth":
        return "toll_booth"
    if tags.get("highway") == "toll_gantry":
        return "toll_gantry"
    if tags.get("toll") == "yes":
        return "toll_road"
    return None


def _optional_tag(tags: dict, key: str) -> str | None:
    value = tags.get(key)
    return str(value) if value not in (None, "") else None


def _element_geometry(element: dict) -> tuple[tuple[float, float], ...]:
    if "lon" in element and "lat" in element:
        return ((float(element["lon"]), float(element["lat"])),)
    points = element.get("geometry")
    if not isinstance(points, list):
        center = element.get("center")
        if isinstance(center, dict) and "lon" in center and "lat" in center:
            points = [center]
        else:
            return ()
    result = []
    for point in points:
        if not isinstance(point, dict) or "lon" not in point or "lat" not in point:
            continue
        coordinate = (float(point["lon"]), float(point["lat"]))
        if not _valid_lon_lat(coordinate):
            raise ValueError("Overpass contiene coordenadas fuera de rango")
        result.append(coordinate)
    return tuple(result)


def _valid_lon_lat(point: tuple[float, float]) -> bool:
    lon, lat = point
    return math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat_mid = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * 6_371_000 * math.cos(lat_mid)
    dy = math.radians(b[1] - a[1]) * 6_371_000
    return math.hypot(dx, dy)


def _nearest_geometry_pair(
    route: tuple[tuple[float, float], ...], route_lengths: list[float], route_total: float,
    feature: tuple[tuple[float, float], ...],
) -> tuple[float, float]:
    """Mínima distancia polilínea-polilínea y posición en la ruta, en metros."""
    lat0 = math.radians(sum(point[1] for point in (*route, *feature)) / (len(route) + len(feature)))
    scale_x, scale_y = 6_371_000 * math.cos(lat0), 6_371_000

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return math.radians(point[0]) * scale_x, math.radians(point[1]) * scale_y

    route_xy, feature_xy = tuple(map(project, route)), tuple(map(project, feature))
    route_segments = list(zip(route_xy, route_xy[1:])) or [(route_xy[0], route_xy[0])]
    feature_segments = list(zip(feature_xy, feature_xy[1:])) or [(feature_xy[0], feature_xy[0])]
    best: tuple[float, float] | None = None
    route_offset = 0.0
    for index, (a, b) in enumerate(route_segments):
        for c, d in feature_segments:
            distance, route_t = _segment_pair_distance(a, b, c, d)
            fraction = (route_offset + route_t * route_lengths[index]) / route_total
            if best is None or distance < best[0]:
                best = distance, fraction
        route_offset += route_lengths[index]
    assert best is not None
    return best


def _segment_pair_distance(a, b, c, d) -> tuple[float, float]:
    """Distancia mínima entre segmentos y parámetro t sobre el segmento AB."""
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = d[0] - c[0], d[1] - c[1]
    determinant = vx * wy - vy * wx
    if abs(determinant) > 1e-9:
        t = ((c[0] - a[0]) * wy - (c[1] - a[1]) * wx) / determinant
        u = ((c[0] - a[0]) * vy - (c[1] - a[1]) * vx) / determinant
        if 0 <= t <= 1 and 0 <= u <= 1:
            return 0.0, t
    candidates = []
    # Proyectar extremos de cada segmento contra el otro cubre el mínimo si
    # los segmentos no se cruzan. Los dos primeros puntos pertenecen a CD;
    # los dos últimos pertenecen a AB y ya tienen su t sobre la ruta.
    for point, origin, end, point_on_route, fixed_t in (
        (c, a, b, False, None), (d, a, b, False, None),
        (a, c, d, True, 0.0), (b, c, d, True, 1.0),
    ):
        dx, dy = end[0] - origin[0], end[1] - origin[1]
        length2 = dx * dx + dy * dy
        t = fixed_t if fixed_t is not None else (
            0.0 if length2 == 0 else max(0.0, min(1.0,
                ((point[0] - origin[0]) * dx + (point[1] - origin[1]) * dy) / length2))
        )
        nearest = origin[0] + t * dx, origin[1] + t * dy
        distance = math.hypot(point[0] - nearest[0], point[1] - nearest[1])
        route_t = t if point_on_route else fixed_t
        if route_t is None:
            # El punto original está sobre CD; recuperar la proyección calculada
            # sobre AB mediante la distancia mínima al pie en AB.
            route_t = t
        candidates.append((distance, float(route_t)))
    return min(candidates, key=lambda candidate: candidate[0])
