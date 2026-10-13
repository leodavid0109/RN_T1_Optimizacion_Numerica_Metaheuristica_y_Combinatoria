"""Cliente conservador de TollGuru para planificar y probar solicitudes.

El módulo no realiza llamadas al importarse. Las respuestas reales se guardan
solo en almacenamiento local ignorado por Git hasta aclarar su redistribución.
No convierte importes del proveedor en tarifas verificadas oficialmente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TOLLGURU_BASE_URL = "https://apis.tollguru.com/toll/v2"
POLYLINE_PATH = "/complete-polyline-from-mapping-service"
OD_PATH = "/origin-destination-waypoints"


class TollGuruError(RuntimeError):
    """Fallo sanitizado que no incluye API keys, cabeceras ni cuerpos remotos."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class TollGuruRequestPlan:
    endpoint: str
    payload: Mapping[str, object]
    route_id: str
    request_sha256: str
    method: str = "POST"


@dataclass(frozen=True)
class TollGuruResponse:
    route_id: str
    request_sha256: str
    requested_departure_time: str | None
    queried_at: str
    status_code: int
    provider_transaction_count: int | None
    raw_payload: Mapping[str, object]


class TollGuruClient:
    """Cliente HTTP con presupuesto estricto y ejecución siempre explícita.

    La clave usa `x-api-key`, que aparece en los ejemplos POST específicos y en
    el esquema de seguridad actual. La guía narrativa también menciona Basic
    Auth; confirmar la regla aplicable a la cuenta antes del piloto real.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "TOLLGURU_API_KEY",
        base_url: str = TOLLGURU_BASE_URL,
        timeout_seconds: float = 30.0,
        max_http_requests: int = 1,
        opener: Callable = urlopen,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("TollGuru debe consultarse mediante HTTPS")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser positivo y finito")
        if max_http_requests < 1:
            raise ValueError("max_http_requests debe ser al menos 1")
        if not api_key_env.strip():
            raise ValueError("api_key_env no puede estar vacío")
        self._api_key = api_key if api_key is not None else os.environ.get(api_key_env)
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_http_requests = max_http_requests
        self.opener = opener
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.http_requests_made = 0
        self.http_status_codes: list[int] = []

    def plan_polyline(
        self,
        route_id: str,
        coordinates_lon_lat: tuple[tuple[float, float], ...],
        *,
        vehicle: Mapping[str, object],
        map_provider: str = "custom",
        departure_time: str | None = None,
    ) -> TollGuruRequestPlan:
        """Prepara una ruta completa ORS; las coordenadas se codifican lat,lng.

        `vehicle` se exige explícitamente porque la equivalencia del BMW con las
        categorías españolas del proveedor aún no está resuelta documentalmente.
        """
        _validate_route_id(route_id)
        if len(coordinates_lon_lat) < 2:
            raise ValueError("la geometría necesita al menos dos coordenadas")
        if not isinstance(vehicle, Mapping) or not vehicle:
            raise ValueError("vehicle debe ser un objeto no vacío")
        if not map_provider.strip():
            raise ValueError("map_provider no puede estar vacío")
        points: list[str] = []
        for point in coordinates_lon_lat:
            if len(point) != 2:
                raise ValueError("cada punto debe ser (longitud, latitud)")
            lon, lat = map(float, point)
            if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError("geometría contiene coordenadas inválidas")
            # La documentación del campo `path` ejemplifica latitud,longitud.
            points.append(f"{lat:.7f},{lon:.7f}")
        payload: dict[str, object] = {
            "mapProvider": map_provider,
            "path": "|".join(points),
            "vehicle": dict(vehicle),
        }
        if departure_time is not None:
            _validate_datetime(departure_time)
            payload["departureTime"] = departure_time
        return self._plan(route_id, POLYLINE_PATH, payload, departure_time)

    def plan_origin_destination(
        self,
        route_id: str,
        payload: Mapping[str, object],
        *,
        departure_time: str | None = None,
    ) -> TollGuruRequestPlan:
        """Planifica OD a partir del objeto documentado, sin inventar perfil.

        El llamador suministra `from`, `to`, `vehicle` y las opciones que haya
        verificado para su cuenta; el planificador no ejecuta ni altera el JSON.
        """
        _validate_route_id(route_id)
        if not isinstance(payload, Mapping) or not payload.get("from") or not payload.get("to"):
            raise ValueError("OD requiere los campos from y to documentados")
        if not isinstance(payload.get("vehicle"), Mapping):
            raise ValueError("OD requiere un objeto vehicle documentado")
        body = dict(payload)
        if departure_time is not None:
            _validate_datetime(departure_time)
            body["departureTime"] = departure_time
        return self._plan(route_id, OD_PATH, body, departure_time)

    def execute(self, plan: TollGuruRequestPlan, *, execute: bool = False) -> TollGuruResponse | TollGuruRequestPlan:
        """Devuelve el plan por defecto; solo ejecuta con `execute=True`."""
        if not execute:
            return plan
        if not self._api_key:
            raise TollGuruError(f"falta {self.api_key_env}; no se realizó ninguna solicitud")
        if self.http_requests_made >= self.max_http_requests:
            raise TollGuruError("se agotó el presupuesto total de solicitudes HTTP")
        request = Request(
            plan.endpoint,
            data=json.dumps(plan.payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": self._api_key},
            method="POST",
        )
        self.http_requests_made += 1
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status = response.status
                body = response.read()
        except HTTPError as exc:
            self.http_status_codes.append(exc.code)
            raise TollGuruError(f"TollGuru respondió HTTP {exc.code}", status_code=exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TollGuruError(f"falló la conexión a TollGuru: {type(exc).__name__}") from exc
        self.http_status_codes.append(status)
        if status < 200 or status >= 300:
            raise TollGuruError(f"TollGuru respondió HTTP {status}", status_code=status)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TollGuruError("TollGuru devolvió una respuesta no JSON") from exc
        if not isinstance(parsed, dict):
            raise TollGuruError("respuesta TollGuru inválida: se esperaba un objeto JSON")
        if not any(isinstance(parsed.get(key), (dict, list)) for key in ("route", "routes")):
            raise TollGuruError("respuesta TollGuru incompleta: falta route o routes")
        tx = parsed.get("meta", {}).get("tx") if isinstance(parsed.get("meta"), dict) else None
        tx = tx if isinstance(tx, int) and tx >= 0 else None
        queried = self.now()
        if queried.tzinfo is None:
            raise ValueError("now debe devolver una fecha con zona horaria")
        return TollGuruResponse(
            route_id=plan.route_id,
            request_sha256=plan.request_sha256,
            requested_departure_time=plan.payload.get("departureTime") if isinstance(plan.payload.get("departureTime"), str) else None,
            queried_at=queried.astimezone(timezone.utc).isoformat(),
            status_code=status,
            provider_transaction_count=tx,
            raw_payload=parsed,
        )

    @staticmethod
    def save_local(response: TollGuruResponse, root: str | Path = "data/raw/tollguru") -> Path:
        """Guarda el resultado bruto localmente; la carpeta debe estar ignorada."""
        target_dir = Path(root)
        target_dir.mkdir(parents=True, exist_ok=True)
        serialized_response = json.dumps(response.raw_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        response_digest = sha256(serialized_response.encode("utf-8")).hexdigest()[:12]
        target = target_dir / f"{response.route_id}_{response.request_sha256[:12]}_{response_digest}.json"
        document = {
            "schema_version": 1,
            "provider": "TollGuru",
            "route_id": response.route_id,
            "request_sha256": response.request_sha256,
            "requested_departure_time": response.requested_departure_time,
            "queried_at": response.queried_at,
            "http_status": response.status_code,
            "provider_transaction_count": response.provider_transaction_count,
            "raw_response": response.raw_payload,
            "economic_status": "unverified_provider_estimate",
            "note": "No interpretar como tarifa oficial ni usar como costo completo sin validación.",
        }
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def _plan(self, route_id: str, path: str, payload: Mapping[str, object], departure_time: str | None) -> TollGuruRequestPlan:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        return TollGuruRequestPlan(
            endpoint=f"{self.base_url}{path}", payload=dict(payload), route_id=route_id,
            request_sha256=digest,
        )


def _validate_datetime(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("departure_time debe ser ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("departure_time debe incluir zona horaria explícita")


def _validate_route_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError("route_id debe ser un identificador estable sin separadores de ruta")
