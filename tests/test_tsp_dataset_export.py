"""Pruebas sintéticas del exportador offline; no son datos de España."""

from hashlib import sha256
import json

import numpy as np
import pytest

from src.tsp.cities import CATALOG_PATH, load_city_catalog
from src.tsp.etl.dataset_export import export_spain_dataset, load_published_dataset


def _synthetic_snapshot(path):
    n = 47
    distances = [[0 if i == j else 1000 + i * n + j for j in range(n)] for i in range(n)]
    durations = [[0 if i == j else 3600 + i * 10 + j for j in range(n)] for i in range(n)]
    response = {"distances": distances, "durations": durations,
                "metadata": {"timestamp": 1_792_000_000_000, "attribution": "synthetic test fixture"}}
    cities = [city.city_id for city in load_city_catalog()]
    payload = {
        "schema_version": 1, "request_id": "synthetic-matrix-test", "provider": "synthetic-test",
        "request": {"url": "https://fixture.invalid/matrix/driving-car",
                    "body": {"metrics": ["distance", "duration"], "units": "m"}},
        "response": response, "city_order": cities, "acquired_at": "2026-10-12T00:00:00+00:00",
        "response_sha256": sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_export_is_deterministic_complete_and_loads_offline(tmp_path):
    snapshot = _synthetic_snapshot(tmp_path / "snapshot.json")
    first = tmp_path / "first"
    second = tmp_path / "second"
    metadata_a = export_spain_dataset(snapshot, CATALOG_PATH, "configs/tsp_economics.yaml", first)
    metadata_b = export_spain_dataset(snapshot, CATALOG_PATH, "configs/tsp_economics.yaml", second)
    assert metadata_a == metadata_b
    assert metadata_a["city_count"] == 47
    assert metadata_a["directed_non_diagonal_arcs"] == 2162
    assert set(metadata_a["files_sha256"]) == {
        "cities.csv", "distance_km.csv", "duration_hours.csv", "fuel_reference_eur.csv",
        "fuel_low_eur.csv", "fuel_high_eur.csv",
    }
    for filename in (*metadata_a["files_sha256"], "README.md", "LICENSE-DATA.md", "metadata.json", "SHA256SUMS.txt"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    loaded = load_published_dataset(first)
    assert loaded["distance_km"].shape == (47, 47)
    assert loaded["duration_hours"].shape == (47, 47)
    assert np.count_nonzero(loaded["distance_km"] != loaded["distance_km"].T) > 0
    assert np.allclose(loaded["fuel_reference_eur"], loaded["distance_km"] / 100 * 5.4 * 1.849098398)
    assert loaded["metadata"]["tolls_included"] is False
    assert "economic_cost" not in loaded


def test_export_rejects_snapshot_hash_mismatch(tmp_path):
    snapshot = _synthetic_snapshot(tmp_path / "snapshot.json")
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["response"]["distances"][0][1] += 1
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash de la respuesta"):
        export_spain_dataset(snapshot, CATALOG_PATH, "configs/tsp_economics.yaml", tmp_path / "out")


def test_offline_loader_rejects_changed_export_file(tmp_path):
    snapshot = _synthetic_snapshot(tmp_path / "snapshot.json")
    output = tmp_path / "dataset"
    export_spain_dataset(snapshot, CATALOG_PATH, "configs/tsp_economics.yaml", output)
    with (output / "distance_km.csv").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="hash ausente o inválido"):
        load_published_dataset(output)
