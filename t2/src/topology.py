from __future__ import annotations

import logging
import re
from typing import Any

from src import config
from src.database import execute, fetch_all, fetch_one, fetch_scalar

logger = logging.getLogger(__name__)

ANALYZE_PATTERN = re.compile(r"(Isolated segments|Dead ends|Potential gaps found near dead ends|Intersections detected|Ring geometries)\s*:\s*(\d+)")
SCRATCH_TABLE = "tolerance_scratch"


def pgrouting_version(connection: Any) -> str:
    return str(fetch_scalar(connection, "SELECT pgr_version()"))


def _plain_layer_filter(layers: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{layer}'" for layer in layers)
    return f"source_layer IN ({quoted})"


def build_topology(connection: Any, tolerance: float = config.TOPOLOGY_TOLERANCE_DEG) -> dict[str, Any]:
    connection.notices.clear()
    sql = (config.SQL_DIR / "03_topology.sql").read_text(encoding="utf-8")
    execute(connection, sql, {"tolerance": tolerance, "rapa_nui_lon": config.RAPA_NUI_MAX_LONGITUDE})
    analysis = parse_analyze_notices(connection.notices)
    store_analysis(connection, tolerance, analysis)
    return analysis


def parse_analyze_notices(notices: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for notice in notices:
        for label, value in ANALYZE_PATTERN.findall(notice):
            found[label] = int(value)
    return found


def store_analysis(connection: Any, tolerance: float, analysis: dict[str, int]) -> None:
    execute(connection, "DROP TABLE IF EXISTS topology_analysis")
    execute(connection, "CREATE TABLE topology_analysis (tolerance_deg DOUBLE PRECISION, metric TEXT, value INTEGER)")
    for metric, value in analysis.items():
        execute(connection, "INSERT INTO topology_analysis VALUES (%s, %s, %s)", (tolerance, metric, value))


def component_count(connection: Any, table: str, layers: tuple[str, ...]) -> dict[str, int]:
    edges_sql = f"SELECT edge_id AS id, source, target, length_m AS cost, length_m AS reverse_cost FROM {table} WHERE {_plain_layer_filter(layers)}"
    return fetch_one(
        connection,
        "SELECT count(DISTINCT component) AS components, count(*) AS vertices, "
        "max(size) AS largest_component "
        "FROM (SELECT node, component, count(*) OVER (PARTITION BY component) AS size "
        "FROM pgr_connectedComponents(%s)) c",
        (edges_sql,),
    )


def _scratch_topology(connection: Any, layers: tuple[str, ...], tolerance: float) -> dict[str, int]:
    execute(connection, f"DROP TABLE IF EXISTS {SCRATCH_TABLE}")
    execute(connection, f"DROP TABLE IF EXISTS {SCRATCH_TABLE}_vertices_pgr")
    execute(
        connection,
        f"CREATE TABLE {SCRATCH_TABLE} AS SELECT edge_id, source_layer, geom, length_m, "
        f"NULL::BIGINT AS source, NULL::BIGINT AS target FROM network_edges "
        f"WHERE {_plain_layer_filter(layers)} AND NOT is_rapa_nui",
    )
    execute(connection, f"CREATE INDEX ON {SCRATCH_TABLE} USING GIST (geom)")
    execute(connection, f"SELECT pgr_createTopology('{SCRATCH_TABLE}', %s, 'geom', 'edge_id', 'source', 'target')", (tolerance,))
    return component_count(connection, SCRATCH_TABLE, layers)


def _scratch_noded(connection: Any, layers: tuple[str, ...], tolerance: float) -> dict[str, int]:
    _scratch_topology(connection, layers, tolerance)
    noded = f"{SCRATCH_TABLE}_noded"
    execute(connection, f"DROP TABLE IF EXISTS {noded}")
    execute(connection, f"DROP TABLE IF EXISTS {noded}_vertices_pgr")
    execute(connection, f"SELECT pgr_nodeNetwork('{SCRATCH_TABLE}', %s, 'edge_id', 'geom')", (tolerance,))
    execute(connection, f"ALTER TABLE {noded} ADD COLUMN edge_id BIGINT, ADD COLUMN source_layer TEXT, ADD COLUMN length_m DOUBLE PRECISION")
    execute(
        connection,
        f"UPDATE {noded} n SET edge_id = n.id, source_layer = s.source_layer, "
        f"length_m = ST_Length(n.geom::geography) FROM {SCRATCH_TABLE} s WHERE s.edge_id = n.old_id",
    )
    execute(connection, f"SELECT pgr_createTopology('{noded}', %s, 'geom', 'edge_id', 'source', 'target')", (tolerance,))
    result = component_count(connection, noded, layers)
    execute(connection, f"DROP TABLE IF EXISTS {noded}")
    execute(connection, f"DROP TABLE IF EXISTS {noded}_vertices_pgr")
    return result


def compare_tolerances(connection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario, layers in config.SCENARIO_LAYERS.items():
        for tolerance in config.TOLERANCE_CANDIDATES_DEG:
            stats = _scratch_topology(connection, layers, tolerance)
            rows.append(_tolerance_row(scenario, tolerance, "snap_only", stats))
        noded = _scratch_noded(connection, layers, config.TOPOLOGY_TOLERANCE_DEG)
        rows.append(_tolerance_row(scenario, config.TOPOLOGY_TOLERANCE_DEG, "snap_and_node", noded))
    execute(connection, f"DROP TABLE IF EXISTS {SCRATCH_TABLE}")
    execute(connection, f"DROP TABLE IF EXISTS {SCRATCH_TABLE}_vertices_pgr")
    store_tolerance_rows(connection, rows)
    return rows


def _tolerance_row(scenario: str, tolerance: float, method: str, stats: dict[str, int]) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "tolerance_deg": tolerance,
        "tolerance_m": round(tolerance * config.METERS_PER_DEGREE_LAT, 1),
        "method": method,
        "vertices": int(stats["vertices"]),
        "components": int(stats["components"]),
        "largest_component": int(stats["largest_component"]),
    }


def store_tolerance_rows(connection: Any, rows: list[dict[str, Any]]) -> None:
    execute(connection, "DROP TABLE IF EXISTS tolerance_comparison")
    execute(
        connection,
        "CREATE TABLE tolerance_comparison (scenario TEXT, tolerance_deg DOUBLE PRECISION, tolerance_m DOUBLE PRECISION, "
        "method TEXT, vertices INTEGER, components INTEGER, largest_component INTEGER)",
    )
    for row in rows:
        execute(
            connection,
            "INSERT INTO tolerance_comparison VALUES (%(scenario)s, %(tolerance_deg)s, %(tolerance_m)s, %(method)s, "
            "%(vertices)s, %(components)s, %(largest_component)s)",
            row,
        )


def topology_summary(connection: Any) -> dict[str, Any]:
    summary = fetch_one(
        connection,
        "SELECT (SELECT count(*) FROM network_edges) AS edges, "
        "(SELECT count(*) FROM network_vertices) AS vertices, "
        "(SELECT count(*) FROM network_edges WHERE source IS NULL OR target IS NULL) AS edges_without_topology, "
        "(SELECT count(*) FROM network_edges WHERE source = target) AS self_loops",
    )
    summary["components"] = {
        scenario: component_count(connection, "network_edges", layers)
        for scenario, layers in config.SCENARIO_LAYERS.items()
    }
    summary["analysis"] = {row["metric"]: row["value"] for row in fetch_all(connection, "SELECT metric, value FROM topology_analysis")}
    return summary
