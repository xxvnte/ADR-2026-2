import math

import numpy as np
import pytest

from src.attr import compute_attr, deterministic_alive, monte_carlo_attr

CHAIN = [(1, 2), (2, 3)]


def test_chain_of_three_is_fully_connected() -> None:
    result = compute_attr(CHAIN, [1, 2, 3])
    assert result.attr == 1.0
    assert result.total_pairs == 3
    assert result.connected_pairs == 3
    assert result.all_connected


def test_removing_central_link_keeps_one_pair() -> None:
    result = compute_attr(CHAIN, [1, 2, 3], alive=[True, False])
    assert math.isclose(result.attr, 1 / 3)
    assert not result.all_connected
    assert result.isolated_nodes == (2,)


def test_two_components_of_two_nodes() -> None:
    result = compute_attr([(1, 2), (3, 4)], [1, 2, 3, 4])
    assert math.isclose(result.attr, 2 / 6)
    assert [component.size for component in result.components] == [2, 2]


def test_star_of_five_with_two_failed_leaves() -> None:
    star = [(0, 1), (0, 2), (0, 3), (0, 4)]
    result = compute_attr(star, [0, 1, 2, 3, 4], alive=[True, True, False, False])
    assert math.isclose(result.attr, 3 / 10)


def test_key_nodes_on_same_vertex_are_connected() -> None:
    result = compute_attr([(1, 2)], [1, 1, 3], alive=[False])
    assert math.isclose(result.attr, 1 / 3)


def test_unanchored_node_is_isolated() -> None:
    result = compute_attr(CHAIN, [1, 3, None], node_ids=[10, 30, 99])
    assert math.isclose(result.attr, 1 / 3)
    assert 99 in result.isolated_nodes


def test_non_key_vertices_do_not_count() -> None:
    result = compute_attr([(1, 5), (5, 6), (6, 2)], [1, 2])
    assert result.n == 2
    assert result.attr == 1.0


def test_fewer_than_two_key_nodes_raises() -> None:
    with pytest.raises(ValueError):
        compute_attr(CHAIN, [1])


def test_monte_carlo_without_failures_matches_operational() -> None:
    result = monte_carlo_attr(CHAIN, [0.0, 0.0], [1, 2, 3], runs=50, seed=1)
    assert result.mean == 1.0
    assert result.std == 0.0


def test_monte_carlo_with_certain_failure_matches_disconnected() -> None:
    result = monte_carlo_attr(CHAIN, [0.0, 1.0], [1, 2, 3], runs=50, seed=1)
    assert math.isclose(result.mean, 1 / 3)


def test_monte_carlo_estimates_expectation_of_equation_nine() -> None:
    probability = 0.3
    expected = (1 - probability) ** 2 * 1.0 + 2 * probability * (1 - probability) * (1 / 3) + probability**2 * 0.0
    result = monte_carlo_attr(CHAIN, [probability, probability], [1, 2, 3], runs=20000, seed=7)
    assert abs(result.mean - expected) < 0.01


def test_monte_carlo_is_reproducible_with_seed() -> None:
    first = monte_carlo_attr(CHAIN, [0.5, 0.5], [1, 2, 3], runs=100, seed=3)
    second = monte_carlo_attr(CHAIN, [0.5, 0.5], [1, 2, 3], runs=100, seed=3)
    assert np.array_equal(first.samples, second.samples)


def test_deterministic_threshold() -> None:
    assert deterministic_alive([0.2, 0.5, 0.9], 0.5).tolist() == [True, False, False]
