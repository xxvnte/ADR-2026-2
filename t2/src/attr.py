from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

UNANCHORED_INDEX = -1


@dataclass(frozen=True)
class ComponentDetail:
    label: int
    key_nodes: tuple[int, ...]

    @property
    def size(self) -> int:
        return len(self.key_nodes)


@dataclass(frozen=True)
class AttrResult:
    attr: float
    n: int
    total_pairs: int
    connected_pairs: int
    components: tuple[ComponentDetail, ...] = field(default_factory=tuple)

    @property
    def all_connected(self) -> bool:
        return self.connected_pairs == self.total_pairs

    @property
    def isolated_nodes(self) -> tuple[int, ...]:
        return tuple(component.key_nodes[0] for component in self.components if component.size == 1)


@dataclass(frozen=True)
class IndexedGraph:
    vertex_count: int
    source_index: np.ndarray
    target_index: np.ndarray
    key_index: np.ndarray


def pairs(count: int) -> int:
    return count * (count - 1) // 2


def index_graph(edges: Sequence[tuple[int, int]], key_vertex_ids: Sequence[int | None]) -> IndexedGraph:
    vertex_ids = {vertex for edge in edges for vertex in edge}
    vertex_ids.update(vertex for vertex in key_vertex_ids if vertex is not None)
    position = {vertex: index for index, vertex in enumerate(sorted(vertex_ids))}
    edge_array = np.array([(position[a], position[b]) for a, b in edges], dtype=np.int64).reshape(-1, 2)
    key_index = np.array(
        [position[vertex] if vertex is not None else UNANCHORED_INDEX for vertex in key_vertex_ids],
        dtype=np.int64,
    )
    return IndexedGraph(len(position), edge_array[:, 0], edge_array[:, 1], key_index)


def key_labels(graph: IndexedGraph, alive: np.ndarray | None = None) -> np.ndarray:
    mask = np.ones(graph.source_index.shape[0], dtype=bool) if alive is None else alive
    sources = graph.source_index[mask]
    targets = graph.target_index[mask]
    weights = np.ones(sources.shape[0], dtype=np.int32)
    adjacency = coo_matrix((weights, (sources, targets)), shape=(graph.vertex_count, graph.vertex_count)).tocsr()
    _, labels = connected_components(adjacency, directed=False)
    result = np.empty(graph.key_index.shape[0], dtype=np.int64)
    anchored = graph.key_index >= 0
    result[anchored] = labels[graph.key_index[anchored]]
    unanchored_count = int((~anchored).sum())
    result[~anchored] = -np.arange(1, unanchored_count + 1)
    return result


def attr_from_labels(labels: np.ndarray) -> float:
    count = labels.shape[0]
    if count < 2:
        raise ValueError("el ATTR requiere al menos dos nodos clave")
    _, sizes = np.unique(labels, return_counts=True)
    return float((sizes * (sizes - 1) // 2).sum() / pairs(count))


def summarize(labels: np.ndarray, node_ids: Sequence[int]) -> AttrResult:
    count = labels.shape[0]
    if count < 2:
        raise ValueError("el ATTR requiere al menos dos nodos clave")
    groups: dict[int, list[int]] = {}
    for label, node_id in zip(labels.tolist(), node_ids):
        groups.setdefault(label, []).append(node_id)
    components = tuple(
        sorted(
            (ComponentDetail(label, tuple(members)) for label, members in groups.items()),
            key=lambda component: (-component.size, component.key_nodes[0]),
        )
    )
    connected = sum(pairs(component.size) for component in components)
    return AttrResult(connected / pairs(count), count, pairs(count), connected, components)


def compute_attr(
    edges: Sequence[tuple[int, int]],
    key_vertex_ids: Sequence[int | None],
    node_ids: Sequence[int] | None = None,
    alive: Sequence[bool] | None = None,
) -> AttrResult:
    graph = index_graph(edges, key_vertex_ids)
    mask = None if alive is None else np.asarray(alive, dtype=bool)
    labels = key_labels(graph, mask)
    identifiers = list(node_ids) if node_ids is not None else list(range(len(key_vertex_ids)))
    return summarize(labels, identifiers)


@dataclass(frozen=True)
class MonteCarloResult:
    samples: np.ndarray
    pair_connection_probability: np.ndarray
    node_partner_loss_probability: np.ndarray
    node_expected_partners: np.ndarray
    baseline_partners: np.ndarray

    @property
    def mean(self) -> float:
        return float(self.samples.mean())

    @property
    def std(self) -> float:
        return float(self.samples.std(ddof=1)) if self.samples.shape[0] > 1 else 0.0

    def percentile(self, value: float) -> float:
        return float(np.percentile(self.samples, value))

    def confidence_interval(self, z_value: float) -> tuple[float, float]:
        half_width = z_value * self.std / np.sqrt(self.samples.shape[0])
        return float(self.mean - half_width), float(self.mean + half_width)

    def running_mean(self) -> np.ndarray:
        return np.cumsum(self.samples) / np.arange(1, self.samples.shape[0] + 1)


def same_component_matrix(labels: np.ndarray) -> np.ndarray:
    matrix = labels[:, None] == labels[None, :]
    np.fill_diagonal(matrix, False)
    return matrix


def sample_alive(probabilities: np.ndarray, generator: np.random.Generator) -> np.ndarray:
    return generator.random(probabilities.shape[0]) >= probabilities


def monte_carlo_attr(
    edges: Sequence[tuple[int, int]],
    failure_probabilities: Sequence[float],
    key_vertex_ids: Sequence[int | None],
    runs: int,
    seed: int,
) -> MonteCarloResult:
    graph = index_graph(edges, key_vertex_ids)
    probabilities = np.asarray(failure_probabilities, dtype=float)
    generator = np.random.default_rng(seed)
    baseline = same_component_matrix(key_labels(graph))
    node_count = graph.key_index.shape[0]
    samples = np.empty(runs, dtype=float)
    pair_hits = np.zeros((node_count, node_count), dtype=np.int64)
    partner_loss = np.zeros(node_count, dtype=np.int64)
    partner_total = np.zeros(node_count, dtype=np.int64)
    for run in range(runs):
        labels = key_labels(graph, sample_alive(probabilities, generator))
        samples[run] = attr_from_labels(labels)
        connected = same_component_matrix(labels)
        pair_hits += connected
        partners = connected.sum(axis=1)
        partner_total += partners
        partner_loss += partners < baseline.sum(axis=1)
    return MonteCarloResult(
        samples=samples,
        pair_connection_probability=pair_hits / runs,
        node_partner_loss_probability=partner_loss / runs,
        node_expected_partners=partner_total / runs,
        baseline_partners=baseline.sum(axis=1),
    )


def deterministic_alive(failure_probabilities: Sequence[float], threshold: float) -> np.ndarray:
    return np.asarray(failure_probabilities, dtype=float) < threshold
