"""Manifiesto estable y reanudable de solicitudes dirigidas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Protocol, Sequence

from ..cities import City
from ..alternatives import RouteAlternative
from .store import RouteStore


@dataclass(frozen=True)
class AcquisitionRequest:
    """Solicitud de ruta dirigida; las coordenadas se envían como lon,lat."""

    origin: City
    destination: City
    strategy: str = "fastest"
    request_alternatives: int = 0
    avoid_tolls: bool = False

    def __post_init__(self) -> None:
        if self.origin.city_id == self.destination.city_id:
            raise ValueError("una solicitud de ruta debe conectar ciudades distintas")
        if self.strategy not in {"fastest", "avoid_tolls", "alternatives"}:
            raise ValueError("strategy debe ser fastest, avoid_tolls o alternatives")
        if not 0 <= self.request_alternatives <= 3:
            raise ValueError("ORS permite solicitar como máximo tres alternativas")
        for city in (self.origin, self.destination):
            if city.coordinate_status != "verificada" or city.latitude is None or city.longitude is None:
                raise ValueError(f"coordenada no verificada para {city.city_id}")

    @property
    def request_id(self) -> str:
        canonical = {
            "origin": self.origin.city_id,
            "destination": self.destination.city_id,
            "coordinates_lon_lat": [
                [self.origin.longitude, self.origin.latitude],
                [self.destination.longitude, self.destination.latitude],
            ],
            "strategy": self.strategy,
            "request_alternatives": self.request_alternatives,
            "avoid_tolls": self.avoid_tolls,
        }
        return sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:20]

    def fastest_route_id(self, profile: str) -> str:
        """Identificador estable que comparten las estrategias del mismo arco y perfil."""
        canonical = json.dumps({
            "origin": self.origin.city_id,
            "destination": self.destination.city_id,
            "origin_lon_lat": [self.origin.longitude, self.origin.latitude],
            "destination_lon_lat": [self.destination.longitude, self.destination.latitude],
            "profile": profile,
        }, sort_keys=True)
        return "ors-fast-" + sha256(canonical.encode()).hexdigest()[:16]


class RouteProvider(Protocol):
    provider_name: str

    def fetch(self, request: AcquisitionRequest) -> tuple[dict, dict, tuple[RouteAlternative, ...]]:
        """Devuelve petición sanitizada, respuesta original y alternativas normalizadas."""
        ...


@dataclass(frozen=True)
class AcquisitionSummary:
    requested: int
    acquired: int
    skipped_existing: int
    failed: int
    http_requests: int = 0


class AcquisitionManager:
    """Procesa solicitudes con checkpoint por arco y evita llamadas duplicadas."""

    def __init__(self, provider: RouteProvider, store: RouteStore, *, daily_quota: int | None = None) -> None:
        if daily_quota is not None and daily_quota < 1:
            raise ValueError("daily_quota debe ser positivo")
        self.provider = provider
        self.store = store
        self.daily_quota = daily_quota

    def run(
        self,
        requests: Sequence[AcquisitionRequest],
        *,
        max_requests: int,
        refresh: bool = False,
    ) -> AcquisitionSummary:
        if max_requests < 0:
            raise ValueError("max_requests no puede ser negativo")
        attempts_before = int(getattr(self.provider, "http_requests_made", 0))
        original_count = len(requests)
        namespace = getattr(self.provider, "cache_namespace",
                            f"{self.provider.provider_name}:{getattr(self.provider, 'profile', '')}")
        unique: dict[str, AcquisitionRequest] = {}
        for request in requests:
            key = f"{namespace}:{request.request_id}"
            unique.setdefault(key, request)
        requests = tuple(unique.values())
        duplicates = original_count - len(requests)
        if len(requests) > max_requests:
            raise ValueError(
                f"el lote contiene {len(requests)} solicitudes y supera max_requests={max_requests}"
            )
        pending = [request for request in requests if refresh or not self.store.request_succeeded(
            f"{namespace}:{request.request_id}"
        )]
        if self.daily_quota is not None:
            today = datetime.now(timezone.utc).date().isoformat()
            prefix = f"{namespace}:"
            used = self.store.count_acquired_on(today, prefix)
            if len(pending) > max(0, self.daily_quota - used):
                raise ValueError(f"el lote pendiente ({len(pending)}) supera la cuota restante del día "
                                 f"({max(0, self.daily_quota - used)})")
        acquired, skipped, failed = 0, duplicates, 0
        for request in requests:
            request_id = f"{namespace}:{request.request_id}"
            if self.store.request_succeeded(request_id) and not refresh:
                skipped += 1
                continue
            try:
                safe_request, response, alternatives = self.provider.fetch(request)
                self.store.save_success(request_id, safe_request, response, alternatives)
                acquired += 1
            except Exception as exc:
                # No registrar cuerpo de excepción ni cabeceras: podrían incluir datos sensibles.
                self.store.save_failure(request_id, type(exc).__name__)
                failed += 1
        return AcquisitionSummary(original_count, acquired, skipped, failed,
                                  int(getattr(self.provider, "http_requests_made", 0)) - attempts_before)
