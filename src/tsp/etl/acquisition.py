"""Manifiesto estable y reanudable de solicitudes dirigidas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Protocol, Sequence

from ..cities import City
from ..alternatives import RouteAlternative
from .store import PersistenceError, RouteStore


@dataclass(frozen=True)
class AcquisitionRequest:
    """Solicitud de ruta dirigida; las coordenadas se envían como lon,lat."""

    origin: City
    destination: City
    strategy: str = "fastest"
    request_alternatives: int = 0
    avoid_tolls: bool = False
    extra_info: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.origin.city_id == self.destination.city_id:
            raise ValueError("una solicitud de ruta debe conectar ciudades distintas")
        if self.strategy not in {"fastest", "avoid_tolls", "alternatives"}:
            raise ValueError("strategy debe ser fastest, avoid_tolls o alternatives")
        if not 0 <= self.request_alternatives <= 3:
            raise ValueError("ORS permite solicitar como máximo tres alternativas")
        extras = tuple(self.extra_info)
        if len(extras) != len(set(extras)) or set(extras) - {"tollways", "osmid", "waycategory"}:
            raise ValueError("extra_info debe contener valores únicos: tollways, osmid, waycategory")
        object.__setattr__(self, "extra_info", tuple(sorted(extras)))
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
        # Omitir la clave vacía conserva las huellas de las adquisiciones anteriores.
        if self.extra_info:
            canonical["extra_info"] = self.extra_info
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
    http_status_codes: tuple[int, ...] = ()
    failures: tuple[dict, ...] = ()
    not_attempted: int = 0
    stopped_reason: str | None = None


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
        status_codes_before = len(getattr(self.provider, "http_status_codes", ()))
        original_count = len(requests)
        namespace = getattr(self.provider, "cache_namespace",
                            f"{self.provider.provider_name}:{getattr(self.provider, 'profile', '')}")
        unique: dict[str, AcquisitionRequest] = {}
        stopped_reason = None
        not_attempted = 0
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
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(hours=24)
            prefix = f"{namespace}:"
            used = self.store.count_http_requests_since(window_start, prefix)
            remaining = max(0, self.daily_quota - used)
            if len(pending) > remaining:
                raise ValueError(f"el lote pendiente ({len(pending)}) supera la cuota local restante "
                                 "de la ventana móvil de 24 horas "
                                 f"({remaining})")
            # El límite del proveedor es por intentos HTTP, incluidos reintentos.
            # Acotar el presupuesto del cliente evita que retries excedan el
            # guardarraíl local aunque el número de rutas pendientes quepa.
            provider_http_budget = getattr(self.provider, "max_http_requests", None)
            provider_http_used = int(getattr(self.provider, "http_requests_made", 0))
            if hasattr(self.provider, "max_http_requests"):
                daily_http_ceiling = provider_http_used + remaining
                self.provider.max_http_requests = (
                    daily_http_ceiling if provider_http_budget is None
                    else min(provider_http_budget, daily_http_ceiling)
                )
        acquired, skipped, failed = 0, duplicates, 0
        failure_details = []
        for request_index, request in enumerate(requests):
            request_id = f"{namespace}:{request.request_id}"
            if self.store.request_succeeded(request_id) and not refresh:
                skipped += 1
                continue
            request_attempts_before = int(getattr(self.provider, "http_requests_made", 0))
            request_status_before = len(getattr(self.provider, "http_status_codes", ()))
            stage = "provider_request"
            try:
                safe_request, response, alternatives = self.provider.fetch(request)
                safe_request = dict(safe_request)
                safe_request["acquisition"] = {
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                    "request_id": request_id,
                    "origin_id": request.origin.city_id,
                    "destination_id": request.destination.city_id,
                    "strategy": request.strategy,
                    "profile": getattr(self.provider, "profile", ""),
                    "fastest_route_id": request.fastest_route_id(
                        getattr(self.provider, "profile", "")
                    ),
                    "is_primary_fastest": bool(
                        request.strategy == "fastest" and not request.avoid_tolls
                        and not request.extra_info
                    ),
                    "extra_info": list(request.extra_info),
                    "http_requests": int(getattr(self.provider, "http_requests_made", 0))
                    - request_attempts_before,
                    "http_status_codes": list(
                        getattr(self.provider, "http_status_codes", ())[request_status_before:]
                    ),
                    "rate_limit_headers": dict(
                        getattr(self.provider, "last_rate_limit_headers", {})
                    ),
                }
                stage = "persistence"
                self.store.save_success(request_id, safe_request, response, alternatives)
                acquired += 1
                remaining = (getattr(self.provider, "last_rate_limit_headers", {})
                             .get("x-ratelimit-remaining"))
                try:
                    remaining_count = int(remaining) if remaining is not None else None
                except (TypeError, ValueError):
                    remaining_count = None
                if remaining_count is not None and remaining_count <= 0:
                    stopped_reason = "provider_reported_no_remaining_quota"
                    not_attempted = sum(
                        1 for remaining_request in requests[request_index + 1:]
                        if refresh or not self.store.request_succeeded(
                            f"{namespace}:{remaining_request.request_id}"
                        )
                    )
                    break
                if remaining_count is not None and hasattr(self.provider, "max_http_requests"):
                    # Un encabezado actual del proveedor prevalece sobre el
                    # guardarraíl local; el reset no se interpreta como
                    # medianoche ni se toma de snapshots de otra ejecución.
                    current_http = int(getattr(self.provider, "http_requests_made", 0))
                    provider_ceiling = current_http + remaining_count
                    configured_ceiling = getattr(self.provider, "max_http_requests", None)
                    self.provider.max_http_requests = (
                        provider_ceiling if configured_ceiling is None
                        else min(configured_ceiling, provider_ceiling)
                    )
            except Exception as exc:
                attempts = (int(getattr(self.provider, "http_requests_made", 0))
                            - request_attempts_before)
                statuses = tuple(getattr(self.provider, "http_status_codes", ())[request_status_before:])
                is_persistence_error = isinstance(exc, PersistenceError) or stage == "persistence"
                is_provider_diagnostic = all(hasattr(exc, attribute) for attribute in
                                             ("category", "stage", "http_status_code"))
                error_stage = (getattr(exc, "stage", stage) if is_provider_diagnostic
                               else "persistence" if is_persistence_error else stage)
                category = ("persistence_error" if is_persistence_error else
                            getattr(exc, "category", type(exc).__name__) if is_provider_diagnostic
                            else "unexpected_error")
                safe_message = (str(exc) if is_persistence_error or is_provider_diagnostic else
                                f"fallo inesperado durante la solicitud ({type(exc).__name__})")
                secret = getattr(self.provider, "api_key", None)
                if secret:
                    safe_message = safe_message.replace(secret, "[REDACTED]")
                status_code = getattr(exc, "http_status_code", None) if is_provider_diagnostic else None
                if status_code is None and statuses:
                    status_code = statuses[-1]
                diagnostic = {
                    "category": category, "message": safe_message,
                    "http_status_code": status_code,
                    "stage": error_stage,
                    "http_request_counted": attempts > 0,
                    "origin_id": request.origin.city_id,
                    "destination_id": request.destination.city_id,
                    "strategy": request.strategy,
                    "extra_info": list(request.extra_info),
                    "profile": getattr(self.provider, "profile", None),
                    "endpoint": getattr(self.provider, "endpoint", None),
                    "effective_endpoint": (
                        f"{getattr(self.provider, 'endpoint', '').rstrip('/')}/"
                        f"{getattr(self.provider, 'profile', '')}/geojson"
                        if getattr(self.provider, "endpoint", None) else None
                    ),
                    "timeout_seconds": getattr(self.provider, "timeout_seconds", None),
                    "provider_may_have_processed_request": (
                        attempts > 0 and (
                            status_code is not None
                            or category not in {"connection_refused", "dns_error"}
                        )
                    ),
                    "response_received": bool(status_code is not None and 200 <= status_code < 300),
                    "rate_limit_headers": dict(
                        getattr(self.provider, "last_rate_limit_headers", {})
                    ),
                }
                if isinstance(exc, PersistenceError):
                    diagnostic.update({
                        "persistence_exception_type": exc.cause_type,
                        "persistence_message": exc.cause_message.replace(secret, "[REDACTED]")
                        if secret else exc.cause_message,
                        "persistence_operation": exc.operation,
                        "persistence_stage": exc.stage,
                        "persistence_resource": exc.resource,
                        "raw_response_file": exc.raw_response_file,
                        "raw_response_available": exc.raw_response_available,
                        "offline_recovery_possible": exc.raw_response_available,
                    })
                elif is_persistence_error:
                    diagnostic.update({
                        "persistence_exception_type": type(exc).__name__,
                        "persistence_message": safe_message,
                        "persistence_operation": "save_success",
                        "persistence_stage": "unknown_write_stage",
                        "persistence_resource": None,
                        "raw_response_file": None,
                        "raw_response_available": False,
                        "offline_recovery_possible": False,
                    })
                diagnostic_path = self.store.save_failure(
                    request_id, type(exc).__name__,
                    http_requests=attempts, http_status_codes=statuses, diagnostic=diagnostic,
                )
                failure_details.append({"request_id": request.request_id,
                                        **diagnostic, "http_requests": attempts,
                                        "http_status_codes": statuses,
                                        "diagnostic_file": diagnostic_path})
                failed += 1
                if category in {"authentication_rejected", "rate_limited", "persistence_error",
                                "http_budget_exhausted", "connection_refused", "dns_error",
                                "connection_error", "transport_error"}:
                    stopped_reason = category
                    not_attempted = sum(
                        1 for remaining in requests[request_index + 1:]
                        if refresh or not self.store.request_succeeded(
                            f"{namespace}:{remaining.request_id}"
                        )
                    )
                    break
        return AcquisitionSummary(original_count, acquired, skipped, failed,
                                  int(getattr(self.provider, "http_requests_made", 0)) - attempts_before,
                                  tuple(getattr(self.provider, "http_status_codes", ())[status_codes_before:]),
                                  tuple(failure_details), not_attempted, stopped_reason)
