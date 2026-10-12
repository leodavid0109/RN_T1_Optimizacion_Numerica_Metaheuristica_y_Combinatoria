"""Cliente opcional para openrouteservice; nunca se consulta al importar."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
import os
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..alternatives import RouteAlternative, TollStatus
from .acquisition import AcquisitionRequest


class ProviderError(RuntimeError):
    """Error sanitizado de proveedor (no contiene clave ni cabeceras)."""


class OpenRouteServiceProvider:
    """Adaptador de Directions API v2 con reintentos acotados y clave por entorno."""

    provider_name = "openrouteservice"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        profile: str = "driving-car",
        endpoint: str = "https://api.openrouteservice.org/v2/directions",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        max_http_requests: int | None = None,
        min_interval_seconds: float = 1.5,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("ORS_API_KEY")
        self.profile = profile
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_http_requests = max_http_requests
        self.http_requests_made = 0
        self.min_interval_seconds = min_interval_seconds
        self.opener, self.sleep, self.clock = opener, sleep, clock
        self.today = today or (lambda: datetime.now(timezone.utc).date().isoformat())
        self._last_request_at: float | None = None
        if (self.timeout_seconds <= 0 or self.max_retries < 0 or self.min_interval_seconds < 0
                or (max_http_requests is not None and max_http_requests < 1)):
            raise ValueError("timeout, reintentos o intervalo de consulta no válido")

    @property
    def cache_namespace(self) -> str:
        endpoint_id = sha256(self.endpoint.encode()).hexdigest()[:10]
        return f"{self.provider_name}:{self.profile}:endpoint-{endpoint_id}"

    def fetch(self, request: AcquisitionRequest) -> tuple[dict, tuple[RouteAlternative, ...]]:
        if not self.api_key:
            raise ProviderError("falta ORS_API_KEY; no se realizó ninguna solicitud")
        coordinates = [
            [float(request.origin.longitude), float(request.origin.latitude)],
            [float(request.destination.longitude), float(request.destination.latitude)],
        ]
        body: dict = {"coordinates": coordinates, "instructions": True, "geometry": True}
        body["preference"] = "fastest"
        if request.request_alternatives:
            body["alternative_routes"] = {"target_count": request.request_alternatives}
        if request.avoid_tolls or request.strategy == "avoid_tolls":
            body["options"] = {"avoid_features": ["tollways"]}
        url = f"{self.endpoint}/{self.profile}/geojson"
        safe_request = {"method": "POST", "url": url, "body": body}
        raw = self._post(url, body)
        routes = parse_ors_geojson(
            raw,
            origin_id=request.origin.city_id,
            destination_id=request.destination.city_id,
            request_id=request.request_id,
            fastest_route_id=request.fastest_route_id(self.profile),
            is_primary_fastest=(request.strategy == "fastest" and not request.avoid_tolls),
            strategy=request.strategy,
            profile=self.profile,
            source=url,
            acquired_on=self.today(),
        )
        return safe_request, raw, routes

    def fetch_matrix(self, cities) -> tuple[dict, dict, dict]:
        """Obtiene tabla ORS dirigida de distancias/tiempos; respuesta en km y horas.

        El endpoint Matrix no devuelve geometrías. Para geometría, pasos y búsqueda
        de alternativas se usa Directions por arco; el resultado Matrix no basta.
        """
        if not self.api_key:
            raise ProviderError("falta ORS_API_KEY; no se realizó ninguna solicitud")
        cities = tuple(cities)
        if len(cities) < 2 or len({city.city_id for city in cities}) != len(cities):
            raise ValueError("Matrix requiere al menos dos ciudades con ids únicos")
        if any(city.latitude is None or city.longitude is None
                             or city.coordinate_status != "verificada" for city in cities):
            raise ValueError("Matrix requiere coordenadas verificadas")
        if len(cities) * len(cities) > 3500:
            raise ValueError("la matriz excede el límite publicado de 3.500 pares por solicitud")
        body = {
            "locations": [[float(city.longitude), float(city.latitude)] for city in cities],
            "metrics": ["distance", "duration"],
            "units": "m",
            "preference": "fastest",
            "resolve_locations": True,
        }
        base_url = self.endpoint.removesuffix("/directions")
        url = f"{base_url}/matrix/{self.profile}"
        response = self._post(url, body)
        return {"method": "POST", "url": url, "body": body}, response, parse_ors_matrix(response, len(cities))

    def _post(self, url: str, body: Mapping) -> dict:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            if self._last_request_at is not None:
                wait = self.min_interval_seconds - (self.clock() - self._last_request_at)
                if wait > 0:
                    self.sleep(wait)
            request = Request(
                url,
                data=payload,
                headers={"Authorization": self.api_key or "", "Content-Type": "application/json"},
                method="POST",
            )
            if (self.max_http_requests is not None
                    and self.http_requests_made >= self.max_http_requests):
                raise ProviderError("se agotó el presupuesto total de solicitudes HTTP")
            # Cuenta cada intento, incluso fallos de transporte y reintentos.
            self.http_requests_made += 1
            self._last_request_at = self.clock()
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    status = response.status
                    data = response.read()
                    headers = response.headers
            except HTTPError as exc:
                status, headers = exc.code, exc.headers
                data = b""
            except (URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError("falló la conexión al proveedor") from exc
                self.sleep(min(2**attempt, 30))
                continue

            if status == 401 or status == 403:
                raise ProviderError(f"el proveedor rechazó autenticación/permisos (HTTP {status})")
            if status == 429 or status >= 500:
                if attempt >= self.max_retries:
                    raise ProviderError(f"el proveedor no aceptó la solicitud (HTTP {status})")
                retry_after = headers.get("Retry-After") if headers else None
                try:
                    delay = float(retry_after) if retry_after is not None else float(2**attempt)
                except (ValueError, TypeError):
                    try:
                        delay = max(0.0, (parsedate_to_datetime(retry_after)
                                         - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        delay = float(2**attempt)
                self.sleep(min(max(delay, 0.0), 60.0))
                continue
            if status < 200 or status >= 300:
                raise ProviderError(f"respuesta HTTP no satisfactoria ({status})")
            try:
                decoded = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("el proveedor devolvió JSON inválido") from exc
            if not isinstance(decoded, dict):
                raise ProviderError("la respuesta del proveedor debe ser un objeto JSON")
            return decoded
        raise ProviderError("se agotaron los reintentos")


def parse_ors_geojson(
    response: dict,
    *,
    origin_id: str,
    destination_id: str,
    request_id: str,
    fastest_route_id: str,
    is_primary_fastest: bool,
    strategy: str,
    profile: str,
    source: str,
    acquired_on: str,
) -> tuple[RouteAlternative, ...]:
    """Normaliza GeoJSON ORS (m, s) y conserva que el peaje es desconocido."""
    features = response.get("features")
    if not isinstance(features, list) or not features:
        raise ProviderError("la respuesta no contiene features de ruta")
    parsed = []
    for index, feature in enumerate(features):
        try:
            properties = feature["properties"]
            summary = properties["summary"]
            distance_km = float(summary["distance"]) / 1000.0
            duration_hours = float(summary["duration"]) / 3600.0
            coordinates = feature["geometry"]["coordinates"]
            geometry = tuple((float(pair[0]), float(pair[1])) for pair in coordinates)
            segments = properties.get("segments", [])
            road_references = tuple(dict.fromkeys(
                str(step.get("ref") or step.get("name"))
                for segment in segments for step in segment.get("steps", [])
                if step.get("ref") or step.get("name")
            ))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProviderError("feature ORS incompleta o con unidades inválidas") from exc
        if len(geometry) < 2:
            raise ProviderError("geometría ORS incompleta")
        parsed.append((distance_km, duration_hours, geometry, road_references))
    if any(distance <= 0 or duration <= 0 for distance, duration, _, _ in parsed):
        raise ProviderError("distancia y duración de ruta deben ser positivas")

    ids = [f"ors-{request_id}-{index:02d}" for index in range(len(parsed))]
    fastest_index = min(range(len(parsed)), key=lambda index: (parsed[index][1], parsed[index][0], ids[index]))
    # Solo la consulta base declara la ruta rápida oficial; los resultados de
    # evitación/alternativas enlazan a esa identidad sin reemplazarla.
    if is_primary_fastest:
        ids[fastest_index] = fastest_route_id
    metadata = response.get("metadata") or {}
    engine_metadata = metadata.get("engine") or {}
    engine_version = str(engine_metadata.get("version") or "no_informada_por_API")
    graph_version = engine_metadata.get("graph_date") or engine_metadata.get("graph_version")
    return tuple(
        RouteAlternative(
            origin_id=origin_id,
            destination_id=destination_id,
            alternative_id=ids[index],
            fastest_route_id=fastest_route_id,
            distance_km=distance,
            duration_hours=duration,
            toll_status=TollStatus.UNKNOWN,
            toll_cost_eur=None,
            routing_engine="openrouteservice",
            routing_engine_version=engine_version,
            profile=profile,
            source=source,
            acquired_on=acquired_on,
            network_data_version=str(graph_version) if graph_version is not None else None,
            road_references=road_references,
            routing_parameters=(("preference", "fastest"), ("strategy", strategy)),
            geometry_lon_lat=geometry,
            limitations=(
                "Duración calculada por el perfil, no medición de tráfico en tiempo real.",
                "El proveedor no proporciona tarifa monetaria de peajes en este registro.",
                "Las alternativas solicitadas no son un conjunto exhaustivo de rutas.",
                *( () if graph_version is not None else ("Versión/fecha del grafo no informada en la respuesta.",) ),
            ),
        )
        for index, (distance, duration, geometry, road_references) in enumerate(parsed)
    )


def parse_ors_matrix(response: dict, size: int) -> dict:
    """Normaliza m/s a km/h y rechaza matrices nulas o de forma incorrecta."""
    try:
        distances = response["distances"]
        durations = response["durations"]
        if len(distances) != size or len(durations) != size:
            raise ValueError
        distance_km, time_hours = [], []
        for d_row, t_row in zip(distances, durations):
            if len(d_row) != size or len(t_row) != size:
                raise ValueError
            if any(value is None for value in (*d_row, *t_row)):
                raise ValueError
            distance_km.append([float(value) / 1000 for value in d_row])
            time_hours.append([float(value) / 3600 for value in t_row])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("matriz ORS incompleta, no cuadrada o con celdas sin ruta") from exc
    for matrix in (distance_km, time_hours):
        if any(not math.isfinite(value) or value < 0 for row in matrix for value in row):
            raise ProviderError("la matriz ORS contiene valores negativos o no finitos")
        if any(abs(matrix[index][index]) > 1e-9 for index in range(size)):
            raise ProviderError("la diagonal de la matriz ORS no es cero")
    return {"distance_km": distance_km, "time_hours": time_hours}
