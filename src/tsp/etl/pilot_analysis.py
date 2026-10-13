"""Análisis reproducible de un piloto ORS a partir de archivos locales."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Sequence

from ..alternatives import RouteAlternative
from ..cities import City
from .economics import FuelEconomics, apply_fuel_economics
from .store import RouteStore


PILOT_PAIRS = (
    ("madrid", "toledo"),
    ("toledo", "madrid"),
    ("bizkaia", "zaragoza"),
    ("zaragoza", "bizkaia"),
    ("madrid", "a_coruna"),
    ("barcelona", "girona"),
)
HOUR_VALUES_EUR = (10.0, 25.0, 50.0)


def analyze_ors_pilot(
    cities: Sequence[City],
    store: RouteStore,
    economics: FuelEconomics,
    *,
    pairs: Sequence[tuple[str, str]] = PILOT_PAIRS,
) -> list[dict[str, object]]:
    """Valida y compara los registros rápidos y avoid_tolls del piloto local.

    Comprueba cada alternativa contra la respuesta cruda enlazada en el estado
    incremental. Nunca clasifica avoid_tolls como peaje verificado sin costo.
    """
    city_by_id = {city.city_id: city for city in cities}
    if len(city_by_id) != len(cities):
        raise ValueError("el catálogo de ciudades contiene ids duplicados")
    for origin_id, destination_id in pairs:
        if origin_id not in city_by_id or destination_id not in city_by_id:
            raise ValueError(f"arco fuera del catálogo: {origin_id}->{destination_id}")

    records = store.load_alternatives()
    identity_keys = [(r.origin_id, r.destination_id, r.alternative_id) for r in records]
    if len(identity_keys) != len(set(identity_keys)):
        raise ValueError("hay identificadores de alternativa duplicados")
    records = apply_fuel_economics(records, economics, scenario="reference")
    raw_by_alternative = _load_raw_associations(store)
    rows: list[dict[str, object]] = []

    for origin_id, destination_id in pairs:
        arc_records = [r for r in records if (r.origin_id, r.destination_id) ==
                       (origin_id, destination_id)]
        fastest = [r for r in arc_records if _strategy(raw_by_alternative, r) == "fastest"]
        avoid = [r for r in arc_records if _strategy(raw_by_alternative, r) == "avoid_tolls"]
        if len(fastest) != 1 or len(avoid) != 1 or len(arc_records) != 2:
            raise ValueError(
                f"se esperaba una ruta de cada estrategia para {origin_id}->{destination_id}; "
                f"fastest={len(fastest)}, avoid_tolls={len(avoid)}, total={len(arc_records)}"
            )
        fast, candidate = fastest[0], avoid[0]
        if candidate.fastest_route_id != fast.alternative_id:
            raise ValueError(f"la candidata no referencia la ruta rápida de {origin_id}->{destination_id}")
        if fast.alternative_id != fast.fastest_route_id:
            raise ValueError(f"Modelo A no tiene su ruta rápida en {origin_id}->{destination_id}")

        fast_raw = raw_by_alternative[fast.alternative_id]
        avoid_raw = raw_by_alternative[candidate.alternative_id]
        _validate_raw_observation(fast, fast_raw, city_by_id[origin_id], city_by_id[destination_id])
        _validate_raw_observation(candidate, avoid_raw, city_by_id[origin_id], city_by_id[destination_id])

        fast_fuel = fast.fuel_cost_eur
        avoid_fuel = candidate.fuel_cost_eur
        if fast_fuel is None or avoid_fuel is None:
            raise ValueError("no se pudo calcular combustible con los parámetros económicos")
        delta_km = candidate.distance_km - fast.distance_km
        delta_hours = candidate.duration_hours - fast.duration_hours
        delta_fuel = avoid_fuel - fast_fuel
        row: dict[str, object] = {
            "origin_id": origin_id,
            "origin_name": city_by_id[origin_id].name,
            "destination_id": destination_id,
            "destination_name": city_by_id[destination_id].name,
            "fastest_alternative_id": fast.alternative_id,
            "avoid_tolls_alternative_id": candidate.alternative_id,
            "fastest_distance_km": fast.distance_km,
            "avoid_tolls_distance_km": candidate.distance_km,
            "distance_delta_km": delta_km,
            "distance_delta_percent": delta_km / fast.distance_km * 100.0,
            "fastest_duration_hours": fast.duration_hours,
            "avoid_tolls_duration_hours": candidate.duration_hours,
            "fastest_duration_minutes": fast.duration_hours * 60.0,
            "avoid_tolls_duration_minutes": candidate.duration_hours * 60.0,
            "time_delta_minutes": delta_hours * 60.0,
            "time_delta_percent": delta_hours / fast.duration_hours * 100.0,
            "fastest_fuel_eur": fast_fuel,
            "avoid_tolls_fuel_eur": avoid_fuel,
            "fuel_delta_eur": delta_fuel,
            "vehicle_configuration": fast.vehicle_configuration,
            "fuel_consumption_l_per_100km": fast.fuel_consumption_l_per_100km,
            "fuel_price_eur_per_l": fast.fuel_price_eur_per_l,
            "fuel_price_reference": fast.fuel_price_reference,
            "geometries_equal": fast.geometry_lon_lat == candidate.geometry_lon_lat,
            "fastest_toll_status": fast.toll_status.value,
            "fastest_toll_eur": fast.toll_cost_eur,
            "avoid_tolls_toll_status": candidate.toll_status.value,
            "avoid_tolls_toll_eur": candidate.toll_cost_eur,
            "fastest_acquired_at_utc": fast_raw["acquisition"]["acquired_at"],
            "avoid_tolls_acquired_at_utc": avoid_raw["acquisition"]["acquired_at"],
            "fastest_request_id": fast_raw["request_id"],
            "avoid_tolls_request_id": avoid_raw["request_id"],
            "fastest_data_source": fast.source,
            "avoid_tolls_data_source": candidate.source,
            "routing_profile": fast.profile,
            "routing_engine_version": fast.routing_engine_version,
            "network_data_version": fast.network_data_version,
            "fastest_http_status": 200,
            "avoid_tolls_http_status": 200,
        }
        for hour_value in HOUR_VALUES_EUR:
            if not math.isfinite(float(hour_value)) or float(hour_value) < 0:
                raise ValueError("los valores horarios deben ser finitos y no negativos")
            # Ahorro neto de peaje requerido: P_fast - P_avoid debe superar este umbral.
            row[f"toll_saving_required_at_{_number_token(hour_value)}_eur"] = (
                float(hour_value) * delta_hours + delta_fuel
            )
        rows.append(row)
    return rows


def write_ors_pilot_report(rows: Sequence[dict[str, object]], output_dir: str | Path) -> tuple[Path, Path]:
    """Escribe el CSV y el resumen Markdown en la carpeta local indicada."""
    if not rows:
        raise ValueError("el informe necesita al menos una comparación")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "ors_pilot_comparison.csv"
    markdown_path = output / "ors_pilot_summary.md"
    fields = list(rows[0])
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    markdown_path.write_text(_render_markdown(rows), encoding="utf-8")
    return csv_path, markdown_path


def _load_raw_associations(store: RouteStore) -> dict[str, dict]:
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    associations: dict[str, dict] = {}
    for request_id, entry in state.get("requests", {}).items():
        if entry.get("status") != "adquirida":
            continue
        raw_path = Path(entry["raw_file"])
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        raw_record = json.loads(raw_path.read_text(encoding="utf-8"))
        acquisition = raw_record.get("request", {}).get("acquisition", {})
        if (raw_record.get("request_id") != request_id
                or acquisition.get("http_requests") != 1
                or acquisition.get("http_status_codes") != [200]):
            raise ValueError(f"respuesta/procedencia incompleta para {request_id}")
        for index, alternative_id in enumerate(entry.get("active_alternative_ids", [])):
            if alternative_id in associations:
                raise ValueError(f"alternativa asociada a más de una respuesta: {alternative_id}")
            features = raw_record.get("response", {}).get("features", [])
            if index >= len(features):
                raise ValueError(f"falta el feature {index} de la respuesta {request_id}")
            body = raw_record.get("request", {}).get("body", {})
            options = body.get("options", {})
            strategy = "avoid_tolls" if "tollways" in options.get("avoid_features", []) else "fastest"
            associations[alternative_id] = {
                "request_id": request_id,
                "acquisition": acquisition,
                "body": body,
                "feature": features[index],
                "strategy": strategy,
                "response_metadata": raw_record.get("response", {}).get("metadata", {}),
            }
    return associations


def _strategy(raw_by_alternative: dict[str, dict], record: RouteAlternative) -> str:
    try:
        return str(raw_by_alternative[record.alternative_id]["strategy"])
    except KeyError as exc:
        raise ValueError(f"no se encuentra respuesta cruda para {record.alternative_id}") from exc


def _validate_raw_observation(
    record: RouteAlternative,
    raw: dict,
    origin: City,
    destination: City,
) -> None:
    body = raw["body"]
    coordinates = body.get("coordinates")
    expected = [[float(origin.longitude), float(origin.latitude)],
                [float(destination.longitude), float(destination.latitude)]]
    if coordinates != expected:
        raise ValueError(f"coordenadas de solicitud no corresponden a {origin.city_id}->{destination.city_id}")
    feature = raw["feature"]
    properties = feature.get("properties", {})
    summary = properties.get("summary", {})
    geometry_data = feature.get("geometry", {}).get("coordinates", [])
    geometry = tuple((float(point[0]), float(point[1])) for point in geometry_data)
    if len(geometry) < 2 or geometry != record.geometry_lon_lat:
        raise ValueError(f"geometría ausente o distinta de la persistida para {record.alternative_id}")
    if not math.isclose(float(summary["distance"]) / 1000.0, record.distance_km, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"distancia del catálogo no coincide con la respuesta de {record.alternative_id}")
    if not math.isclose(float(summary["duration"]) / 3600.0, record.duration_hours, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"duración del catálogo no coincide con la respuesta de {record.alternative_id}")
    if record.acquired_on != str(raw["acquisition"]["acquired_at"])[:10]:
        raise ValueError(f"fecha de adquisición no coincide para {record.alternative_id}")
    if not raw["response_metadata"].get("engine", {}).get("version"):
        raise ValueError(f"falta la versión de motor en {record.alternative_id}")


def _number_token(value: float) -> str:
    return f"{float(value):g}".replace(".", "_")


def _render_markdown(rows: Sequence[dict[str, object]]) -> str:
    first = rows[0]
    lines = [
        "# Comparación local del piloto ORS: rutas rápidas y candidatas sin peajes",
        "",
        "Generado offline desde `route_alternatives.csv`, `acquisition_state.json` y las respuestas crudas locales.",
        "El informe no contiene geometrías ni respuestas crudas.",
        "",
        "## Metodología",
        "",
        f"- Vehículo `{first['vehicle_configuration']}`, consumo {float(first['fuel_consumption_l_per_100km']):.1f} L/100 km, gasolina a {float(first['fuel_price_eur_per_l']):.9f} €/L.",
        "- Combustible = distancia (km) / 100 × consumo × precio, según `configs/tsp_economics.yaml`.",
        "- Diferencias porcentuales y absolutas se calculan como `avoid_tolls - fastest`.",
        "- El umbral satisface `P_fast - P_avoid > v·(T_avoid - T_fast) + (F_avoid - F_fast)`; la igualdad implica empate.",
        "- `avoid_tolls` no acredita peaje cero. Las tarifas monetarias de todos estos registros permanecen desconocidas.",
        "- El umbral es ahorro de peaje requerido, no un ahorro medido. Las alternativas no son exhaustivas.",
        "",
        "## Comparación",
        "",
        "| Arco | Rápida km/min | Avoid km/min | Δ km (%) | Δ min (%) | Combustible rápida / avoid / Δ € | Geometría | Peaje rápida / avoid | Ahorro requerido 10 / 25 / 50 €/h |",
        "|---|---:|---:|---:|---:|---:|---|---|---:|",
    ]
    for row in rows:
        geometry = "igual" if row["geometries_equal"] else "diferente"
        thresholds = " / ".join(
            f"{float(row[f'toll_saving_required_at_{_number_token(v)}_eur']):.2f}"
            for v in HOUR_VALUES_EUR
        )
        lines.append(
            f"| {row['origin_name']} → {row['destination_name']} "
            f"| {float(row['fastest_distance_km']):.2f} / {float(row['fastest_duration_minutes']):.2f} "
            f"| {float(row['avoid_tolls_distance_km']):.2f} / {float(row['avoid_tolls_duration_minutes']):.2f} "
            f"| {float(row['distance_delta_km']):+.2f} ({float(row['distance_delta_percent']):+.2f}%) "
            f"| {float(row['time_delta_minutes']):+.2f} ({float(row['time_delta_percent']):+.2f}%) "
            f"| {float(row['fastest_fuel_eur']):.2f} / {float(row['avoid_tolls_fuel_eur']):.2f} / "
            f"{float(row['fuel_delta_eur']):+.2f} | {geometry} "
            f"| {row['fastest_toll_status']} / {row['avoid_tolls_toll_status']} | {thresholds} |"
        )
    lines.extend([
        "",
        "## Alcance",
        "",
        "El Modelo A puede recuperar la ruta cuyo id coincide con `fastest_route_id`. El contrato de alternativas conserva también cada candidata para el Modelo B. Sin peajes verificados no es posible comparar el costo económico completo ni construir una matriz económica completa. Los resultados de tiempo son estimaciones del perfil ORS, no tiempos de tráfico medidos.",
        "",
    ])
    return "\n".join(lines)
