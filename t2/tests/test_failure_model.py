import math

import numpy as np

from src import config
from src.failure_model import (
    distance_to_plane_km,
    failure_probability,
    hypocentral_distance_km,
    kanno_pgv_cm_s,
    repair_rate_per_km,
    to_cartesian_km,
)

MAGNITUDE = 8.8


def test_kanno_matches_hand_calculation() -> None:
    distance = 100.0
    expected_log = (
        config.KANNO_A * MAGNITUDE
        + config.KANNO_B * distance
        - math.log10(distance + config.KANNO_D * 10 ** (config.KANNO_E * MAGNITUDE))
        + config.KANNO_C
        + config.KANNO_SITE_P * math.log10(config.SITE_VS30_MPS)
        + config.KANNO_SITE_Q
    )
    assert math.isclose(float(kanno_pgv_cm_s(MAGNITUDE, np.array([distance]))[0]), 10**expected_log, rel_tol=1e-12)


def test_pgv_decreases_with_distance() -> None:
    pgv = kanno_pgv_cm_s(MAGNITUDE, np.linspace(1, 2000, 200))
    assert np.all(np.diff(pgv) < 0)


def test_stiffer_site_reduces_pgv() -> None:
    soft = kanno_pgv_cm_s(MAGNITUDE, np.array([100.0]), vs30=300.0)
    stiff = kanno_pgv_cm_s(MAGNITUDE, np.array([100.0]), vs30=760.0)
    assert stiff[0] < soft[0]


def test_hazus_repair_rate_formula() -> None:
    assert math.isclose(float(repair_rate_per_km(np.array([10.0]), 1.0)[0]), 0.0001 * 10**2.25)
    assert math.isclose(float(repair_rate_per_km(np.array([10.0]), config.HAZUS_K_DUCTILE)[0]), 0.3 * 0.0001 * 10**2.25)


def test_zero_distance_gives_maximum_probability() -> None:
    distances = np.array([0.0, 50.0, 200.0, 1000.0])
    pgv = kanno_pgv_cm_s(MAGNITUDE, hypocentral_distance_km(distances, 22.9))
    probability = failure_probability(repair_rate_per_km(pgv, config.HAZUS_K_DUCTILE) * 10.0)
    assert probability[0] == probability.max()
    assert np.all(np.diff(probability) < 0)


def test_large_distance_gives_near_zero_probability() -> None:
    pgv = kanno_pgv_cm_s(MAGNITUDE, np.array([3000.0]))
    probability = failure_probability(repair_rate_per_km(pgv, config.HAZUS_K_DUCTILE) * 1.0)
    assert probability[0] < 1e-3


def test_probability_bounds_and_poisson_form() -> None:
    probability = failure_probability(np.array([0.0, 1.0, 1e6]))
    assert probability[0] == 0.0
    assert math.isclose(probability[1], 1 - math.exp(-1))
    assert probability[2] == 1.0


def test_longer_link_fails_more() -> None:
    rate = repair_rate_per_km(np.array([30.0]), config.HAZUS_K_DUCTILE)
    assert failure_probability(rate * 20.0)[0] > failure_probability(rate * 2.0)[0]


def test_hypocentral_distance() -> None:
    assert math.isclose(float(hypocentral_distance_km(np.array([30.0]), 40.0)[0]), 50.0)


def test_distance_to_plane_inside_and_outside() -> None:
    lon = np.array([-73.0, -73.0, -73.0, -73.0])
    lat = np.array([-35.0, -35.0, -35.0, -35.0])
    depth = np.array([10.0, 10.0, 30.0, 30.0])
    corners = to_cartesian_km(np.array([-74.0, -72.0, -72.0, -74.0]), np.array([-36.0, -36.0, -34.0, -34.0]), depth)
    above = to_cartesian_km(lon[:1], lat[:1], np.array([0.0]))
    distance = distance_to_plane_km(above, corners)
    assert 10.0 < distance[0] < 30.0
    far = to_cartesian_km(np.array([-60.0]), np.array([-35.0]), np.array([0.0]))
    assert distance_to_plane_km(far, corners)[0] > 1000.0
