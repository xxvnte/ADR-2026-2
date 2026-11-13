from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from src import config
from src.attr import AttrResult, MonteCarloResult, compute_attr, deterministic_alive, monte_carlo_attr
from src.database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

SCOPE_CONTINENTAL = "continental"
SCOPE_WITH_RAPA_NUI = "with_rapa_nui"
METHOD_OPERATIONAL = "operational"
METHOD_MONTE_CARLO = "monte_carlo"
METHOD_DETERMINISTIC = "deterministic_threshold"
ATTR_JSON_PATH = config.OUTPUT_DIR / "attr_results.json"


@dataclass(frozen=True)
class ScenarioData:
    scenario: str
    scope: str
    edge_ids: list[int]
    edges: list[tuple[int, int]]
    node_ids: list[int]
    node_names: list[str]
    node_roles: list[str]
    key_vertices: list[int | None]


def load_scenario(connection: Any, scenario: str, scope: str) -> ScenarioData:
    layers = list(config.SCENARIO_LAYERS[scenario])
    edge_rows = fetch_all(
        connection,
        "SELECT edge_id, source, target FROM network_edges WHERE source_layer = ANY(%s) ORDER BY edge_id",
        (layers,),
    )
    node_rows = fetch_all(
        connection,
        "SELECT k.node_id, k.name, k.role, CASE WHEN a.is_anchored THEN a.vertex_id END AS vertex_id "
        "FROM key_nodes k JOIN key_node_anchors a ON a.node_id = k.node_id AND a.scenario = %s "
        "WHERE %s OR NOT k.is_rapa_nui ORDER BY k.node_id",
        (scenario, scope == SCOPE_WITH_RAPA_NUI),
    )
    return ScenarioData(
        scenario=scenario,
        scope=scope,
        edge_ids=[row["edge_id"] for row in edge_rows],
        edges=[(row["source"], row["target"]) for row in edge_rows],
        node_ids=[row["node_id"] for row in node_rows],
        node_names=[row["name"] for row in node_rows],
        node_roles=[row["role"] for row in node_rows],
        key_vertices=[row["vertex_id"] for row in node_rows],
    )


def operational_attr(data: ScenarioData) -> AttrResult:
    return compute_attr(data.edges, data.key_vertices, data.node_ids)


def sql_attr(connection: Any, data: ScenarioData) -> dict[str, Any]:
    layers = ", ".join(f"'{layer}'" for layer in config.SCENARIO_LAYERS[data.scenario])
    edges_sql = (
        "SELECT edge_id AS id, source, target, cost, reverse_cost FROM network_edges "
        f"WHERE source_layer IN ({layers})"
    )
    return fetch_one(
        connection,
        (config.SQL_DIR / "07_attr_check.sql").read_text(encoding="utf-8"),
        {"edges_sql": edges_sql, "scenario": data.scenario, "include_rapa_nui": data.scope == SCOPE_WITH_RAPA_NUI},
    )


def failure_vector(connection: Any, data: ScenarioData, variant: str) -> np.ndarray:
    rows = fetch_all(
        connection,
        "SELECT edge_id, failure_probability FROM edge_failure_variants WHERE variant = %s",
        (variant,),
    )
    lookup = {row["edge_id"]: row["failure_probability"] for row in rows}
    return np.array([lookup[edge_id] for edge_id in data.edge_ids], dtype=float)


def component_rows(data: ScenarioData, result: AttrResult) -> list[dict[str, Any]]:
    names = dict(zip(data.node_ids, data.node_names))
    return [
        {
            "component_rank": rank,
            "key_nodes": component.size,
            "pairs": component.size * (component.size - 1) // 2,
            "members": [names[node_id] for node_id in component.key_nodes],
        }
        for rank, component in enumerate(result.components, start=1)
    ]


def operational_summary(connection: Any, data: ScenarioData) -> dict[str, Any]:
    result = operational_attr(data)
    check = sql_attr(connection, data)
    names = dict(zip(data.node_ids, data.node_names))
    return {
        "scenario": data.scenario,
        "scope": data.scope,
        "edges": len(data.edges),
        "attr": result.attr,
        "n": result.n,
        "total_pairs": result.total_pairs,
        "connected_pairs": result.connected_pairs,
        "all_connected": result.all_connected,
        "components_with_key_nodes": len(result.components),
        "isolated_key_nodes": [names[node_id] for node_id in result.isolated_nodes],
        "unanchored_key_nodes": [name for name, vertex in zip(data.node_names, data.key_vertices) if vertex is None],
        "components": component_rows(data, result),
        "sql_check": {key: float(value) for key, value in check.items()},
        "sql_matches": int(check["connected_pairs"]) == result.connected_pairs and int(check["n"]) == result.n,
    }


def monte_carlo_summary(data: ScenarioData, probabilities: np.ndarray, variant: str, baseline: float) -> tuple[dict[str, Any], MonteCarloResult]:
    result = monte_carlo_attr(data.edges, probabilities, data.key_vertices, config.MONTE_CARLO_RUNS, config.MONTE_CARLO_SEED)
    low, high = result.confidence_interval(config.CONFIDENCE_Z)
    summary = {
        "scenario": data.scenario,
        "scope": data.scope,
        "variant": variant,
        "runs": config.MONTE_CARLO_RUNS,
        "seed": config.MONTE_CARLO_SEED,
        "attr_before": baseline,
        "attr_after": result.mean,
        "std": result.std,
        "ci95": [low, high],
        "percentiles": {str(value): result.percentile(value) for value in config.PERCENTILES},
        "absolute_loss": baseline - result.mean,
        "relative_loss": (baseline - result.mean) / baseline if baseline > 0 else None,
    }
    return summary, result


def deterministic_summary(data: ScenarioData, probabilities: np.ndarray, baseline: float) -> dict[str, Any]:
    alive = deterministic_alive(probabilities, config.DETERMINISTIC_THRESHOLD)
    result = compute_attr(data.edges, data.key_vertices, data.node_ids, alive=alive.tolist())
    return {
        "threshold": config.DETERMINISTIC_THRESHOLD,
        "removed_edges": int((~alive).sum()),
        "attr_after": result.attr,
        "connected_pairs": result.connected_pairs,
        "absolute_loss": baseline - result.attr,
    }


def node_impact(data: ScenarioData, result: MonteCarloResult) -> list[dict[str, Any]]:
    rows = [
        {
            "node_id": node_id,
            "name": name,
            "role": role,
            "baseline_partners": int(baseline),
            "expected_partners_after": float(expected),
            "partner_loss_probability": float(loss),
            "expected_partners_lost": float(baseline - expected),
        }
        for node_id, name, role, baseline, expected, loss in zip(
            data.node_ids,
            data.node_names,
            data.node_roles,
            result.baseline_partners,
            result.node_expected_partners,
            result.node_partner_loss_probability,
        )
    ]
    return sorted(rows, key=lambda row: (-row["expected_partners_lost"], -row["partner_loss_probability"]))


def critical_pairs(data: ScenarioData, result: MonteCarloResult) -> list[dict[str, Any]]:
    baseline = operational_attr(data)
    label = {node_id: rank for rank, component in enumerate(baseline.components) for node_id in component.key_nodes}
    rows = [
        {
            "node_a": data.node_names[first],
            "node_b": data.node_names[second],
            "connection_probability": float(result.pair_connection_probability[first, second]),
        }
        for first, second in combinations(range(len(data.node_ids)), 2)
        if label[data.node_ids[first]] == label[data.node_ids[second]]
    ]
    return sorted(rows, key=lambda row: row["connection_probability"])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value for key, value in row.items()})


def store_attr_results(connection: Any, report: dict[str, Any]) -> None:
    execute(connection, "DROP TABLE IF EXISTS attr_results")
    execute(
        connection,
        "CREATE TABLE attr_results (scenario TEXT, scope TEXT, method TEXT, variant TEXT, attr DOUBLE PRECISION, "
        "n INTEGER, total_pairs INTEGER, connected_pairs DOUBLE PRECISION, std DOUBLE PRECISION, p5 DOUBLE PRECISION, "
        "p50 DOUBLE PRECISION, p95 DOUBLE PRECISION, ci_low DOUBLE PRECISION, ci_high DOUBLE PRECISION, runs INTEGER, seed BIGINT)",
    )
    for row in report["operational"]:
        execute(
            connection,
            "INSERT INTO attr_results (scenario, scope, method, attr, n, total_pairs, connected_pairs) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (row["scenario"], row["scope"], METHOD_OPERATIONAL, row["attr"], row["n"], row["total_pairs"], row["connected_pairs"]),
        )
    for row in report["post_earthquake"]:
        execute(
            connection,
            "INSERT INTO attr_results (scenario, scope, method, variant, attr, std, p5, p50, p95, ci_low, ci_high, runs, seed) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["scenario"], row["scope"], METHOD_MONTE_CARLO, row["variant"], row["attr_after"], row["std"],
                row["percentiles"]["5"], row["percentiles"]["50"], row["percentiles"]["95"], row["ci95"][0], row["ci95"][1],
                row["runs"], row["seed"],
            ),
        )
    deterministic = report["deterministic"]
    if not deterministic:
        return
    execute(
        connection,
        "INSERT INTO attr_results (scenario, scope, method, variant, attr, connected_pairs) VALUES (%s, %s, %s, %s, %s, %s)",
        (config.BASE_SCENARIO, SCOPE_CONTINENTAL, METHOD_DETERMINISTIC, config.VARIANT_PRIMARY, deterministic["attr_after"], deterministic["connected_pairs"]),
    )


def run_attr(connection: Any, with_earthquake: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {"operational": [], "post_earthquake": [], "deterministic": {}, "node_impact": [], "critical_pairs": []}
    datasets: dict[tuple[str, str], ScenarioData] = {}
    for scenario in config.SCENARIO_LAYERS:
        for scope in (SCOPE_CONTINENTAL, SCOPE_WITH_RAPA_NUI):
            data = load_scenario(connection, scenario, scope)
            datasets[(scenario, scope)] = data
            report["operational"].append(operational_summary(connection, data))
    if with_earthquake:
        run_post_earthquake(connection, report, datasets)
    persist_report(connection, report)
    return report


def _baseline(report: dict[str, Any], scenario: str, scope: str) -> float:
    return next(row["attr"] for row in report["operational"] if row["scenario"] == scenario and row["scope"] == scope)


def run_post_earthquake(connection: Any, report: dict[str, Any], datasets: dict[tuple[str, str], ScenarioData]) -> None:
    base = datasets[(config.BASE_SCENARIO, SCOPE_CONTINENTAL)]
    base_before = _baseline(report, config.BASE_SCENARIO, SCOPE_CONTINENTAL)
    primary_samples: MonteCarloResult | None = None
    for variant in config.FAILURE_VARIANTS:
        probabilities = failure_vector(connection, base, variant)
        summary, result = monte_carlo_summary(base, probabilities, variant, base_before)
        report["post_earthquake"].append(summary)
        if variant == config.VARIANT_PRIMARY:
            primary_samples = result
            report["deterministic"] = deterministic_summary(base, probabilities, base_before)
    all_layers = datasets[(config.ALL_LAYERS_SCENARIO, SCOPE_CONTINENTAL)]
    summary, _ = monte_carlo_summary(
        all_layers,
        failure_vector(connection, all_layers, config.VARIANT_PRIMARY),
        config.VARIANT_PRIMARY,
        _baseline(report, config.ALL_LAYERS_SCENARIO, SCOPE_CONTINENTAL),
    )
    report["post_earthquake"].append(summary)
    if primary_samples is not None:
        report["node_impact"] = node_impact(base, primary_samples)
        report["critical_pairs"] = critical_pairs(base, primary_samples)
        report["primary_samples"] = primary_samples.samples.tolist()
        report["primary_running_mean"] = primary_samples.running_mean().tolist()


def persist_report(connection: Any, report: dict[str, Any]) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {key: value for key, value in report.items() if key not in ("primary_samples", "primary_running_mean")}
    ATTR_JSON_PATH.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    base = next(row for row in report["operational"] if row["scenario"] == config.BASE_SCENARIO and row["scope"] == SCOPE_CONTINENTAL)
    write_csv(config.OUTPUT_DIR / "attr_components.csv", base["components"])
    if report["node_impact"]:
        write_csv(config.OUTPUT_DIR / "key_node_impact.csv", report["node_impact"])
        write_csv(config.OUTPUT_DIR / "critical_pairs.csv", report["critical_pairs"])
        np.savetxt(config.OUTPUT_DIR / "monte_carlo_samples.csv", np.asarray(report["primary_samples"]), delimiter=",", header="attr_k", comments="")
    store_attr_results(connection, report)
