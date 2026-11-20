from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src import config
from src.database import execute, execute_many, fetch_all
from src.earthquake import Epicenter, read_epicenter

logger = logging.getLogger(__name__)

GRID_FIELD_COUNT = 9
GRID_PGV_COLUMN = 4
GRID_PATTERN = re.compile(r"<grid_data>(.*?)</grid_data>", re.DOTALL)
SPEC_PATTERN = re.compile(r'<grid_specification ([^>]*)/>')
ATTRIBUTE_PATTERN = re.compile(r'(\w+)="([^"]*)"')


@dataclass(frozen=True)
class ShakeMapGrid:
    lon_min: float
    lat_max: float
    lon_step: float
    lat_step: float
    n_lon: int
    n_lat: int
    pgv: np.ndarray

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        column = np.rint((lon - self.lon_min) / self.lon_step).astype(np.int64)
        row = np.rint((self.lat_max - lat) / self.lat_step).astype(np.int64)
        inside = (column >= 0) & (column < self.n_lon) & (row >= 0) & (row < self.n_lat)
        values = np.zeros(lon.shape[0], dtype=float)
        values[inside] = self.pgv[row[inside], column[inside]]
        return values


def kanno_pgv_cm_s(magnitude: float, distance_km: np.ndarray, vs30: float = config.SITE_VS30_MPS) -> np.ndarray:
    distance = np.asarray(distance_km, dtype=float)
    log_bedrock = (
        config.KANNO_A * magnitude
        + config.KANNO_B * distance
        - np.log10(distance + config.KANNO_D * 10 ** (config.KANNO_E * magnitude))
        + config.KANNO_C
    )
    site_term = config.KANNO_SITE_P * np.log10(vs30) + config.KANNO_SITE_Q
    return 10 ** (log_bedrock + site_term)


def hypocentral_distance_km(epicentral_km: np.ndarray, depth_km: float) -> np.ndarray:
    return np.sqrt(np.asarray(epicentral_km, dtype=float) ** 2 + depth_km**2)


def repair_rate_per_km(pgv_cm_s: np.ndarray, ductility_k: float) -> np.ndarray:
    return config.HAZUS_RR_COEFFICIENT * ductility_k * np.asarray(pgv_cm_s, dtype=float) ** config.HAZUS_RR_EXPONENT


def failure_probability(expected_repairs: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - np.exp(-np.asarray(expected_repairs, dtype=float)), 0.0, 1.0)


def to_cartesian_km(lon: np.ndarray, lat: np.ndarray, depth_km: np.ndarray) -> np.ndarray:
    radius = config.EARTH_RADIUS_KM - np.asarray(depth_km, dtype=float)
    lon_rad = np.radians(lon)
    lat_rad = np.radians(lat)
    return np.column_stack(
        (
            radius * np.cos(lat_rad) * np.cos(lon_rad),
            radius * np.cos(lat_rad) * np.sin(lon_rad),
            radius * np.sin(lat_rad),
        )
    )


def _segment_distance(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    direction = end - start
    ratio = np.clip(((points - start) @ direction) / (direction @ direction), 0.0, 1.0)
    closest = start + ratio[:, None] * direction
    return np.linalg.norm(points - closest, axis=1)


def _inside_convex(points_2d: np.ndarray, corners_2d: np.ndarray) -> np.ndarray:
    signs = []
    for index in range(corners_2d.shape[0]):
        start = corners_2d[index]
        end = corners_2d[(index + 1) % corners_2d.shape[0]]
        edge = end - start
        relative = points_2d - start
        signs.append(edge[0] * relative[:, 1] - edge[1] * relative[:, 0])
    stacked = np.vstack(signs)
    return np.all(stacked >= 0, axis=0) | np.all(stacked <= 0, axis=0)


def distance_to_plane_km(points: np.ndarray, corners: np.ndarray) -> np.ndarray:
    origin = corners[0]
    strike = corners[1] - origin
    normal = np.cross(strike, corners[-1] - origin)
    normal /= np.linalg.norm(normal)
    axis_u = strike / np.linalg.norm(strike)
    axis_v = np.cross(normal, axis_u)
    corners_2d = np.column_stack(((corners - origin) @ axis_u, (corners - origin) @ axis_v))
    relative = points - origin
    points_2d = np.column_stack((relative @ axis_u, relative @ axis_v))
    edge_distance = np.min(
        np.vstack([_segment_distance(points, corners[i], corners[(i + 1) % corners.shape[0]]) for i in range(corners.shape[0])]),
        axis=0,
    )
    plane_distance = np.abs(relative @ normal)
    return np.where(_inside_convex(points_2d, corners_2d), plane_distance, edge_distance)


def load_rupture_quads(path: Path = config.RUPTURE_PATH) -> list[np.ndarray]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    quads: list[np.ndarray] = []
    for feature in collection["features"]:
        for polygon in feature["geometry"]["coordinates"]:
            ring = np.asarray(polygon[0], dtype=float)
            if np.allclose(ring[0], ring[-1]):
                ring = ring[:-1]
            quads.append(to_cartesian_km(ring[:, 0], ring[:, 1], ring[:, 2]))
    return quads


def rupture_distance_km(lon: np.ndarray, lat: np.ndarray, quads: list[np.ndarray]) -> np.ndarray:
    points = to_cartesian_km(lon, lat, np.zeros(lon.shape[0]))
    return np.min(np.vstack([distance_to_plane_km(points, quad) for quad in quads]), axis=0)


def load_shakemap_grid(path: Path = config.SHAKEMAP_GRID_PATH) -> ShakeMapGrid:
    text = path.read_text(encoding="utf-8")
    spec = dict(ATTRIBUTE_PATTERN.findall(SPEC_PATTERN.search(text).group(1)))
    n_lon, n_lat = int(spec["nlon"]), int(spec["nlat"])
    values = np.array(GRID_PATTERN.search(text).group(1).split(), dtype=float).reshape(-1, GRID_FIELD_COUNT)
    lon_min, lon_max = float(spec["lon_min"]), float(spec["lon_max"])
    lat_min, lat_max = float(spec["lat_min"]), float(spec["lat_max"])
    return ShakeMapGrid(
        lon_min=lon_min,
        lat_max=lat_max,
        lon_step=(lon_max - lon_min) / (n_lon - 1),
        lat_step=(lat_max - lat_min) / (n_lat - 1),
        n_lon=n_lon,
        n_lat=n_lat,
        pgv=values[:, GRID_PGV_COLUMN].reshape(n_lat, n_lon),
    )


@dataclass(frozen=True)
class Subsegments:
    edge_id: np.ndarray
    length_km: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    epicentral_km: np.ndarray


def read_subsegments(connection: Any) -> Subsegments:
    rows = fetch_all(connection, "SELECT edge_id, length_m, mid_lon, mid_lat, epicentral_distance_m FROM edge_subsegments ORDER BY edge_id")
    return Subsegments(
        edge_id=np.array([row["edge_id"] for row in rows], dtype=np.int64),
        length_km=np.array([row["length_m"] for row in rows], dtype=float) / config.METERS_PER_KM,
        lon=np.array([row["mid_lon"] for row in rows], dtype=float),
        lat=np.array([row["mid_lat"] for row in rows], dtype=float),
        epicentral_km=np.array([row["epicentral_distance_m"] for row in rows], dtype=float) / config.METERS_PER_KM,
    )


def variant_intensity(variant: str, epicenter: Epicenter, segments: Subsegments) -> tuple[np.ndarray, np.ndarray | None, float]:
    if variant in (config.VARIANT_PRIMARY, config.VARIANT_BRITTLE):
        distance = hypocentral_distance_km(segments.epicentral_km, epicenter.depth_km)
        ductility = config.HAZUS_K_BRITTLE if variant == config.VARIANT_BRITTLE else config.HAZUS_K_DUCTILE
        return kanno_pgv_cm_s(epicenter.magnitude, distance), distance, ductility
    if variant == config.VARIANT_RUPTURE:
        distance = rupture_distance_km(segments.lon, segments.lat, load_rupture_quads())
        return kanno_pgv_cm_s(epicenter.magnitude, distance), distance, config.HAZUS_K_DUCTILE
    if variant == config.VARIANT_SHAKEMAP:
        return load_shakemap_grid().sample(segments.lon, segments.lat), None, config.HAZUS_K_DUCTILE
    raise ValueError(f"variante de modelo desconocida: {variant}")


def aggregate_by_edge(edge_ids: np.ndarray, values: np.ndarray, reducer: Any) -> dict[int, float]:
    order = np.argsort(edge_ids, kind="stable")
    sorted_ids = edge_ids[order]
    boundaries = np.flatnonzero(np.diff(sorted_ids)) + 1
    starts = np.concatenate(([0], boundaries))
    reduced = reducer.reduceat(values[order], starts)
    return dict(zip(sorted_ids[starts].tolist(), reduced.tolist()))


def compute_variant(variant: str, epicenter: Epicenter, segments: Subsegments, edges: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    pgv, model_distance, ductility = variant_intensity(variant, epicenter, segments)
    repairs = repair_rate_per_km(pgv, ductility) * segments.length_km
    expected = aggregate_by_edge(segments.edge_id, repairs, np.add)
    max_pgv = aggregate_by_edge(segments.edge_id, pgv, np.maximum)
    min_distance = aggregate_by_edge(segments.edge_id, segments.epicentral_km, np.minimum)
    min_model = aggregate_by_edge(segments.edge_id, model_distance, np.minimum) if model_distance is not None else {}
    rows: list[tuple[Any, ...]] = []
    for edge in edges:
        edge_id = edge["edge_id"]
        length_km = edge["length_m"] / config.METERS_PER_KM
        is_ferry = edge["source_layer"] == config.FERRY_LAYER
        intensity = 0.0 if is_ferry else max_pgv[edge_id]
        repairs_total = 0.0 if is_ferry else expected[edge_id]
        probability = config.FERRY_FAILURE_PROBABILITY if is_ferry else float(failure_probability(repairs_total))
        rows.append(
            (
                edge_id,
                variant,
                min_distance[edge_id],
                min_model.get(edge_id),
                intensity,
                repairs_total / length_km,
                repairs_total,
                probability,
            )
        )
    return rows


def compute_failures(connection: Any) -> dict[str, Any]:
    epicenter = read_epicenter(connection)
    if epicenter.depth_km > config.KANNO_SHALLOW_MAX_DEPTH_KM:
        raise ValueError("el modelo somero de Kanno et al. (2006) requiere profundidad focal <= 30 km")
    execute(connection, (config.SQL_DIR / "06_failure.sql").read_text(encoding="utf-8"), {"step_m": config.SEGMENT_STEP_M})
    segments = read_subsegments(connection)
    edges = fetch_all(connection, "SELECT edge_id, source_layer, length_m FROM network_edges ORDER BY edge_id")
    for variant in config.FAILURE_VARIANTS:
        rows = compute_variant(variant, epicenter, segments, edges)
        execute_many(connection, "INSERT INTO edge_failure_variants VALUES %s", rows, page_size=config.INSERT_BATCH_SIZE)
        logger.info("stored variant %s", variant)
    execute(
        connection,
        "INSERT INTO edge_failure (edge_id, distance_km, intensity, repair_rate, expected_repairs, failure_probability) "
        "SELECT edge_id, distance_km, intensity, repair_rate, expected_repairs, failure_probability "
        "FROM edge_failure_variants WHERE variant = %s",
        (config.VARIANT_PRIMARY,),
    )
    update_topology_probabilities(connection)
    return {"subsegments": int(segments.edge_id.shape[0]), "edges": len(edges), "validation": validate_failures(connection)}


def update_topology_probabilities(connection: Any) -> None:
    execute(
        connection,
        "UPDATE network_edges e SET failure_probability = f.failure_probability "
        "FROM edge_failure f WHERE f.edge_id = e.edge_id",
    )


def topology_probability_check(connection: Any) -> dict[str, Any]:
    return fetch_all(
        connection,
        "SELECT count(*) AS edges, count(*) FILTER (WHERE e.failure_probability = f.failure_probability) AS matching, "
        "count(*) FILTER (WHERE e.failure_probability > 0) AS positive "
        "FROM network_edges e JOIN edge_failure f USING (edge_id)",
    )[0]


def extreme_links(connection: Any, ascending: bool, limit: int) -> list[dict[str, Any]]:
    order = "ASC" if ascending else "DESC"
    return fetch_all(
        connection,
        "SELECT e.edge_id, e.length_m / %s AS length_km, f.distance_km, f.intensity, e.failure_probability "
        "FROM network_edges e JOIN edge_failure f USING (edge_id) "
        "WHERE e.source_layer = %s AND NOT e.is_rapa_nui "
        f"ORDER BY e.failure_probability {order}, f.distance_km {order}, e.edge_id LIMIT %s",
        (config.METERS_PER_KM, config.FIBER_LAYER, limit),
    )


def distance_bands(connection: Any) -> list[dict[str, Any]]:
    edges = list(config.DISTANCE_BANDS_KM)
    rows = []
    for low, high in zip(edges[:-1], edges[1:]):
        row = fetch_all(
            connection,
            "SELECT count(*) AS links, avg(e.failure_probability) AS p_mean, "
            "count(*) FILTER (WHERE e.failure_probability > %s) AS above_half, "
            "sum(e.length_m) / %s AS km "
            "FROM network_edges e JOIN edge_failure f USING (edge_id) "
            "WHERE e.source_layer = %s AND NOT e.is_rapa_nui AND f.distance_km >= %s AND f.distance_km < %s",
            (config.DETERMINISTIC_THRESHOLD, config.METERS_PER_KM, config.FIBER_LAYER, low, high),
        )[0]
        rows.append({"low_km": low, "high_km": high, **row})
    return rows


def validate_failures(connection: Any) -> dict[str, Any]:
    row = fetch_all(
        connection,
        "SELECT (SELECT count(*) FROM network_edges) AS edges, count(*) AS with_probability, "
        "count(*) FILTER (WHERE failure_probability < 0 OR failure_probability > 1) AS out_of_range, "
        "count(*) FILTER (WHERE failure_probability = 'NaN'::float8) AS nan_values, "
        "corr(distance_km, failure_probability) AS distance_correlation FROM edge_failure",
    )[0]
    row["passed"] = (
        row["edges"] == row["with_probability"] and row["out_of_range"] == 0 and row["nan_values"] == 0 and (row["distance_correlation"] or 0) < 0
    )
    return row


def failure_statistics(connection: Any, layers: tuple[str, ...]) -> list[dict[str, Any]]:
    bins = ", ".join(f"count(*) FILTER (WHERE v.failure_probability > {threshold}) AS above_{str(threshold).replace('.', '_')}" for threshold in config.PROBABILITY_BINS)
    return fetch_all(
        connection,
        "SELECT v.variant, count(*) AS edges, min(v.failure_probability) AS p_min, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY v.failure_probability) AS p_median, "
        "avg(v.failure_probability) AS p_mean, max(v.failure_probability) AS p_max, "
        f"max(v.intensity) AS pgv_max, {bins} "
        "FROM edge_failure_variants v JOIN network_edges e USING (edge_id) "
        "WHERE e.source_layer = ANY(%s) GROUP BY v.variant ORDER BY v.variant",
        (list(layers),),
    )
