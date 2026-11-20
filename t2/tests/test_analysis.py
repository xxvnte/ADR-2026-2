import math

import networkx as nx
import numpy as np

from src.analysis import convergence, normalize_region, weighted_path_load
from src.attr import attr_from_labels, index_graph, key_labels


def test_region_names_are_normalized() -> None:
    assert normalize_region("BHo-B") == "Biobío"
    assert normalize_region("Ñuble") == "Ñuble"
    assert normalize_region("Los R") == "Los Ríos"
    assert normalize_region("Tarapacm") == "Tarapacá"
    assert normalize_region("Región Metropolitana de Santiago") == "Metropolitana de Santiago"
    assert normalize_region("Santa Cruz") is None


def test_weighted_path_load_counts_key_node_pairs() -> None:
    graph = nx.Graph()
    graph.add_edge(1, 2, weight=1.0)
    graph.add_edge(2, 3, weight=1.0)
    graph.add_edge(3, 4, weight=1.0)
    load = weighted_path_load(graph, {1: 3, 4: 2})
    assert load == {2: 6, 3: 6}


def test_removing_bridge_reduces_attr() -> None:
    edges = [(1, 2), (2, 3)]
    graph = index_graph(edges, [1, 3])
    base = attr_from_labels(key_labels(graph))
    without_bridge = attr_from_labels(key_labels(graph, np.array([True, False])))
    assert base == 1.0
    assert without_bridge == 0.0


def test_convergence_reports_standard_error_and_stable_iteration() -> None:
    running = [0.5, 0.3, 0.41, 0.401, 0.4]
    result = convergence(running, std=0.2, tolerance=0.02)
    assert math.isclose(result["standard_error"], 0.2 / math.sqrt(5))
    assert result["stable_from"] == 3
    assert result["runs"] == 5
