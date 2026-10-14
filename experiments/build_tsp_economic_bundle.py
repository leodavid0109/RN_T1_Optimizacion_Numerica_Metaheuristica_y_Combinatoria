"""Build a local, offline economic TSP bundle from saved ORS route snapshots.

No API is called. The numeric experimental bundle uses the explicitly
uncalibrated tollway-kilometre proxy; strict matrices remain separate.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from statistics import mean

from experiments.build_tsp_exploratory_economics import (
    DATASET_DEFAULT, ROUTES_DEFAULT, build_exploratory_economics,
    proxy_rate_scenarios,
)
from src.tsp.etl.dataset_export import REPO_ROOT, load_published_dataset


DEFAULT_OUTPUT = REPO_ROOT / "data/datasets/spain_tsp_economic_20261013"
WORK_OUTPUT = REPO_ROOT / "data/processed/tolls/economic_20261013_work"
HOURS = (10, 25, 50)
LEVELS = ("low", "base", "high")
csv.field_size_limit(100_000_000)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matrix_rows(order: tuple[str, ...], matrix: list[list[float]], *, choice: bool = False) -> list[dict]:
    return [{"city_id": city, **{
        dest: (str(matrix[i][j]) if choice else format(float(matrix[i][j]), ".15g"))
        for j, dest in enumerate(order)
    }} for i, city in enumerate(order)]


_ROAD_REF = re.compile(r"(?<![A-Z0-9])(?:AP|AG|AC|A|R|C|N|M)\s*-\s*\d{1,3}[A-Z]?(?![A-Z0-9])", re.IGNORECASE)


def _corridor_candidates(labels: list[str]) -> str:
    refs = set()
    for label in labels:
        for match in _ROAD_REF.findall(str(label)):
            prefix, number = re.match(r"([A-Z]+)\s*-\s*(\d+[A-Z]?)", match, re.IGNORECASE).groups()
            refs.add(f"{prefix.upper()}-{number.upper()}")
    return ";".join(sorted(refs)) if refs else "UNRESOLVED"


def build_bundle(
    *, dataset_dir: Path = DATASET_DEFAULT, enriched_routes_path: Path = ROUTES_DEFAULT,
    output_dir: Path = DEFAULT_OUTPUT, work_dir: Path = WORK_OUTPUT,
) -> dict:
    base = build_exploratory_economics(dataset_dir, enriched_routes_path, work_dir)
    dataset = load_published_dataset(dataset_dir)
    order = tuple(dataset["city_order"])
    expected_pairs = len(order) * (len(order) - 1)
    route_rows = _read_rows(work_dir / "exploratory_route_costs.csv")
    proxy_rows = _read_rows(work_dir / "experimental_proxy_route_costs.csv")
    if len(route_rows) != expected_pairs or len(proxy_rows) != expected_pairs:
        raise ValueError("las tablas de rutas no cubren los 2.162 arcos del catálogo")
    by_pair = {(row["origin_id"], row["destination_id"]): row for row in route_rows}
    proxy_by_pair = {(row["origin_id"], row["destination_id"]): row for row in proxy_rows}
    expected = {(a, b) for a in order for b in order if a != b}
    if set(by_pair) != expected or set(proxy_by_pair) != expected:
        raise ValueError("pares dirigidos duplicados o ausentes en la tabla económica")

    output_dir.mkdir(parents=True, exist_ok=True)
    strict_dir = output_dir / "strict"
    strict_dir.mkdir(exist_ok=True)
    for value in HOURS:
        shutil.copyfile(work_dir / f"model_a_v{value}_eur.csv", strict_dir / f"model_a_strict_v{value}_eur.csv")
        shutil.copyfile(work_dir / f"model_b_best_known_option_v{value}_eur.csv",
                        strict_dir / f"model_b_strict_known_options_v{value}_eur.csv")

    proxy_rates = proxy_rate_scenarios()
    matrices: dict[tuple[str, int], list[list[float]]] = {}
    choices: dict[int, list[list[str]]] = {}
    for level in LEVELS:
        for value in HOURS:
            matrix = [[0.0 for _ in order] for _ in order]
            source = work_dir / f"model_a_proxy_{level}_v{value}_eur.csv"
            rows = _read_rows(source)
            if [row["city_id"] for row in rows] != list(order):
                raise ValueError(f"orden de ciudades incorrecto en {source.name}")
            for i, row in enumerate(rows):
                for j, city in enumerate(order):
                    matrix[i][j] = float(row[city])
            if any(not math.isfinite(x) or x < 0 for row in matrix for x in row):
                raise ValueError(f"matriz no finita o negativa: {source.name}")
            if any(matrix[i][i] != 0 for i in range(len(order))):
                raise ValueError(f"diagonal distinta de cero: {source.name}")
            matrices[(level, value)] = matrix

    # No local avoid_tolls snapshot has validated tollways/waycategory extras;
    # consequently the honest current Model B option set is fastest-only.
    for value in HOURS:
        choices[value] = [["FASTEST_ONLY" for _ in order] for _ in order]
        for i in range(len(order)):
            choices[value][i][i] = "DIAGONAL"

    for value in HOURS:
        _write_rows(output_dir / f"model_a_v{value}_eur.csv", ["city_id", *order],
                    _matrix_rows(order, matrices[("base", value)]))
        _write_rows(output_dir / f"model_b_v{value}_eur.csv", ["city_id", *order],
                    _matrix_rows(order, matrices[("base", value)]))
        _write_rows(output_dir / f"model_b_choice_v{value}.csv", ["city_id", *order],
                    _matrix_rows(order, choices[value], choice=True))
        for level in ("low", "high"):
            for model in ("model_a", "model_b"):
                _write_rows(output_dir / f"{model}_{level}_v{value}_eur.csv", ["city_id", *order],
                            _matrix_rows(order, matrices[(level, value)]))

    evidence_rows = []
    component_rows = []
    toll_matrix = [[0.0 for _ in order] for _ in order]
    index = {city: i for i, city in enumerate(order)}
    for pair in sorted(expected, key=lambda x: (index[x[0]], index[x[1]])):
        route = by_pair[pair]
        proxy = proxy_by_pair[pair]
        toll = float(proxy["proxy_toll_base_eur"])
        toll_matrix[index[pair[0]]][index[pair[1]]] = toll
        status = ("ZERO_ASSUMED_ORS" if proxy["proxy_status_base"] == "INFERRED_ZERO_ORS"
                  else proxy["proxy_status_base"])
        evidence_rows.append({
            "origin_id": pair[0], "destination_id": pair[1],
            "route_id": route["route_id"], "request_id": route["request_id"],
            "geometry_sha256": route["geometry_sha256"],
            "response_sha256": route["response_sha256"],
            "distance_km": route["distance_km"], "duration_hours": route["duration_hours"],
            "toll_distance_km": route["toll_distance_km"],
            "toll_status_experimental": status,
            "toll_eur_base": format(toll, ".15g"),
            "rate_eur_per_toll_km": format(proxy_rates["base"], ".15g"),
            "method": "ORS tollways km * 0.14145 EUR/km unless an existing route-level official tariff inference or ZERO_ASSUMED_ORS applies",
            "confidence": route["confidence"], "strictly_verified": "false",
            "reference_date": "2026-10-13", "reference_local_time": "12:00 Europe/Madrid",
            "vehicle_class": "turismo ligero", "payment": "general sin descuentos personales",
        })
        fuel = float(route["fuel_eur"])
        duration = float(route["duration_hours"])
        component = {
            "origin_id": pair[0], "destination_id": pair[1], "route_id": route["route_id"],
            "geometry_sha256": route["geometry_sha256"], "distance_km": route["distance_km"],
            "duration_hours": route["duration_hours"], "fuel_eur": format(fuel, ".15g"),
            "toll_eur_base": format(toll, ".15g"), "toll_status": status,
            "time_value_basis": "C=v*duration+fuel+toll",
        }
        for value in HOURS:
            component[f"time_cost_v{value}_eur"] = format(value * duration, ".15g")
            component[f"model_a_cost_v{value}_eur"] = format(value * duration + fuel + toll, ".15g")
            component[f"model_b_cost_v{value}_eur"] = component[f"model_a_cost_v{value}_eur"]
        component_rows.append(component)

    _write_rows(output_dir / "toll_fastest_eur.csv", ["city_id", *order], _matrix_rows(order, toll_matrix))
    _write_rows(output_dir / "toll_evidence.csv", list(evidence_rows[0]), evidence_rows)
    _write_rows(output_dir / "toll_components.csv", list(component_rows[0]), component_rows)

    sample_path = REPO_ROOT / "data/processed/tolls/exploratory_current/real_route_stratified_review_30.csv"
    sample_rows = _read_rows(sample_path) if sample_path.is_file() else []
    for row in sample_rows:
        source = by_pair.get((row["origin_id"], row["destination_id"]), {})
        proxy = proxy_by_pair.get((row["origin_id"], row["destination_id"]), {})
        proxy_status = proxy.get("proxy_status_base", "")
        row["economic_toll_status_base"] = (
            "ZERO_ASSUMED_ORS" if proxy_status == "INFERRED_ZERO_ORS" else proxy_status
        )
        row["economic_toll_eur_base"] = proxy.get("proxy_toll_base_eur", "")
        row["geometry_sha256"] = source.get("geometry_sha256", row.get("geometry_sha256", ""))
        row["audit_scope"] = "Revisión de consistencia de datos/etiquetas; no es ground truth independiente"
        row["predictive_validation_status"] = "NOT_VALIDATED_INDEPENDENTLY"
    if sample_rows:
        _write_rows(output_dir / "validation_sample_30.csv", list(sample_rows[0]), sample_rows)

    alternatives = []
    old_path = REPO_ROOT / "data/processed/routes/route_alternatives.csv"
    if old_path.is_file():
        for row in _read_rows(old_path):
            try:
                params = dict(json.loads(row.get("routing_parameters") or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                params = {}
            if params.get("strategy") == "avoid_tolls":
                alternatives.append({
                    "origin_id": row["origin_id"], "destination_id": row["destination_id"],
                    "alternative_id": row["alternative_id"], "distance_km": row["distance_km"],
                    "duration_hours": row["duration_hours"], "extra_info_status": "NOT_ACQUIRED",
                    "toll_status": "UNKNOWN", "eligible_for_model_b": "false",
                    "reason": "Snapshot heredado sin extras tollways/waycategory; no acredita ausencia de peajes.",
                })
    _write_rows(output_dir / "alternatives_inventory.csv",
                ["origin_id", "destination_id", "alternative_id", "distance_km", "duration_hours",
                 "extra_info_status", "toll_status", "eligible_for_model_b", "reason"], alternatives)

    available_avoid_pairs = {
        (row["origin_id"], row["destination_id"])
        for row in alternatives if row["eligible_for_model_b"] == "true"
    }
    avoid_queue = []
    for pair in expected:
        route = by_pair[pair]
        toll_km = float(route.get("toll_distance_km") or 0.0)
        if toll_km <= 0 or pair in available_avoid_pairs:
            continue
        proxy = proxy_by_pair[pair]
        avoid_queue.append({
            "origin_id": pair[0], "destination_id": pair[1],
            "priority_score": format(float(proxy["proxy_toll_base_eur"]), ".12g"),
            "toll_distance_km": format(toll_km, ".12g"),
            "estimated_toll_base_eur": proxy["proxy_toll_base_eur"],
            "reason": "Ruta rápida con tollways positivos; una alternativa permitiría comparar coste y tiempo.",
            "strategy": "avoid_tolls", "extra_info": "tollways,waycategory",
            "status": "PENDING_ALTERNATIVE_ACQUISITION", "valid_existing_alternative": "false",
        })
    avoid_queue.sort(key=lambda row: (-float(row["priority_score"]), row["origin_id"], row["destination_id"]))
    for priority, row in enumerate(avoid_queue, start=1):
        row["priority"] = priority
    _write_rows(output_dir / "avoid_tolls_pending.csv",
                ["priority", "origin_id", "destination_id", "priority_score", "toll_distance_km",
                 "estimated_toll_base_eur", "reason", "strategy", "extra_info", "status",
                 "valid_existing_alternative"], avoid_queue)

    break_even = [{"origin_id": row["origin_id"], "destination_id": row["destination_id"],
                   "fastest_route_id": row["route_id"], "alternative_route_id": "",
                   "v_critical_eur_per_hour": "", "status": "NO_VALID_FREE_ALTERNATIVE",
                   "reason": "No hay una opción avoid_tolls con extras y valoración tarifaria válidos."}
                  for row in evidence_rows]
    _write_rows(output_dir / "break_even_value_of_time.csv", list(break_even[0]), break_even)

    section_usage = []
    section_path = REPO_ROOT / "data/processed/tolls/ors_extra_info/enriched_routes.json"
    payload = json.loads(section_path.read_text(encoding="utf-8"))
    for route in payload["routes"]:
        sections = route.get("toll_sections") or []
        for ordinal, section in enumerate(sections, start=1):
            labels = section.get("instruction_refs") or section.get("instruction_names") or []
            corridor_candidate = _corridor_candidates(list(map(str, labels)))
            section_usage.append({
                "route_id": route["route_id"], "origin_id": route["origin_id"],
                "destination_id": route["destination_id"], "section_ordinal": ordinal,
                "corridor_label_candidate": corridor_candidate,
                "start_index": section.get("start_index"), "end_index": section.get("end_index"),
                "start_lon": (section.get("start_lon_lat") or [None, None])[0],
                "start_lat": (section.get("start_lon_lat") or [None, None])[1],
                "end_lon": (section.get("end_lon_lat") or [None, None])[0],
                "end_lat": (section.get("end_lon_lat") or [None, None])[1],
                "length_km_approx": section.get("length_km_approx"),
                "position_method": section.get("position_method"),
                "osm_way_ids": ";".join(map(str, section.get("osm_way_ids") or [])),
                "category_values": ";".join(map(str, section.get("waycategory_values") or [])),
                "geometry_hash": hashlib.sha256(json.dumps(
                    section.get("geometry_coordinates") or [], separators=(",", ":")
                ).encode()).hexdigest(),
            })
    _write_rows(output_dir / "toll_corridor_usage_candidates.csv",
                list(section_usage[0]) if section_usage else ["route_id"], section_usage)
    counts: dict[str, dict] = {}
    for row in section_usage:
        key = row["corridor_label_candidate"]
        item = counts.setdefault(key, {"corridor_label_candidate": key, "unique_directed_arcs": set(),
                                      "section_count": 0, "toll_km_observations": 0.0})
        item["unique_directed_arcs"].add((row["origin_id"], row["destination_id"]))
        item["section_count"] += 1
        item["toll_km_observations"] += float(row.get("length_km_approx") or 0)
    frequencies = [{"corridor_label_candidate": key,
                    "directed_arcs_using_candidate": len(item["unique_directed_arcs"]),
                    "toll_section_count": item["section_count"],
                    "sum_km_across_route_observations_not_unique_infrastructure": format(item["toll_km_observations"], ".12g"),
                    "identification_status": "INSTRUCTION_LABEL_CANDIDATE_NOT_INDEPENDENTLY_VERIFIED"}
                   for key, item in sorted(counts.items(), key=lambda kv: (-len(kv[1]["unique_directed_arcs"]), kv[0]))]
    _write_rows(output_dir / "corridor_frequency_candidates.csv", list(frequencies[0]) if frequencies else [], frequencies)
    observed_corridor_codes = sorted({
        ref for row in section_usage for ref in row["corridor_label_candidate"].split(";")
        if ref != "UNRESOLVED"
    })
    corridor_catalog_path = REPO_ROOT / "data/reference/toll_roads_2026.csv"
    known_corridor_count = len(_read_rows(corridor_catalog_path)) if corridor_catalog_path.is_file() else 0

    reference_files = {
        "data/reference/toll_tariffs_2026_curated.csv": "official_tariff_transcriptions_source.csv",
        "data/reference/toll_roads_2026.csv": "toll_corridor_catalog.csv",
        "data/processed/tolls/station_review/toll_stations.csv": "osm_station_catalog_partial.csv",
    }
    for relative, name in reference_files.items():
        source = REPO_ROOT / relative
        if source.is_file():
            shutil.copyfile(source, output_dir / name)
    city_catalog = dataset_dir / "cities.csv"
    if city_catalog.is_file():
        shutil.copyfile(city_catalog, output_dir / "cities.csv")

    sensitivity = []
    for value in HOURS:
        base_costs = [float(row[f"model_a_cost_v{value}_eur"]) for row in component_rows]
        for level in LEVELS:
            total_costs = []
            toll_values = []
            for pair in sorted(expected, key=lambda x: (index[x[0]], index[x[1]])):
                route = by_pair[pair]
                proxy = proxy_by_pair[pair]
                toll = float(proxy[f"proxy_toll_{level}_eur"])
                toll_values.append(toll)
                total_costs.append(value * float(route["duration_hours"]) + float(route["fuel_eur"]) + toll)
            sensitivity.append({
                "hour_value_eur_per_hour": value, "proxy_level": level,
                "proxy_rate_eur_per_toll_km": format(proxy_rates[level], ".15g"),
                "directed_arcs": len(total_costs), "mean_toll_eur": format(mean(toll_values), ".12g"),
                "max_toll_eur": format(max(toll_values), ".12g"),
                "mean_cost_eur": format(mean(total_costs), ".12g"),
                "mean_delta_vs_base_eur": format(mean(total_costs) - mean(base_costs), ".12g"),
                "valid_free_alternative_pairs": 0, "fastest_wins": "",
                "avoid_tolls_wins": "", "mean_savings_eur": "", "max_savings_eur": "",
                "mean_extra_time_when_avoiding_hours": "",
                "alternative_comparison_status": "NO_VALID_FREE_ALTERNATIVES",
                "interpretation": "HYPOTHETICAL_SENSITIVITY_NOT_CONFIDENCE_INTERVAL_OR_TARIFF",
            })
    _write_rows(output_dir / "sensitivity_summary.csv", list(sensitivity[0]), sensitivity)

    statuses = {}
    for row in evidence_rows:
        statuses[row["toll_status_experimental"]] = statuses.get(row["toll_status_experimental"], 0) + 1
    metadata = {
        "schema_version": 1, "dataset": "data/datasets/spain_tsp_2026",
        "scenario_name": "MODELO ECONOMICO EXPERIMENTAL NACIONAL; NO ES TARIFARIO VERIFICADO",
        "reference_date": "2026-10-13", "reference_local_time": "martes 12:00 Europe/Madrid",
        "vehicle": "turismo ligero; BMW 120 F70", "payment": "general sin descuentos personales",
        "currency": "EUR", "fuel_consumption_l_per_100km": 5.4,
        "fuel_price_eur_per_l": 1.849098398, "hour_values_eur_per_hour": list(HOURS),
        "directed_arcs": expected_pairs, "fastest_routes": len(route_rows),
        "toll_status_counts": statuses, "numeric_model_a_arcs": expected_pairs,
        "known_corridor_catalog_records": known_corridor_count,
        "distinct_corridor_codes_candidate_in_route_instructions": observed_corridor_codes,
        "toll_section_observations": len(section_usage),
        "toll_section_sum_km_across_directed_route_observations_not_unique_roads": round(
            sum(float(row.get("length_km_approx") or 0) for row in section_usage), 6
        ),
        "toll_sections_without_specific_corridor_candidate": sum(
            row["corridor_label_candidate"] == "UNRESOLVED" for row in section_usage
        ),
        "stratified_route_review_count": len(sample_rows),
        "predictive_validation": False,
        "numeric_model_b_arcs": expected_pairs,
        "model_b_definition": "minimum among available validated options; current valid option set has fastest only",
        "valid_avoid_tolls_alternatives": 0, "historical_unclassified_avoid_tolls_options": len(alternatives),
        "avoid_tolls_queue_arcs": len(avoid_queue),
        "avoid_tolls_pilot_known_connection_refused_attempts": 20,
        "avoid_tolls_followup_attempt_count": None,
        "avoid_tolls_followup_interrupted": True,
        "avoid_tolls_pilot_http_responses": 0,
        "avoid_tolls_pilot_outcome": "20 logged connection refusals; a subsequent elevated attempt was interrupted without summary, so its attempted count is unknown; zero responses persisted; no further calls after user stop",
        "proxy": {"central_eur_per_toll_km": 0.14145, "low_fraction": 0.5,
                  "base_fraction": 1.0, "high_fraction": 1.5,
                  "status": "ESTIMATED_PROXY_UNCALIBRATED",
                  "not_a_national_tariff": True,
                  "official_route_pair_inferences_preserved": True},
        "zero_policy": "ZERO_ASSUMED_ORS only if valid complete tollways/waycategory extras show no toll sections",
        "strict_outputs": "strict/ contains blank UNKNOWN entries; it is not a finite ACO matrix",
        "matrices_are_finite_for_algorithms": True,
        "limitations": [
            "The per-km proxy is a transparent user-specified sensitivity assumption, not predictive validation.",
            "ZERO_ASSUMED_ORS is not official certification that a route is toll-free.",
            "The only 6 stored historical avoid_tolls alternatives lack complete enriched toll classification and are excluded.",
            "Model B currently equals FASTEST_ONLY; its option set is not a meaningful free-route comparison and is not exhaustive.",
            "Corridor frequencies are candidate labels from ORS instruction names, not a spatially validated unique-road inventory.",
            "No route-level toll total is OFFICIAL_VERIFIED; AP-68/AP-9 inferences remain exploratory.",
            "No independent predictive validation sample supports error-rate claims for the proxy.",
        ],
        "sources": ["ORS directions enriched snapshots, CC BY-SA 4.0 attribution applies",
                    "OpenStreetMap contributors, ODbL attribution applies",
                    "data/reference/toll_tariffs_2026_curated.csv; route-specific pairing is not certified"],
        "input_sha256": {
            "enriched_routes_summary": _sha256(enriched_routes_path),
            "published_dataset_sha256_manifest": _sha256(dataset_dir / "SHA256SUMS.txt"),
            "curated_tariffs": (_sha256(REPO_ROOT / "data/reference/toll_tariffs_2026_curated.csv")
                                if (REPO_ROOT / "data/reference/toll_tariffs_2026_curated.csv").is_file()
                                else None),
            "partial_osm_station_catalog": (
                _sha256(REPO_ROOT / "data/processed/tolls/station_review/toll_stations.csv")
                if (REPO_ROOT / "data/processed/tolls/station_review/toll_stations.csv").is_file()
                else None
            ),
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = [
        "# TSP España — matrices económicas experimentales (13-10-2026)", "",
        "Este paquete permite ejecutar offline matrices finitas para experimentación. No es un tarifario real completo ni prueba que los precios estimados sean exactos.", "",
        "## Escenario", "",
        "Martes 13-10-2026, 12:00 hora peninsular; turismo ligero BMW 120 F70; pago general sin descuentos; combustible 5,4 L/100 km a 1,849098398 EUR/L; valor del tiempo 10, 25 o 50 EUR/h.", "",
        "## Archivos", "",
        "- `model_a_v{10,25,50}_eur.csv`: ruta rápida ORS, costes numéricos con los supuestos descritos.",
        "- `model_b_v{10,25,50}_eur.csv`: misma matriz mientras no haya alternativa libre enriquecida válida.",
        "- `model_b_choice_v{10,25,50}.csv`: todas las celdas no diagonales indican `FASTEST_ONLY`.",
        "- `model_a_{low,high}_v*_eur.csv` y `model_b_{low,high}_v*_eur.csv`: sensibilidad al 50/150 % del proxy central.",
        "- `strict/`: matrices estrictas parciales; celdas vacías siguen siendo UNKNOWN.",
        "- `toll_evidence.csv`, `toll_components.csv`, `toll_fastest_eur.csv`: trazabilidad por arco.",
        "- `toll_corridor_usage_candidates.csv`, `corridor_frequency_candidates.csv`: intervalos/etiquetas candidatos; no son un inventario espacial único certificado.",
        "- `toll_corridor_catalog.csv`, `official_tariff_transcriptions_source.csv`, `osm_station_catalog_partial.csv`: referencias locales, con atribución y alcance parcial.",
        "- `alternatives_inventory.csv`: seis opciones históricas sin extras completos; excluidas del Modelo B.",
        "- `validation_sample_30.csv`: 30 arcos revisados estructuralmente por estratos; no son una muestra de ground truth tarifario independiente.",
        "- `cities.csv`: catálogo ordenado de 47 ciudades; coincide con el dataset vial base.",
        "- `avoid_tolls_pending.csv`: cola pendiente de rutas con tollways positivos, ordenada por coste proxy (priorización, no garantía de ahorro).",
        "- `break_even_value_of_time.csv`: no calculado donde no existe alternativa libre validada.",
        "- `metadata.json`, `LICENSE-DATA.md`, `SHA256SUMS.txt`: parámetros, límites, atribución y hashes.", "",
        "## Matriz recomendada para la prueba del compañero", "",
        "Para probar ACO o GA con peajes, cargue `model_a_v25_eur.csv`: es el Modelo A experimental base, en EUR por arco dirigido, con valor del tiempo de 25 EUR/h. Use el orden de `cities.csv`, cierre el tour regresando a su ciudad inicial y entregue a ambos algoritmos exactamente la misma matriz y presupuesto de evaluaciones. 25 EUR/h es el escenario central entre las sensibilidades, no una estimación oficial del valor social del tiempo.", "",
        "El supuesto de recorrido completo se aplica solo a pares concretos con corredor indicado por ORS: AP-68 Bilbao–Zaragoza (39,90 EUR por sentido), AP-9 A Coruña–Pontevedra (8,80 + 7,55 = 16,35 EUR por sentido) y C-32 Tarragona–Barcelona (8,42 EUR de la barrera Vallcarca, una vez por sentido). Son inferencias de recorrido completo, no verificaciones de accesos ni de todos los eventos de cobro. No se extiende una tarifa a otros arcos por mencionar la autopista.", "",
        "Para el baseline sin peajes, cargue `data/datasets/spain_tsp_2026/baseline_cost_v_25_eur.csv`. No interprete la diferencia con Modelo A como efecto tarifario exacto: este escenario combina ceros asumidos e importes proxy.", "",
        "## Supuestos de peaje", "",
        "Si ORS devuelve extras completos y no marca tramos tollways, se usa `ZERO_ASSUMED_ORS` (supuesto, no verificación oficial). Las rutas con pares tarifarios previamente inferidos conservan esos importes como inferencias. Los demás tramos positivos usan 0,14145 EUR por km tollways en la matriz base; sensibilidad: 0,070725 y 0,212175 EUR/km. El proxy no describe literalmente un sistema de tarifa por km ni es estadísticamente validado.", "",
        "## Modelo B y adquisición", "",
        "El piloto de 20 `avoid_tolls` dejó 20 rechazos de conexión sin código HTTP ni respuesta. Un intento posterior con permisos ampliados se interrumpió sin resumen, por lo que se desconoce cuántos intentos adicionales alcanzó a iniciar. No hay alternativas nuevas persistidas. Por ello el Modelo B numérico equivale al fastest-only y no debe describirse como comparación de rutas rápidas y libres. Revise diagnósticos y cuota antes de reintentar.", "",
        "## Cargar la matriz offline", "",
        "Las matrices de este paquete ya están generadas; cargarlas no necesita internet, snapshots privados ni ORS_API_KEY. Este ejemplo conserva el orden y construye una matriz lista para entregar a la función objetivo de GA/ACO:", "",
        "```python",
        "import csv",
        "from pathlib import Path",
        "root = Path('data/datasets/spain_tsp_economic_20261013')",
        "with (root / 'cities.csv').open(encoding='utf-8-sig', newline='') as f:",
        "    cities = [row['city_id'] for row in csv.DictReader(f)]",
        "with (root / 'model_a_v25_eur.csv').open(encoding='utf-8-sig', newline='') as f:",
        "    rows = list(csv.DictReader(f))",
        "assert [row['city_id'] for row in rows] == cities",
        "cost = [[float(row[city]) for city in cities] for row in rows]",
        "assert len(cost) == 47 and all(len(row) == 47 for row in cost)",
        "```", "",
        "## Atribución", "",
        "Resultados ORS: © openrouteservice by HeiGIT | Data from OpenStreetMap, bajo CC BY-SA 4.0 según términos de cuenta consultados. Datos OSM: © OpenStreetMap contributors, ODbL 1.0. El catálogo parcial de estaciones conserva solo entidades cartográficas y no acredita el paso de una ruta ni un pago. Revisar licencias y atribución antes de redistribuir este paquete.", "",
    ]
    (output_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")
    (output_dir / "LICENSE-DATA.md").write_text(
        "# Licencias y atribución de datos\n\n"
        "Este paquete reúne fuentes con condiciones distintas; no se declara una licencia única que sustituya las de origen.\n\n"
        "- Resultados y geometrías derivados de openrouteservice: © openrouteservice by HeiGIT | Data from OpenStreetMap; CC BY-SA 4.0 según los términos de cuenta consultados. Atribución y compartir bajo la licencia indicada.\n"
        "- Elementos cartográficos OSM de `osm_station_catalog_partial.csv`: © OpenStreetMap contributors, ODbL 1.0. Se distribuyen como archivo separado, con atribución; no se afirma que ODbL y CC BY-SA sean intercambiables.\n"
        "- Transcripciones de tarifas oficiales: importes, estaciones y vigencias conservan la fuente y cita en cada fila. Este archivo no concede derechos sobre la presentación gráfica de los documentos ni relicencia materiales de terceros.\n"
        "- Código del repositorio mantiene su licencia de código, separada de las licencias de datos.\n\n"
        "Revisar los términos vigentes de cada fuente antes de redistribuir el paquete en otros medios o combinar sus bases de datos.\n",
        encoding="utf-8",
    )
    hashes = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        hashes.append(f"{_sha256(path)}  {path.relative_to(output_dir).as_posix()}")
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--routes", type=Path, default=ROUTES_DEFAULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-output", type=Path, default=WORK_OUTPUT)
    args = parser.parse_args()
    metadata = build_bundle(dataset_dir=args.dataset, enriched_routes_path=args.routes,
                            output_dir=args.output, work_dir=args.work_output)
    print(json.dumps({k: metadata[k] for k in (
        "directed_arcs", "toll_status_counts", "numeric_model_a_arcs", "numeric_model_b_arcs",
        "valid_avoid_tolls_alternatives", "historical_unclassified_avoid_tolls_options",
        "avoid_tolls_queue_arcs", "avoid_tolls_pilot_known_connection_refused_attempts",
        "avoid_tolls_pilot_http_responses",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
