"""Create one traveler-style GIF per ACO/nearest-neighbor method, offline."""

from __future__ import annotations

import argparse
import bisect
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import numpy as np

from experiments.run_tsp_model_a_visual import (
    DEFAULT_BUNDLE,
    DEFAULT_DATASET,
    DEFAULT_OUTPUT,
    _load_route_geometries,
)
from experiments.run_tsp_economic_aco import load_model_a_problem


EARTH_RADIUS_KM = 6371.0088
METHOD_FILES = {
    "Ant System (ACO)": "model_a_v25_trip_aco.gif",
    "Vecino más cercano": "model_a_v25_trip_nearest_neighbor.gif",
    "Vecino más cercano + 2-opt": "model_a_v25_trip_nearest_neighbor_2opt.gif",
}
METHOD_COLORS = {
    "Ant System (ACO)": "#c23b5a",
    "Vecino más cercano": "#2878b5",
    "Vecino más cercano + 2-opt": "#27966f",
}


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(hav)))


def _normalize_cycle(city_ids: list[str], start_id: str) -> list[str]:
    if len(city_ids) != 47 or len(set(city_ids)) != 47:
        raise ValueError("cada resultado debe contener las 47 ciudades una sola vez")
    if start_id not in city_ids:
        raise ValueError(f"el tour no contiene la ciudad de salida {start_id}")
    index = city_ids.index(start_id)
    return city_ids[index:] + city_ids[:index]


def _interpolate_path(path, cumulative, distance):
    if distance <= 0:
        return path[0]
    if distance >= cumulative[-1]:
        return path[-1]
    index = bisect.bisect_right(cumulative, distance) - 1
    segment_length = cumulative[index + 1] - cumulative[index]
    fraction = (distance - cumulative[index]) / segment_length if segment_length else 0.0
    return (
        path[index][0] + fraction * (path[index + 1][0] - path[index][0]),
        path[index][1] + fraction * (path[index + 1][1] - path[index][1]),
    )


def _prepare_trip(city_ids, cities_by_id, geometries):
    closed = city_ids + [city_ids[0]]
    legs = []
    for origin_id, destination_id in zip(closed[:-1], closed[1:]):
        coordinates = geometries.get((origin_id, destination_id))
        if coordinates is None:
            raise ValueError(f"falta geometría del arco {origin_id}->{destination_id}")
        cumulative = [0.0]
        for left, right in zip(coordinates[:-1], coordinates[1:]):
            cumulative.append(cumulative[-1] + _distance_km(left, right))
        length = cumulative[-1]
        if not math.isfinite(length) or length <= 0:
            raise ValueError(f"longitud geométrica no válida para {origin_id}->{destination_id}")
        legs.append({
            "origin_id": origin_id,
            "destination_id": destination_id,
            "coordinates": coordinates,
            "cumulative": cumulative,
            "length_km": length,
        })
    total = sum(leg["length_km"] for leg in legs)
    if total <= 0 or len(legs) != 47:
        raise ValueError("el tour no contiene 47 tramos dirigidos válidos")
    return legs, total


def _create_gif(method, city_ids, cities, geometries, output: Path, *, frames: int = 72, fps: int = 8):
    cities_by_id = {city.city_id: city for city in cities}
    city_ids = _normalize_cycle(city_ids, "madrid")
    legs, route_distance = _prepare_trip(city_ids, cities_by_id, geometries)
    cumulative_leg_ends = np.cumsum([leg["length_km"] for leg in legs]).tolist()

    backdrop = []
    for coordinates in geometries.values():
        step = max(1, len(coordinates) // 12)
        sample = coordinates[::step]
        if sample[-1] != coordinates[-1]:
            sample.append(coordinates[-1])
        backdrop.append(sample)

    longitude = [city.longitude for city in cities]
    latitude = [city.latitude for city in cities]
    figure, axes = plt.subplots(figsize=(8.6, 7.6), dpi=75)
    axes.add_collection(LineCollection(backdrop, colors="#d7dce2", linewidths=0.34, alpha=0.62, zorder=1))
    axes.scatter(longitude, latitude, s=15, c="#263746", edgecolors="white", linewidths=0.45, zorder=4)
    madrid = cities_by_id["madrid"]
    axes.scatter([madrid.longitude], [madrid.latitude], marker="*", s=145, c="#f2b134",
                 edgecolors="#263746", linewidths=0.7, zorder=6)
    axes.annotate("Madrid · salida y regreso", (madrid.longitude, madrid.latitude),
                  xytext=(7, 7), textcoords="offset points", fontsize=8, weight="bold", zorder=7)
    axes.set_xlim(min(longitude) - 1.1, max(longitude) + 1.1)
    axes.set_ylim(min(latitude) - 0.8, max(latitude) + 0.8)
    axes.set_aspect(np.cos(np.deg2rad(np.mean(latitude))))
    axes.set_xlabel("Longitud (°)")
    axes.set_ylabel("Latitud (°)")
    axes.grid(True, linewidth=0.35, color="#e7eaee", zorder=0)
    axes.set_title(f"Viaje TSP por España · {method}\nModelo A experimental, v = 25 EUR/h",
                   loc="left", weight="bold")
    axes.text(0.01, 0.015,
              "Rutas ORS locales · marcador según distancia recorrida · peajes experimentales, no verificados",
              transform=axes.transAxes, fontsize=7, color="#46515c")

    color = METHOD_COLORS[method]
    traveled = LineCollection([], colors=color, linewidths=2.2, alpha=0.92, zorder=3)
    axes.add_collection(traveled)
    traveler = axes.scatter([], [], s=86, marker="o", c="#f2b134", edgecolors="#18232d",
                            linewidths=1.0, zorder=8)
    axes.legend(handles=[
        Line2D([0], [0], color="#d7dce2", lw=1.4, label="Red de geometrías ORS"),
        Line2D([0], [0], color=color, lw=2.2, label="Trayecto recorrido"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#f2b134",
               markeredgecolor="#18232d", label="Viajero", markersize=7),
    ], loc="lower right", frameon=False, fontsize=8)
    progress = axes.text(0.01, 0.97, "", transform=axes.transAxes, va="top", fontsize=9, weight="bold")

    def update(frame):
        traveled_km = route_distance * frame / (frames - 1)
        leg_index = min(bisect.bisect_right(cumulative_leg_ends, traveled_km), len(legs) - 1)
        previous_end = cumulative_leg_ends[leg_index - 1] if leg_index else 0.0
        local_distance = max(0.0, traveled_km - previous_end)
        current_leg = legs[leg_index]
        partial = _interpolate_path(current_leg["coordinates"], current_leg["cumulative"], local_distance)

        visible_segments = [leg["coordinates"] for leg in legs[:leg_index]]
        current_path = current_leg["coordinates"]
        current_cumulative = current_leg["cumulative"]
        visible_points = [point for point, distance in zip(current_path, current_cumulative)
                          if distance < local_distance]
        if not visible_points or visible_points[0] != current_path[0]:
            visible_points.insert(0, current_path[0])
        if visible_points[-1] != partial:
            visible_points.append(partial)
        if len(visible_points) > 1:
            visible_segments.append(visible_points)
        traveled.set_segments(visible_segments)
        traveler.set_offsets([partial])

        origin = cities_by_id[current_leg["origin_id"]].name
        destination = cities_by_id[current_leg["destination_id"]].name
        progress.set_text(
            f"Tramo {leg_index + 1}/47: {origin} → {destination}   |   "
            f"{traveled_km:,.0f}/{route_distance:,.0f} km"
        )
        return traveled, traveler, progress

    animation = FuncAnimation(figure, update, frames=frames, interval=1000 / fps,
                              blit=False, repeat=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    animation.save(output, writer=PillowWriter(fps=fps), dpi=75)
    plt.close(figure)
    return route_distance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path,
                        default=DEFAULT_OUTPUT / "model_a_v25_aco_baselines.json")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frames", type=int, default=72)
    args = parser.parse_args()

    results = json.loads(args.results.read_text(encoding="utf-8"))
    problem, cities = load_model_a_problem(args.bundle, args.dataset, 25.0)
    if problem.size != 47:
        raise ValueError("se esperaba una instancia nacional de 47 ciudades")
    geometries = _load_route_geometries(args.dataset / "routes" / "ors_enriched")
    records = {}
    for row in results["results"]:
        name = row["algorithm"]
        if name == "Ant System (ACO)":
            records[name] = row
        elif name.startswith("Vecino más cercano + 2-opt"):
            records["Vecino más cercano + 2-opt"] = row
        elif name.startswith("Vecino más cercano ("):
            records["Vecino más cercano"] = row

    for method, filename in METHOD_FILES.items():
        if method not in records:
            raise ValueError(f"no hay resultado guardado para {method}")
        route = records[method]["tour_city_ids_open"]
        distance = _create_gif(method, route, cities, geometries,
                               args.output_dir / filename, frames=args.frames)
        print(f"{method}: {filename} | salida Madrid | 47 tramos cerrados | {distance:,.0f} km de geometría")
    print(f"\nResultados fuente: {args.results}")
    print("Animaciones generadas sin llamadas externas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
