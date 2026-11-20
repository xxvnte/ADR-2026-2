from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from src import config
from src.attr import attr_from_labels, index_graph, key_labels
from src.database import fetch_all

REGION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("arica", "Arica y Parinacota"),
    ("tarapac", "Tarapacá"),
    ("antofagasta", "Antofagasta"),
    ("atacama", "Atacama"),
    ("coquimbo", "Coquimbo"),
    ("valpara", "Valparaíso"),
    ("region metropolitana", "Metropolitana de Santiago"),
    ("libertador", "Libertador General Bernardo O'Higgins"),
    ("maule", "Maule"),
    ("nuble", "Ñuble"),
    ("uble", "Ñuble"),
    ("bio", "Biobío"),
    ("bho", "Biobío"),
    ("la araucan", "La Araucanía"),
    ("los r", "Los Ríos"),
    ("los lagos", "Los Lagos"),
    ("ais", "Aysén del General Carlos Ibáñez del Campo"),
    ("magallanes", "Magallanes y de la Antártica Chilena"),
)
RAPA_NUI_REGION = "Valparaíso"
NEAR_SAME_PLACE = "cerca de {name}"


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    lon: float
    lat: float


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower().strip()


def normalize_region(raw: str) -> str | None:
    key = _ascii(raw)
    return next((region for prefix, region in REGION_PREFIXES if key.startswith(prefix)), None)


def haversine_km(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    chord = math.sin((phi_b - phi_a) / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(math.radians(lon_b - lon_a) / 2) ** 2
    return 2 * config.EARTH_RADIUS_KM * math.asin(math.sqrt(chord))


def chile_places() -> list[Place]:
    collection = json.loads((config.EXTERNAL_DIR / "natural_earth_places.geojson").read_text(encoding="utf-8"))
    places = []
    for feature in collection["features"]:
        properties = feature["properties"]
        region = normalize_region(properties.get("adm1name") or "")
        if properties["iso_a2"] != config.CHILE_COUNTRY_CODE or region is None:
            continue
        places.append(Place(properties["name"], region, float(properties["longitude"]), float(properties["latitude"])))
    return places


def nearest_place(places: list[Place], lon: float, lat: float) -> Place:
    return min(places, key=lambda place: haversine_km(lon, lat, place.lon, place.lat))


def key_nodes_table(connection: Any) -> list[dict[str, Any]]:
    places = chile_places()
    rows = fetch_all(
        connection,
        "SELECT k.node_id, k.name, string_agg(r.role, ',' ORDER BY r.role) AS roles, "
        "ST_Y(k.geom) AS lat, ST_X(k.geom) AS lon, k.is_rapa_nui, k.vertex_id, k.anchor_distance_m, k.source, k.justification "
        "FROM key_nodes k JOIN key_node_roles r USING (node_id) GROUP BY k.node_id ORDER BY k.node_id",
    )
    table = []
    for row in rows:
        region = RAPA_NUI_REGION if row["is_rapa_nui"] else nearest_place(places, row["lon"], row["lat"]).region
        table.append({
            "node_id": row["node_id"],
            "name": row["name"],
            "roles": row["roles"],
            "lat": round(row["lat"], config.COORDINATE_DECIMALS),
            "lon": round(row["lon"], config.COORDINATE_DECIMALS),
            "region": region,
            "vertex_id": row["vertex_id"],
            "anchor_m": round(row["anchor_distance_m"] or 0.0),
            "source": row["source"],
            "justification": row["justification"],
        })
    return table


def _fiber_graph(connection: Any) -> nx.Graph:
    rows = fetch_all(
        connection,
        "SELECT source, target, length_m FROM network_edges WHERE source_layer = %s AND NOT is_rapa_nui",
        (config.FIBER_LAYER,),
    )
    graph = nx.Graph()
    for row in rows:
        if row["source"] != row["target"]:
            graph.add_edge(row["source"], row["target"], weight=row["length_m"])
    return graph


def weighted_path_load(graph: nx.Graph, weights: dict[int, int]) -> dict[int, int]:
    load: dict[int, int] = {}
    sources = sorted(weights)
    for index, source in enumerate(sources):
        paths = nx.single_source_dijkstra_path(graph, source, weight="weight")
        for target in sources[index + 1:]:
            if target not in paths:
                continue
            pairs = weights[source] * weights[target]
            for vertex in paths[target][1:-1]:
                load[vertex] = load.get(vertex, 0) + pairs
    return load


def backbone_nodes(connection: Any, key_vertices: list[int | None]) -> list[dict[str, Any]]:
    graph = _fiber_graph(connection)
    weights: dict[int, int] = {}
    for vertex in key_vertices:
        if vertex is not None and vertex in graph:
            weights[vertex] = weights.get(vertex, 0) + 1
    load = weighted_path_load(graph, weights)
    articulation = set(nx.articulation_points(graph))
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    component_of = {vertex: rank for rank, members in enumerate(components, start=1) for vertex in members}
    keys_in = {rank: sum(weights.get(vertex, 0) for vertex in members) for rank, members in enumerate(components, start=1)}
    ranked = sorted(
        (vertex for vertex, pairs in load.items() if pairs > 0 and graph.degree(vertex) >= config.BACKBONE_MIN_DEGREE),
        key=lambda vertex: (-load[vertex], -graph.degree(vertex), vertex),
    )[: config.BACKBONE_NODES_COUNT]
    coordinates = {
        row["id"]: row
        for row in fetch_all(connection, "SELECT id, ST_Y(the_geom) AS lat, ST_X(the_geom) AS lon FROM network_vertices WHERE id = ANY(%s)", (ranked,))
    }
    places = chile_places()
    result = []
    for rank, vertex in enumerate(ranked, start=1):
        lat, lon = coordinates[vertex]["lat"], coordinates[vertex]["lon"]
        result.append({
            "rank": rank,
            "vertex_id": vertex,
            "lat": round(lat, config.COORDINATE_DECIMALS),
            "lon": round(lon, config.COORDINATE_DECIMALS),
            "near": nearest_place(places, lon, lat).name,
            "degree": graph.degree(vertex),
            "key_pairs_through": load[vertex],
            "is_articulation": vertex in articulation,
            "component": component_of[vertex],
            "component_key_nodes": keys_in[component_of[vertex]],
        })
    return result


def _endpoint_names(connection: Any, edge_ids: list[int]) -> dict[int, str]:
    places = chile_places()
    rows = fetch_all(
        connection,
        "SELECT edge_id, ST_X(ST_StartPoint(geom)) AS x1, ST_Y(ST_StartPoint(geom)) AS y1, "
        "ST_X(ST_EndPoint(geom)) AS x2, ST_Y(ST_EndPoint(geom)) AS y2 FROM network_edges WHERE edge_id = ANY(%s)",
        (edge_ids,),
    )
    names = {}
    for row in rows:
        first = nearest_place(places, row["x1"], row["y1"]).name
        second = nearest_place(places, row["x2"], row["y2"]).name
        names[row["edge_id"]] = NEAR_SAME_PLACE.format(name=first) if first == second else f"{first} – {second}"
    return names


def critical_links(connection: Any, edges: list[tuple[int, int]], edge_ids: list[int], key_vertices: list[int | None], probabilities: np.ndarray) -> list[dict[str, Any]]:
    graph = index_graph(edges, key_vertices)
    base_labels = key_labels(graph)
    base_attr = attr_from_labels(base_labels)
    labels, counts = np.unique(base_labels[base_labels >= 0], return_counts=True)
    shared = set(labels[counts >= 2].tolist())
    vertex_labels = _vertex_component_labels(graph)
    key_components = _key_component_set(graph, vertex_labels, base_labels, shared)
    candidates = [position for position in range(len(edge_ids)) if int(vertex_labels[graph.source_index[position]]) in key_components]
    rows = []
    alive = np.ones(len(edge_ids), dtype=bool)
    for position in candidates:
        alive[position] = False
        delta = base_attr - attr_from_labels(key_labels(graph, alive))
        alive[position] = True
        if delta <= 0:
            continue
        rows.append({"position": position, "edge_id": edge_ids[position], "delta_attr": delta, "probability": float(probabilities[position])})
    names = _endpoint_names(connection, [row["edge_id"] for row in rows])
    lengths = {
        row["edge_id"]: row["length_m"]
        for row in fetch_all(connection, "SELECT edge_id, length_m FROM network_edges WHERE edge_id = ANY(%s)", ([row["edge_id"] for row in rows],))
    }
    result = [
        {
            "edge_id": row["edge_id"],
            "segment": names[row["edge_id"]],
            "length_km": round(lengths[row["edge_id"]] / config.METERS_PER_KM, config.DISPLAY_DECIMALS_KM),
            "failure_probability": round(row["probability"], config.DISPLAY_DECIMALS_PROBABILITY),
            "delta_attr": round(row["delta_attr"], config.DISPLAY_DECIMALS_PROBABILITY),
            "pairs_lost": round(row["delta_attr"] * _pairs(len(key_vertices))),
            "risk": round(row["probability"] * row["delta_attr"], config.DISPLAY_DECIMALS_RISK),
        }
        for row in rows
    ]
    return sorted(result, key=lambda row: (-row["risk"], -row["delta_attr"], row["edge_id"]))


def _pairs(count: int) -> int:
    return count * (count - 1) // 2


def _vertex_component_labels(graph: Any) -> np.ndarray:
    weights = np.ones(graph.source_index.shape[0], dtype=np.int32)
    adjacency = coo_matrix((weights, (graph.source_index, graph.target_index)), shape=(graph.vertex_count, graph.vertex_count)).tocsr()
    _, labels = connected_components(adjacency, directed=False)
    return labels


def _key_component_set(graph: Any, vertex_labels: np.ndarray, base_labels: np.ndarray, shared: set[int]) -> set[int]:
    return {int(vertex_labels[graph.key_index[i]]) for i in range(graph.key_index.shape[0]) if graph.key_index[i] >= 0 and int(base_labels[i]) in shared}


def convergence(running_mean: list[float], std: float, tolerance: float) -> dict[str, Any]:
    values = np.asarray(running_mean)
    final = float(values[-1])
    outside = np.flatnonzero(np.abs(values - final) > tolerance)
    stable_from = int(outside[-1]) + 2 if outside.size else 1
    return {
        "runs": int(values.shape[0]),
        "standard_error": std / math.sqrt(values.shape[0]),
        "tolerance": tolerance,
        "stable_from": stable_from,
    }
