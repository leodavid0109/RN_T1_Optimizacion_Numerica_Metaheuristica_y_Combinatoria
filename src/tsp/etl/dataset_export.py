"""Exportación determinista y carga offline del dataset nacional de matrices.

Las matrices derivadas de ORS se pueden preparar localmente. La publicación
requiere resolver por separado los términos de ORS y las obligaciones ODbL.
"""

from __future__ import annotations

import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from ..cities import City, load_city_catalog
from ..matrices import validate_matrix
from .economics import load_fuel_economics
from .ors import parse_ors_matrix


REPO_ROOT = Path(__file__).resolve().parents[3]

DATASET_FILES = (
    "cities.csv", "distance_km.csv", "duration_hours.csv",
    "fuel_reference_eur.csv", "fuel_low_eur.csv", "fuel_high_eur.csv",
)


def export_spain_dataset(
    raw_snapshot_path: str | Path,
    catalog_path: str | Path,
    economics_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Prepara los archivos del dataset desde un snapshot ORS validado, sin red.

    Los archivos se escriben determinísticamente. No se copia la respuesta cruda.
    ``metadata.json`` conserva el hash de la respuesta y del contenedor local.
    """
    raw_path, out = Path(raw_snapshot_path), Path(output_dir)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    cities = load_city_catalog(catalog_path)
    ids = [city.city_id for city in cities]
    if len(cities) != 47:
        raise ValueError(f"se requieren 47 ciudades; recibidas {len(cities)}")
    if payload.get("city_order") != ids:
        raise ValueError("el orden del snapshot no coincide con el catálogo canónico")
    request = payload.get("request", {})
    body = request.get("body", {})
    if body.get("units") != "m" or set(body.get("metrics", ())) != {"distance", "duration"}:
        raise ValueError("el snapshot no declara Matrix en metros y segundos")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("falta la respuesta Matrix en el snapshot")
    response_sha = sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if response_sha != payload.get("response_sha256"):
        raise ValueError("el hash de la respuesta no coincide con el snapshot")
    parsed = parse_ors_matrix(response, len(cities))
    distance = validate_matrix(parsed["distance_km"], len(cities), "distancias")
    duration = validate_matrix(parsed["time_hours"], len(cities), "duraciones")
    _validate_national_matrix(distance, ids, "distancias")
    _validate_national_matrix(duration, ids, "duraciones")
    if not np.any(distance != distance.T) or not np.any(duration != duration.T):
        raise ValueError("se esperaba conservar la asimetría dirigida observada")

    economics = load_fuel_economics(economics_path)
    if economics.price_eur_per_liter is None:
        raise ValueError("el precio de combustible está pendiente")
    fuels = {
        scenario: distance / 100.0 * economics.consumption(scenario) * economics.price_eur_per_liter
        for scenario in ("reference", "low", "high")
    }
    _validate_fuel(fuels, distance, economics.consumption("low"),
                   economics.consumption("reference"), economics.consumption("high"),
                   economics.price_eur_per_liter)

    out.mkdir(parents=True, exist_ok=True)
    _write_cities(out / "cities.csv", cities)
    _write_matrix(out / "distance_km.csv", ids, distance)
    _write_matrix(out / "duration_hours.csv", ids, duration)
    for scenario, matrix in fuels.items():
        suffix = "reference" if scenario == "reference" else scenario
        _write_matrix(out / f"fuel_{suffix}_eur.csv", ids, matrix)
    _write_text(out / "README.md", _readme())
    _write_text(out / "LICENSE-DATA.md", _license_notice())

    output_hashes = {name: _file_sha256(out / name) for name in DATASET_FILES}
    metadata = {
        "schema_version": 1,
        "dataset_id": "spain_tsp_2026",
        "city_count": len(cities),
        "matrix_dimensions": [len(cities), len(cities)],
        "directed_non_diagonal_arcs": len(cities) * (len(cities) - 1),
        "city_order": ids,
        "units": {"distance_km": "km", "duration_hours": "h", "fuel_cost": "EUR"},
        "routing": {
            "provider": "openrouteservice",
            "profile": request.get("url", "").rstrip("/").split("/")[-1],
            "endpoint": request.get("url"),
            "preference": request.get("routing_preference", "provider_default"),
            "acquired_at": payload.get("acquired_at"),
            "provider_timestamp": response.get("metadata", {}).get("timestamp"),
            "map_graph_version": None,
        },
        "provenance": {
            "raw_snapshot_file": _provenance_path(raw_path),
            "raw_snapshot_sha256": _file_sha256(raw_path),
            "response_sha256": response_sha,
            "city_catalog_file": _provenance_path(Path(catalog_path)),
            "fuel_configuration_file": _provenance_path(Path(economics_path)),
            "fuel_price_eur_l": economics.price_eur_per_liter,
            "fuel_price_source": economics.price_source,
            "fuel_price_publication_date": economics.price_reference_date,
            "fuel_price_consulted_on": economics.price_consulted_on,
            "fuel_price_acquired_on": economics.price_acquired_on,
            "fuel_price_source_file_sha256": economics.price_source_sha256,
            "study_reference_date": economics.study_reference_date,
            "vehicle_id": economics.vehicle_id,
            "fuel_grade": economics.fuel_grade,
            "consumption_l_per_100km": {
                scenario: economics.consumption(scenario)
                for scenario in ("reference", "low", "high")
            },
            "fuel_cost_formula": "distance_km / 100 * consumption_l_per_100km * fuel_price_eur_l",
            "openrouteservice_attribution": response.get("metadata", {}).get("attribution"),
            "openstreetmap_attribution": "Data © OpenStreetMap contributors; ODbL",
        },
        "redistribution": {
            "status": "pending_license_review",
            "reason": "Public ORS terms page redirects to account-authenticated terms; public HeiGIT forum answers conflict on CC BY 4.0 vs CC BY-SA 4.0. ODbL treatment of this derived matrix also needs confirmation.",
        },
        "tolls_included": False,
        "complete_economic_cost_matrix_exists": False,
        "files_sha256": output_hashes,
    }
    _write_text(out / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    checksum_lines = [f"{_file_sha256(out / name)}  {name}" for name in (*DATASET_FILES, "README.md", "LICENSE-DATA.md", "metadata.json")]
    _write_text(out / "SHA256SUMS.txt", "\n".join(checksum_lines) + "\n")
    return metadata


def load_published_dataset(dataset_dir: str | Path) -> dict[str, Any]:
    """Carga las matrices publicadas/preparadas y valida hashes y orden offline.

    Devuelve matrices de distancia, duración y combustible; nunca inventa peajes
    ni crea un costo económico total.
    """
    directory = Path(dataset_dir)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("city_count") != 47 or metadata.get("matrix_dimensions") != [47, 47]:
        raise ValueError("metadata no declara las dimensiones nacionales esperadas")
    ids = tuple(metadata.get("city_order", ()))
    if len(ids) != 47 or len(set(ids)) != 47:
        raise ValueError("orden canónico ausente o inválido")
    city_path = directory / "cities.csv"
    city_hash = metadata.get("files_sha256", {}).get("cities.csv")
    if not city_hash or _file_sha256(city_path) != city_hash:
        raise ValueError("hash ausente o inválido para cities.csv")
    with city_path.open(encoding="utf-8", newline="") as stream:
        city_rows = list(csv.DictReader(stream))
    if tuple(row.get("city_id", "") for row in city_rows) != ids:
        raise ValueError("el catálogo de ciudades no coincide con el orden de metadata")
    expected_files = {
        "distance_km": "distance_km.csv", "duration_hours": "duration_hours.csv",
        "fuel_reference_eur": "fuel_reference_eur.csv", "fuel_low_eur": "fuel_low_eur.csv",
        "fuel_high_eur": "fuel_high_eur.csv",
    }
    matrices = {}
    for key, filename in expected_files.items():
        path = directory / filename
        expected_hash = metadata.get("files_sha256", {}).get(filename)
        if not expected_hash or _file_sha256(path) != expected_hash:
            raise ValueError(f"hash ausente o inválido para {filename}")
        matrices[key] = _read_matrix(path, ids)
        _validate_national_matrix(matrices[key], list(ids), filename)
    provenance = metadata.get("provenance", {})
    price = float(provenance.get("fuel_price_eur_l", 0))
    consumptions = provenance.get("consumption_l_per_100km", {})
    for scenario in ("low", "reference", "high"):
        expected = matrices["distance_km"] / 100.0 * float(consumptions[scenario]) * price
        if not np.allclose(matrices[f"fuel_{scenario}_eur"], expected, rtol=1e-14, atol=1e-15):
            raise ValueError(f"fuel_{scenario}_eur.csv no concilia con distance y la configuración económica")
    if metadata.get("tolls_included") is not False or metadata.get("complete_economic_cost_matrix_exists") is not False:
        raise ValueError("dataset no declara explícitamente exclusión de peajes/costo total")
    return {"city_order": ids, **matrices, "metadata": metadata}


def _validate_national_matrix(matrix: np.ndarray, ids: list[str], label: str) -> None:
    n = len(ids)
    if matrix.shape != (n, n) or n != 47:
        raise ValueError(f"{label}: dimensión incompatible")
    if not np.isfinite(matrix).all() or (matrix < 0).any():
        raise ValueError(f"{label}: valores no finitos o negativos")
    if not np.all(np.diag(matrix) == 0):
        raise ValueError(f"{label}: diagonal distinta de cero")
    if (matrix[np.eye(n, dtype=bool) == 0] <= 0).any():
        raise ValueError(f"{label}: arco dirigido no diagonal ausente o no positivo")


def _validate_fuel(
    fuels: dict[str, np.ndarray], distance: np.ndarray,
    low_consumption: float, reference_consumption: float,
    high_consumption: float, price: float,
) -> None:
    for scenario, matrix in fuels.items():
        if matrix.shape != distance.shape or not np.isfinite(matrix).all() or (matrix < 0).any():
            raise ValueError(f"combustible {scenario}: matriz inválida")
        if not np.allclose(np.diag(matrix), 0.0, atol=0.0):
            raise ValueError(f"combustible {scenario}: diagonal distinta de cero")
    off_diagonal = ~np.eye(distance.shape[0], dtype=bool)
    if not np.all(fuels["low"][off_diagonal] < fuels["reference"][off_diagonal]):
        raise ValueError("escenario low no resulta menor que reference")
    if not np.all(fuels["reference"][off_diagonal] < fuels["high"][off_diagonal]):
        raise ValueError("escenario reference no resulta menor que high")
    for scenario, consumption in (("low", low_consumption), ("reference", reference_consumption),
                                  ("high", high_consumption)):
        expected = distance / 100.0 * consumption * price
        if not np.allclose(fuels[scenario], expected, rtol=1e-14, atol=1e-15):
            raise ValueError(f"escenario {scenario} no concilia con la fórmula de combustible")


def _write_cities(path: Path, cities: tuple[City, ...]) -> None:
    columns = list(City.__dataclass_fields__)
    _write_csv(path, columns, [
        [getattr(city, column) if getattr(city, column) is not None else "" for column in columns]
        for city in cities
    ])


def _write_matrix(path: Path, ids: list[str], matrix: np.ndarray) -> None:
    _write_csv(path, ["city_id", *ids], [
        [city_id, *(f"{float(value):.17g}" for value in row)]
        for city_id, row in zip(ids, matrix)
    ])


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_matrix(path: Path, ids: tuple[str, ...]) -> np.ndarray:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows or rows[0] != ["city_id", *ids] or len(rows) != len(ids) + 1:
        raise ValueError(f"matriz {path.name} no conserva el orden canónico")
    values = []
    for city_id, row in zip(ids, rows[1:]):
        if len(row) != len(ids) + 1 or row[0] != city_id:
            raise ValueError(f"fila inválida en {path.name}")
        values.append([float(value) for value in row[1:]])
    return validate_matrix(values, len(ids), path.name)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _provenance_path(path: Path) -> str:
    """Evita incluir rutas locales absolutas y hace metadata portable."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _readme() -> str:
    return """# Instancia vial nacional TSP — España peninsular (2026)

Preparación local a partir de un snapshot ORS Matrix. Incluye distancias dirigidas, duraciones y tres escenarios de combustible. No incluye tarifas de peaje ni matriz de costo económico total.

## Estado de distribución

Este paquete es una vista local de preparación. No redistribuir hasta resolver la revisión de términos ORS (CC BY 4.0 frente a CC BY-SA 4.0) y el alcance ODbL. Consultar `LICENSE-DATA.md`.

## Archivos y unidades

`cities.csv` conserva el orden canónico y procedencia IGN; `distance_km.csv` está en km; `duration_hours.csv` en horas; las tres matrices `fuel_*_eur.csv` están en EUR. Las matrices son dirigidas: fila = origen, columna = destino; la diagonal es cero. CSV tiene etiquetas de fila y columna, así que contiene 48×48 campos con 47×47 valores numéricos.

## Uso offline

Desde la raíz del repositorio: `python -c "from src.tsp.etl.dataset_export import load_published_dataset; d=load_published_dataset('data/datasets/spain_tsp_2026'); print(d['city_order'][:3], d['distance_km'].shape)"`. La carga valida hashes y orden. No construye costos totales porque los peajes siguen sin estar completos.

## Atribución

Rutas: © openrouteservice by HeiGIT. Datos cartográficos: © OpenStreetMap contributors, ODbL. Coordenadas de ciudades: IGN, CC BY 4.0, según procedencia del catálogo. Ver `metadata.json`.
"""


def _license_notice() -> str:
    return """# Estado de licencia de datos — no redistribuir todavía

Este archivo no concede licencia de redistribución. Los términos públicos de ORS enlazan a condiciones de cuenta que requieren autenticación; una respuesta pública del foro de HeiGIT de 2026-10-12 afirma CC BY-SA 4.0, mientras que otra documentación pública indexada refiere CC BY 4.0. La respuesta de soporte remite a los términos y declara que HeiGIT no da asesoría legal sobre el alcance. Además, la matriz resulta de rutas basadas en OSM y el tratamiento como base derivada bajo ODbL debe resolverse.

Hasta conservar y revisar los términos exactos aceptados por esta cuenta y confirmar el tratamiento ODbL de las matrices derivadas, los CSV solo pueden mantenerse en el área local del equipo. No publicar este directorio.

Fuentes consultadas el 2026-10-12:

- ORS Terms of Service: https://openrouteservice.org/terms-of-service/ (redirige a términos de cuenta autenticados).
- Respuesta del foro ORS/HeiGIT sobre resultados y CC BY-SA 4.0: https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079
- Respuesta del foro ORS/HeiGIT sobre persistencia de resultados Matrix: https://ask.openrouteservice.org/t/persistent-storage-and-reuse-of-matrix-api-duration-results/8010
- OSMF Attribution Guidelines: https://osmfoundation.org/wiki/Attribution_Guidelines
- OSM Copyright and License: https://www.openstreetmap.org/copyright
"""
