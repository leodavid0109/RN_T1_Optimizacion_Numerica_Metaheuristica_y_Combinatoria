"""Verifica y reproduce offline las dos partes del Trabajo 1.

La ejecución completa escribe en directorios nuevos bajo results/reproducible
y figures/reproducible; nunca sobreescribe las salidas originales.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from experiments.export_tsp_spain_publication import verify_publication_bundle
from src.tsp.etl.dataset_export import load_published_dataset

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/datasets/spain_tsp_2026"
ECON = ROOT / "data/datasets/spain_tsp_economic_20261013"
HOURS = (10, 25, 50)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(directory: Path) -> int:
    manifest = directory / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise ValueError(f"falta el manifiesto: {manifest}")
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        path = directory / relative.lstrip("* ")
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"archivo ausente o hash incorrecto: {path}")
        count += 1
    return count


def read_matrix(path: Path, order: tuple[str, ...]) -> list[list[float]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if [row.get("city_id") for row in rows] != list(order):
        raise ValueError(f"orden de ciudades inválido: {path}")
    matrix = [[float(row[city]) for city in order] for row in rows]
    if len(matrix) != len(order) or any(len(row) != len(order) for row in matrix):
        raise ValueError(f"dimensiones inválidas: {path}")
    if any(not math.isfinite(x) or x < 0 for row in matrix for x in row):
        raise ValueError(f"valor no finito o negativo: {path}")
    if any(matrix[i][i] != 0 for i in range(len(order))):
        raise ValueError(f"diagonal distinta de cero: {path}")
    return matrix


def reconstruct_economics(dataset: dict, output: Path | None = None) -> dict:
    order = tuple(dataset["city_order"])
    with (ECON / "toll_components.csv").open(encoding="utf-8-sig", newline="") as stream:
        components = list(csv.DictReader(stream))
    expected = {(a, b) for a in order for b in order if a != b}
    pairs = {(r["origin_id"], r["destination_id"]) for r in components}
    if len(components) != 2162 or pairs != expected:
        raise ValueError("toll_components.csv no cubre exactamente los 2.162 arcos")
    index = {city: i for i, city in enumerate(order)}
    matrices = {}
    for hour in HOURS:
        matrix = [[0.0] * len(order) for _ in order]
        field_a, field_b = f"model_a_cost_v{hour}_eur", f"model_b_cost_v{hour}_eur"
        for row in components:
            i, j = index[row["origin_id"]], index[row["destination_id"]]
            value = hour * float(row["duration_hours"]) + float(row["fuel_eur"]) + float(row["toll_eur_base"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("componente económico inválido")
            if not math.isclose(value, float(row[field_a]), rel_tol=1e-11, abs_tol=1e-9):
                raise ValueError(f"componentes no reconcilian para v={hour}: {row['origin_id']}->{row['destination_id']}")
            if not math.isclose(value, float(row[field_b]), rel_tol=1e-11, abs_tol=1e-9):
                raise ValueError("Modelo B no concilia con fastest-only")
            matrix[i][j] = value
        for name in (f"model_a_v{hour}_eur.csv", f"model_b_v{hour}_eur.csv"):
            published = read_matrix(ECON / name, order)
            if any(not math.isclose(matrix[i][j], published[i][j], rel_tol=1e-11, abs_tol=1e-9)
                   for i in range(len(order)) for j in range(len(order))):
                raise ValueError(f"componentes no reconstruyen {name}")
        matrices[hour] = matrix
        if output is not None:
            output.mkdir(parents=True, exist_ok=True)
            with (output / f"model_a_v{hour}_eur.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["city_id", *order])
                for city, values in zip(order, matrix):
                    writer.writerow([city, *[format(x, ".15g") for x in values]])
    metadata = json.loads((ECON / "metadata.json").read_text(encoding="utf-8"))
    return {
        "arcs": len(components),
        "reconstructed_matrices": 3 if output is not None else 0,
        "numeric_arcs_per_matrix": 2162,
        "toll_status_counts": metadata["toll_status_counts"],
        "valid_avoid_tolls_alternatives": metadata.get("valid_avoid_tolls_alternatives", 0),
        "model_b": "FASTEST_ONLY; no representa alternativas libres",
    }


def verify_all() -> dict:
    bundle = verify_publication_bundle(BASE)
    dataset = load_published_dataset(BASE)
    economic_hashes = verify_manifest(ECON)
    economics = reconstruct_economics(dataset)
    if len(dataset["city_order"]) != 47 or bundle["directed_arcs"] != 2162:
        raise ValueError("el dataset no concilia con 47 ciudades y 2.162 arcos")
    ga = any((ROOT / name).is_file() for name in (
        "src/tsp/ga.py", "src/tsp/genetic_algorithm.py", "src/genetic_algorithm.py"
    ))
    return {"python": platform.python_version(), "base_dataset": bundle,
            "economic_hashes_checked": economic_hashes, "economic_model": economics,
            "ga_implementation_available": ga, "external_api_required": False}


def run_step(name: str, command: list[str], expected: list[Path]) -> dict:
    started = time.perf_counter()
    print(f"\n[{name}] {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    record = {"name": name, "command": command, "returncode": result.returncode,
              "elapsed_seconds": round(time.perf_counter() - started, 3),
              "outputs": [str(p.relative_to(ROOT)) for p in expected]}
    if result.returncode:
        raise RuntimeError(f"{name}: terminó con código {result.returncode}")
    missing = [str(p) for p in expected if not p.is_file()]
    if missing:
        raise RuntimeError(f"{name}: faltan salidas esperadas {missing}")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="presupuesto reducido; no son resultados finales")
    mode.add_argument("--verify-only", action="store_true", help="integridad y reconstrucción, sin optimizar")
    parser.add_argument("--part", choices=("1", "2", "all"), default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("results/reproducible"),
                        help="directorio base nuevo para resultados")
    args = parser.parse_args(argv)
    try:
        verified = verify_all()
        print("VERIFICACIÓN:", json.dumps(verified, ensure_ascii=False, indent=2))
        if args.verify_only:
            return 0
        label = "quick" if args.quick else "full"
        result_root = (ROOT / args.output_dir / label).resolve()
        figure_root = (ROOT / "figures/reproducible" / args.output_dir.name / label).resolve()
        if result_root.exists() or figure_root.exists():
            raise FileExistsError(f"las salidas ya existen; use otro --output-dir: {result_root}")
        result_root.mkdir(parents=True)
        figure_root.mkdir(parents=True)
        started = datetime.now(timezone.utc).isoformat()
        records: list[dict] = []

        def call(name: str, module: str, *params: str, outputs: list[Path]) -> None:
            records.append(run_step(name, [sys.executable, "-m", module, *params], outputs))

        if args.part in ("1", "all"):
            gd_r, gd_f = result_root / "part1/gd", figure_root / "part1/gd"
            cmp_r, cmp_f = result_root / "part1/compare", figure_root / "part1/compare"
            anim_f = figure_root / "part1/animations"
            gd_out = [gd_r / "runs.csv", gd_r / "summary.csv", gd_f / "gd_convergencia.png",
                      gd_f / "gd_rosenbrock.gif", gd_f / "gd_rastrigin.gif"]
            cmp_out = [cmp_r / "runs.csv", cmp_r / "summary.csv",
                       cmp_f / "compare_convergencia.png", cmp_f / "compare_cajas.png"]
            anim_out = [anim_f / f"anim_{m}_{f}.gif" for m in ("gd", "ea", "pso", "de")
                        for f in ("rosenbrock", "rastrigin")]
            if args.quick:
                call("GD demo", "experiments.gd_experiment", "--config", "configs/gd_demo.yaml",
                     "--results", str(gd_r), "--figures", str(gd_f), "--set", "n_runs=2", outputs=gd_out)
                call("Comparación demo", "experiments.compare", "--config", "configs/compare_demo.yaml",
                     "--results", str(cmp_r), "--figures", str(cmp_f), "--set", "n_runs=2", outputs=cmp_out)
                call("Estadística demo", "experiments.stats_compare", "--resultados", str(cmp_r),
                     outputs=[cmp_r / "pruebas.csv", cmp_r / "ic_exito.csv"])
                call("Animaciones demo", "experiments.animate", "--config", "configs/anim.yaml",
                     "--figures", str(anim_f), "--set", "presupuesto=250", "--set", "max_cuadros=12",
                     outputs=anim_out)
            else:
                call("GD completo", "experiments.gd_experiment", "--config", "configs/gd.yaml",
                     "--results", str(gd_r), "--figures", str(gd_f), outputs=gd_out)
                call("Comparación completa", "experiments.compare", "--config", "configs/compare.yaml",
                     "--results", str(cmp_r), "--figures", str(cmp_f), outputs=cmp_out)
                call("Estadística completa", "experiments.stats_compare", "--resultados", str(cmp_r),
                     outputs=[cmp_r / "pruebas.csv", cmp_r / "ic_exito.csv"])
                tuning = result_root / "part1/tuning"
                call("Barrido y validación", "experiments.tune_all", "--output", str(tuning),
                     outputs=[tuning / n for n in ("sweep_runs.csv", "sweep_summary.csv",
                                                    "validation_runs.csv", "validation_summary.csv")])
                call("Animaciones finales", "experiments.animate", "--config", "configs/anim.yaml",
                     "--figures", str(anim_f), outputs=anim_out)

        reconstruction = None
        if args.part in ("2", "all"):
            econ_out = result_root / "part2/economic_reconstruction"
            reconstruction = reconstruct_economics(load_published_dataset(BASE), econ_out)
            baseline = result_root / "part2/baseline_aco_30_runs.json"
            model_a = result_root / "part2/model_a_aco_30_runs.json"
            budget = "10" if args.quick else "100"
            call("ACO baseline sin peajes", "experiments.run_tsp_baseline_repetitions",
                 "--budget", budget, "--output", str(baseline), outputs=[baseline])
            call("ACO Modelo A", "experiments.run_tsp_economic_aco",
                 "--budget", budget, "--output", str(model_a), outputs=[model_a])
            visual = result_root / "part2/visual"
            call("ACO y líneas base visuales", "experiments.run_tsp_model_a_visual",
                 "--budget", budget, "--output-dir", str(visual),
                 outputs=[visual / "model_a_v25_aco_baselines.json",
                          visual / "model_a_v25_aco_convergence.csv",
                          visual / "model_a_v25_aco_nn_2opt_comparison.gif"])
            trips = figure_root / "part2/trips"
            call("GIFs de recorridos TSP", "experiments.animate_tsp_model_a_trips",
                 "--results", str(visual / "model_a_v25_aco_baselines.json"),
                 "--output-dir", str(trips),
                 *( ["--frames", "12"] if args.quick else [] ),
                 outputs=[trips / n for n in ("model_a_v25_trip_aco.gif",
                          "model_a_v25_trip_nearest_neighbor.gif",
                          "model_a_v25_trip_nearest_neighbor_2opt.gif")])
            if not args.quick:
                report = result_root / "part2/Informe_Trabajo1.docx"
                call("Informe reproducido", "informe.build_informe_trabajo1",
                     "--results", str(model_a), "--output", str(report),
                     "--figure-dir", str(figure_root / "part2/report"), outputs=[report])

        summary = {"mode": label, "parts": args.part, "started_at_utc": started,
                   "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                   "verification": verified, "economic_reconstruction": reconstruction,
                   "steps": records, "ga": "no disponible; no se generan resultados GA",
                   "external_api_requests": 0}
        path = result_root / "reproduction_summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nREPRODUCCIÓN COMPLETADA: {path.relative_to(ROOT)}", flush=True)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
