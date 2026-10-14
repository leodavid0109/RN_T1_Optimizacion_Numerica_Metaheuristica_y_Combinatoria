"""Empaqueta matrices base y rutas ORS enriquecidas, sin incluir respuestas crudas.

Uso offline::

    python -m experiments.export_tsp_spain_publication

El proceso exige que el catálogo del analizador cubra exactamente los 2.162
arcos, comprueba hashes y extras, y escribe shards JSONL gzip deterministas.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Sequence

from src.tsp.etl.dataset_export import load_published_dataset


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/datasets/spain_tsp_2026"
DEFAULT_RAW = ROOT / "data/raw/routes/enriched"
DEFAULT_ANALYSIS = ROOT / "data/processed/tolls/ors_extra_info/enriched_routes.json"
ATTRIBUTION = "© openrouteservice by HeiGIT | Data from OpenStreetMap"
EXTRA_INFO = ("tollways", "waycategory")


def baseline_cost_matrix(duration_hours, fuel_eur, value_hour_eur: float):
    """Construye únicamente la baseline v*T+F; los peajes quedan fuera."""
    import numpy as np

    value = float(value_hour_eur)
    duration = np.asarray(duration_hours, dtype=float)
    fuel = np.asarray(fuel_eur, dtype=float)
    if not math.isfinite(value) or value < 0 or duration.shape != fuel.shape:
        raise ValueError("valor horario o matrices incompatibles")
    if duration.ndim != 2 or duration.shape[0] != duration.shape[1]:
        raise ValueError("las matrices deben ser cuadradas")
    if not np.isfinite(duration).all() or not np.isfinite(fuel).all():
        raise ValueError("las matrices contienen valores no finitos")
    if (duration < 0).any() or (fuel < 0).any():
        raise ValueError("las matrices no pueden contener valores negativos")
    return value * duration + fuel


def validate_pair_universe(city_order: Sequence[str], pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Valida que haya exactamente un registro por cada arco dirigido no diagonal."""
    ids = tuple(city_order)
    if len(ids) != 47 or len(set(ids)) != 47:
        raise ValueError("el catálogo debe contener exactamente 47 IDs únicos")
    expected = [(origin, destination) for origin in ids for destination in ids if origin != destination]
    observed = list(pairs)
    if len(observed) != len(set(observed)):
        raise ValueError("hay pares dirigidos duplicados")
    if set(observed) != set(expected):
        missing = len(set(expected) - set(observed))
        extra = len(set(observed) - set(expected))
        raise ValueError(f"cobertura de arcos inválida: faltan {missing}, sobran {extra}")
    return expected


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _response_digest(response: dict[str, Any]) -> str:
    encoded = json.dumps(response, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _geometry_digest(coordinates: list[list[float]]) -> str:
    encoded = json.dumps(coordinates, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _extract_record(raw_path: Path, raw: dict[str, Any], analyzed: dict[str, Any]) -> dict[str, Any]:
    request_id = str(analyzed.get("request_id", ""))
    if not request_id or raw.get("request_id") != request_id:
        raise ValueError(f"identidad de solicitud inconsistente en {raw_path.name}")
    request = raw.get("request") or {}
    body = request.get("body") or {}
    acquisition = request.get("acquisition") or {}
    requested = set(body.get("extra_info") or acquisition.get("extra_info") or [])
    if not set(EXTRA_INFO).issubset(requested):
        raise ValueError(f"extras solicitados incompletos en {request_id}")
    if analyzed.get("coverage") != "complete_cartographic":
        raise ValueError(f"cobertura cartográfica incompleta en {request_id}")
    if analyzed.get("response_hash_verified") is not True:
        raise ValueError(f"hash de respuesta no verificado en {request_id}")
    if (analyzed.get("extra_info_status", {}).get("tollways") != "solicitado_y_presente"
            or analyzed.get("extra_info_status", {}).get("waycategory") != "solicitado_y_presente"):
        raise ValueError(f"estado de extras incompleto en {request_id}")

    response = raw.get("response") or {}
    features = response.get("features") or []
    feature_index = int(analyzed.get("feature_index", 0))
    if feature_index < 0 or feature_index >= len(features):
        raise ValueError(f"feature ausente en {request_id}")
    feature = features[feature_index]
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") != "LineString" or len(coordinates) < 2:
        raise ValueError(f"geometría inválida en {request_id}")
    for point in coordinates:
        if (not isinstance(point, (list, tuple)) or len(point) < 2
                or not all(math.isfinite(float(value)) for value in point[:2])
                or not -180 <= float(point[0]) <= 180 or not -90 <= float(point[1]) <= 90):
            raise ValueError(f"coordenada inválida en {request_id}")
    geometry_hash = _geometry_digest(coordinates)
    if geometry_hash != analyzed.get("geometry_sha256"):
        raise ValueError(f"hash de geometría inconsistente en {request_id}")

    response_hash = _response_digest(response)
    expected_prefix = raw_path.stem.rsplit("_", 1)[-1]
    recorded_hash = raw.get("response_sha256")
    if not response_hash.startswith(expected_prefix):
        raise ValueError(f"hash de respuesta no coincide con el nombre del snapshot {request_id}")
    if recorded_hash and not response_hash.startswith(str(recorded_hash)):
        raise ValueError(f"hash de respuesta inconsistente en {request_id}")
    raw_hash = _sha256_file(raw_path)
    if analyzed.get("raw_sha256") and analyzed["raw_sha256"] != raw_hash:
        raise ValueError(f"hash crudo inconsistente en {request_id}")

    extras = (feature.get("properties") or {}).get("extras") or {}
    if any(name not in extras or not isinstance(extras[name].get("values"), list) for name in EXTRA_INFO):
        raise ValueError(f"extras incompletos en {request_id}")
    summary = (feature.get("properties") or {}).get("summary") or {}
    distance_m = float(summary.get("distance", float(analyzed["distance_km"]) * 1000))
    duration_s = float(summary.get("duration", float(analyzed["duration_hours"]) * 3600))
    if not math.isfinite(distance_m) or distance_m <= 0 or not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError(f"distancia o duración inválida en {request_id}")

    origin_id = str(analyzed.get("origin_id", ""))
    destination_id = str(analyzed.get("destination_id", ""))
    if not origin_id or not destination_id or origin_id == destination_id:
        raise ValueError(f"par dirigido inválido en {request_id}")
    if acquisition.get("origin_id") and acquisition["origin_id"] != origin_id:
        raise ValueError(f"origen inconsistente en {request_id}")
    if acquisition.get("destination_id") and acquisition["destination_id"] != destination_id:
        raise ValueError(f"destino inconsistente en {request_id}")

    return {
        "schema_version": 1,
        "route_id": str(analyzed["route_id"]),
        "request_id": request_id,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "acquired_at": acquisition.get("acquired_at"),
        "source": {
            "provider": "openrouteservice by HeiGIT",
            "endpoint": request.get("url"),
            "profile": acquisition.get("profile", "driving-car"),
            "preference": body.get("preference", "fastest"),
            "extra_info": list(EXTRA_INFO),
            "routing_engine_version": (response.get("metadata") or {}).get("engine", {}).get("version"),
            "attribution": ATTRIBUTION,
        },
        "distance_m": distance_m,
        "duration_s": duration_s,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "geometry_sha256": geometry_hash,
        "response_sha256": response_hash,
        "raw_snapshot_sha256": raw_hash,
        "extras": {name: extras[name] for name in EXTRA_INFO},
        "provider_warnings": analyzed.get("provider_warnings") or [],
    }


def _write_gzip_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as binary:
            with gzip.GzipFile(filename="", mode="wb", fileobj=binary, compresslevel=9, mtime=0) as compressed:
                for record in records:
                    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    compressed.write(line.encode("utf-8"))
            binary.flush()
            os.fsync(binary.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def export_publication_bundle(
    dataset_dir: str | Path = DEFAULT_DATASET,
    raw_dir: str | Path = DEFAULT_RAW,
    analysis_path: str | Path = DEFAULT_ANALYSIS,
    *,
    shard_size: int = 200,
) -> dict[str, Any]:
    """Añade baselines y shards de geometrías verificadas al dataset publicado."""
    import numpy as np

    dataset_path, raw_root, analysis_file = Path(dataset_dir), Path(raw_dir), Path(analysis_path)
    if shard_size <= 0:
        raise ValueError("shard_size debe ser positivo")
    loaded = load_published_dataset(dataset_path)
    metadata_path = dataset_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    ids = tuple(loaded["city_order"])

    # Las matrices base son completamente reproducibles desde las matrices publicadas.
    base_files = {}
    for hour_value in (10, 25, 50):
        name = f"baseline_cost_v_{hour_value}_eur.csv"
        matrix = baseline_cost_matrix(loaded["duration_hours"], loaded["fuel_reference_eur"], hour_value)
        _write_matrix(dataset_path / name, ids, matrix)
        base_files[name] = _file_hash(dataset_path / name)

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    analyzed_routes = analysis.get("routes")
    if analysis.get("skipped_snapshots") or not isinstance(analyzed_routes, list):
        raise ValueError("el análisis offline tiene snapshots omitidos o formato inválido")
    if len(analyzed_routes) != 47 * 46:
        raise ValueError(f"se esperaban 2162 rutas analizadas; recibidas {len(analyzed_routes)}")
    by_request: dict[str, dict[str, Any]] = {}
    for route in analyzed_routes:
        request_id = str(route.get("request_id", ""))
        if not request_id or request_id in by_request:
            raise ValueError(f"request_id vacío o duplicado en análisis: {request_id}")
        by_request[request_id] = route
    raw_by_request: dict[str, Path] = {}
    for raw_path in sorted(raw_root.glob("*.json")):
        try:
            with raw_path.open(encoding="utf-8") as stream:
                raw = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"snapshot crudo ilegible: {raw_path.name}: {type(exc).__name__}") from exc
        request_id = str(raw.get("request_id", ""))
        if request_id in raw_by_request:
            raise ValueError(f"snapshot crudo duplicado para {request_id}")
        raw_by_request[request_id] = raw_path
    if set(raw_by_request) != set(by_request):
        raise ValueError(
            f"inventario crudo/análisis distinto: análisis={len(by_request)}, crudo={len(raw_by_request)}, "
            f"sin crudo={len(set(by_request)-set(raw_by_request))}, sin análisis={len(set(raw_by_request)-set(by_request))}"
        )

    records_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for request_id, analyzed in by_request.items():
        raw_path = raw_by_request[request_id]
        with raw_path.open(encoding="utf-8") as stream:
            raw = json.load(stream)
        record = _extract_record(raw_path, raw, analyzed)
        pair = (record["origin_id"], record["destination_id"])
        if pair in records_by_pair:
            raise ValueError(f"par dirigido duplicado en snapshots: {pair}")
        records_by_pair[pair] = record
    ordered_pairs = validate_pair_universe(ids, records_by_pair)
    ordered_records = [records_by_pair[pair] for pair in ordered_pairs]

    routes_dir = dataset_path / "routes" / "ors_enriched"
    routes_dir.mkdir(parents=True, exist_ok=True)
    shards = []
    for offset in range(0, len(ordered_records), shard_size):
        chunk = ordered_records[offset:offset + shard_size]
        shard_name = f"routes-{offset // shard_size + 1:04d}.jsonl.gz"
        shard_path = routes_dir / shard_name
        _write_gzip_jsonl(shard_path, chunk)
        shards.append({
            "path": f"routes/ors_enriched/{shard_name}",
            "records": len(chunk),
            "size_bytes": shard_path.stat().st_size,
            "sha256": _file_hash(shard_path),
        })
    route_manifest = {
        "schema_version": 1,
        "dataset_id": metadata.get("dataset_id"),
        "route_count": len(ordered_records),
        "directed_non_diagonal_arcs": len(ordered_pairs),
        "city_order": list(ids),
        "profile": "driving-car",
        "preference": "fastest",
        "extra_info": list(EXTRA_INFO),
        "units": {"distance_m": "m", "duration_s": "s", "geometry": "WGS84 longitude,latitude"},
        "encoding": "UTF-8 JSON Lines compressed with deterministic gzip (mtime=0), shards ordered by city catalog",
        "attribution": ATTRIBUTION,
        "results_license": "CC BY-SA 4.0",
        "osm_notice": "Contains routing outputs derived from OpenStreetMap data; see LICENSE-DATA.md for separate ODbL notice and scope.",
        "shard_size": shard_size,
        "shards": shards,
    }
    manifest_path = routes_dir / "manifest.json"
    _write_text_atomic(manifest_path, json.dumps(route_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    files_sha = dict(metadata.get("files_sha256", {}))
    files_sha.update(base_files)
    files_sha["routes/ors_enriched/manifest.json"] = _file_hash(manifest_path)
    for shard in shards:
        files_sha[shard["path"]] = shard["sha256"]
    metadata["files_sha256"] = dict(sorted(files_sha.items()))
    metadata["baseline_costs"] = {
        "scope": "BASELINE SIN COMPONENTE DE PEAJES",
        "formula": "value_hour_eur_per_hour * duration_hours + fuel_reference_eur",
        "hour_values_eur_per_hour": [10, 25, 50],
        "files": [f"baseline_cost_v_{v}_eur.csv" for v in (10, 25, 50)],
        "tolls_included": False,
    }
    metadata["enriched_route_bundle"] = {
        "route_count": len(ordered_records),
        "valid_directed_arcs": len(ordered_pairs),
        "extra_info": list(EXTRA_INFO),
        "osmId_available": False,
        "manifest": "routes/ors_enriched/manifest.json",
        "shards": len(shards),
        "source_raw_directory": "data/raw/routes/enriched (local; raw response JSON is not included)",
        "analysis_snapshot_count": len(analyzed_routes),
        "coverage": "complete_cartographic",
        "tolls_monetarily_verified": 0,
    }
    metadata["files_sha256"] = dict(sorted(metadata["files_sha256"].items()))
    _write_text_atomic(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    readme = (dataset_path / "README.md").read_text(encoding="utf-8")
    marker = "## Rutas ORS enriquecidas"
    if marker not in readme:
        readme += f"""

{marker}

Se distribuyen las 2.162 geometrías dirigidas `fastest` en `{route_manifest['encoding']}` dentro de `routes/ors_enriched/`. Cada registro incluye distancia y duración originales en m/s, geometría WGS84, `tollways`, `waycategory`, IDs estables, hashes y fecha de adquisición. `osmId` no fue devuelto por el servicio público en estas respuestas. La clasificación de segmentos es cartográfica, no una tarifa monetaria ni prueba de cobro.

`routes/ors_enriched/manifest.json` enumera filas, unidades, atribución y SHA-256 de cada shard. El empaquetado se puede reproducir offline con `python -m experiments.export_tsp_spain_publication` si se conservan los snapshots originales locales y el análisis generado por `python -m experiments.analyze_tsp_ors_extras`.

Las matrices `baseline_cost_v_10_eur.csv`, `baseline_cost_v_25_eur.csv` y `baseline_cost_v_50_eur.csv` calculan `v*T + combustible`. Son **BASELINE SIN COMPONENTE DE PEAJES**, no equivalen a rutas gratuitas ni a un costo económico total.
"""
        _write_text_atomic(dataset_path / "README.md", readme)
    license_path = dataset_path / "LICENSE-DATA.md"
    license_text = license_path.read_text(encoding="utf-8")
    if marker not in license_text:
        license_text += f"""

## Geometrías y resultados Directions publicados

Los shards de rutas y sus atributos `tollways`/`waycategory` son resultados de openrouteservice y se ofrecen conforme a la licencia de resultados CC BY-SA 4.0 indicada en los términos de HeiGIT consultados el 2026-10-12; atribución: **{ATTRIBUTION}**. Los atributos de ruta pueden derivar de la base cartográfica de OpenStreetMap. Se mantiene por separado la atribución y el aviso ODbL de [OpenStreetMap](https://www.openstreetmap.org/copyright); CC BY-SA y ODbL son licencias distintas. El conjunto no contiene el extracto vial original de OSM. Si la clasificación de una distribución como base derivada de OSM activara obligaciones adicionales, estas se rigen por ODbL y deben cumplirse independientemente; no se afirma que la licencia ORS las sustituya.

El empaquetado excluye instrucciones textuales innecesarias, encabezados de cuota, credenciales y los contenedores crudos. Mantiene geometría WGS84, segmentos extras, IDs y hashes necesarios para reproducir el análisis.
"""
        _write_text_atomic(license_path, license_text)

    checksum_names = [
        "cities.csv", "distance_km.csv", "duration_hours.csv", "fuel_reference_eur.csv",
        "fuel_low_eur.csv", "fuel_high_eur.csv", *base_files,
        "README.md", "LICENSE-DATA.md", "metadata.json", "routes/ors_enriched/manifest.json",
        *(shard["path"] for shard in shards),
    ]
    checksum_lines = [f"{_file_hash(dataset_path / name)}  {name}" for name in checksum_names]
    _write_text_atomic(dataset_path / "SHA256SUMS.txt", "\n".join(checksum_lines) + "\n")
    return route_manifest


def verify_publication_bundle(dataset_dir: str | Path = DEFAULT_DATASET) -> dict[str, Any]:
    """Valida hashes, gzip, geometrías, extras y cobertura 47×46 desde el paquete."""
    root = Path(dataset_dir)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    route_metadata = metadata.get("enriched_route_bundle") or {}
    manifest_rel = route_metadata.get("manifest")
    if not manifest_rel:
        raise ValueError("metadata no contiene manifest de geometrías")
    manifest_path = root / manifest_rel
    expected_manifest_hash = metadata.get("files_sha256", {}).get(manifest_rel)
    if not expected_manifest_hash or _file_hash(manifest_path) != expected_manifest_hash:
        raise ValueError("hash del manifiesto de geometrías ausente o inválido")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = tuple(metadata.get("city_order") or [])
    seen_pairs: list[tuple[str, str]] = []
    seen_request_ids: set[str] = set()
    count = 0
    bytes_total = manifest_path.stat().st_size
    for shard in manifest.get("shards", []):
        relative = shard.get("path", "")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"falta shard de geometrías: {relative}")
        digest = _file_hash(path)
        if digest != shard.get("sha256") or metadata.get("files_sha256", {}).get(relative) != digest:
            raise ValueError(f"hash inválido para shard {relative}")
        if path.stat().st_size != shard.get("size_bytes"):
            raise ValueError(f"tamaño inválido para shard {relative}")
        bytes_total += path.stat().st_size
        shard_count = 0
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    record = json.loads(line)
                    if record.get("schema_version") != 1:
                        raise ValueError(f"schema inválido en {relative}:{line_number}")
                    pair = (str(record.get("origin_id", "")), str(record.get("destination_id", "")))
                    if not all(pair) or pair[0] == pair[1]:
                        raise ValueError(f"par inválido en {relative}:{line_number}")
                    seen_pairs.append(pair)
                    request_id = str(record.get("request_id", ""))
                    if not request_id or request_id in seen_request_ids:
                        raise ValueError(f"request_id vacío o duplicado: {request_id}")
                    seen_request_ids.add(request_id)
                    geometry = record.get("geometry") or {}
                    coordinates = geometry.get("coordinates") or []
                    if geometry.get("type") != "LineString" or len(coordinates) < 2:
                        raise ValueError(f"geometría inválida en {request_id}")
                    if _geometry_digest(coordinates) != record.get("geometry_sha256"):
                        raise ValueError(f"hash geométrico inválido en {request_id}")
                    extras = record.get("extras") or {}
                    if any(name not in extras or not isinstance(extras[name].get("values"), list) for name in EXTRA_INFO):
                        raise ValueError(f"extras ausentes en {request_id}")
                    for name in EXTRA_INFO:
                        for interval in extras[name]["values"]:
                            if (not isinstance(interval, list) or len(interval) != 3
                                    or not all(isinstance(v, int) for v in interval)
                                    or interval[0] < 0 or interval[1] < interval[0]
                                    or interval[1] >= len(coordinates)):
                                raise ValueError(f"intervalo {name} inválido en {request_id}")
                    shard_count += 1
                    count += 1
        except (OSError, EOFError, json.JSONDecodeError) as exc:
            raise ValueError(f"shard corrupto {relative}: {type(exc).__name__}") from exc
        if shard_count != shard.get("records"):
            raise ValueError(f"conteo de registros inválido en {relative}")
    validate_pair_universe(ids, seen_pairs)
    if count != manifest.get("route_count") or count != route_metadata.get("route_count"):
        raise ValueError("conteo de geometrías no concilia con manifiestos")
    return {
        "routes": count,
        "directed_arcs": len(seen_pairs),
        "shards": len(manifest.get("shards", [])),
        "bundle_bytes": bytes_total,
        "extra_info": list(EXTRA_INFO),
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_matrix(path: Path, ids: Sequence[str], matrix) -> None:
    import numpy as np

    values = np.asarray(matrix, dtype=float)
    if values.shape != (len(ids), len(ids)) or not np.isfinite(values).all():
        raise ValueError(f"matriz inválida: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["city_id", *ids])
            writer.writerows([[city_id, *(format(float(v), ".17g") for v in row)] for city_id, row in zip(ids, values)])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--shard-size", type=int, default=200)
    parser.add_argument("--verify-only", action="store_true", help="valida el paquete local sin reexportar")
    args = parser.parse_args(argv)
    if args.verify_only:
        result = verify_publication_bundle(args.dataset_dir)
    else:
        manifest = export_publication_bundle(args.dataset_dir, args.raw_dir, args.analysis, shard_size=args.shard_size)
        result = {
            "route_count": manifest["route_count"],
            "shards": len(manifest["shards"]),
            "total_bytes": sum(shard["size_bytes"] for shard in manifest["shards"]),
            "manifest": str(args.dataset_dir / "routes/ors_enriched/manifest.json"),
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
