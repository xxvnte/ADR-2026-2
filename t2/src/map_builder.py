from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import config
from src.database import fetch_all
from src.earthquake import Epicenter

LAYER_LABELS = {
    "fiber": "Fibra óptica",
    "power_poles": "Postación eléctrica",
    "road_no_poles": "Camino sin postación",
    "ferry": "Trayecto en ferry",
}
LAYER_COLORS = {"fiber": "#2a78d6", "power_poles": "#eb6834", "road_no_poles": "#1baf7a", "ferry": "#eda100"}
LAYER_WEIGHTS = {"fiber": 2.5, "power_poles": 1.5, "road_no_poles": 1.5, "ferry": 1.5}
ROLE_LABELS = {"generate": "Genera", "exchange": "Intercambia", "receive": "Recibe"}
ROLE_COLORS = {"generate": "#6250d6", "exchange": "#008300", "receive": "#0b0b0b"}
DAMAGE_COLORS = ("#f6c1bd", "#ee8a84", "#d23b3a", "#7a1514")
PROBABILITY_CEILING = 1.0


def _decimal(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def damage_bins() -> list[dict[str, Any]]:
    edges = (0.0, *config.PROBABILITY_BINS, PROBABILITY_CEILING)
    bins = [
        {"min": low, "max": high, "color": color, "label": f"{_decimal(low)} – {_decimal(high)}"}
        for low, high, color in zip(edges[:-2], edges[1:-1], DAMAGE_COLORS)
    ]
    last = edges[-2]
    bins.append({"min": last, "max": None, "color": DAMAGE_COLORS[-1], "label": f"> {_decimal(last)}"})
    return bins
VARIANT_LABELS = {
    config.VARIANT_PRIMARY: "Kanno + distancia hipocentral, dúctil (principal)",
    config.VARIANT_RUPTURE: "Kanno + distancia a la ruptura, dúctil",
    config.VARIANT_SHAKEMAP: "ShakeMap USGS, dúctil",
    config.VARIANT_BRITTLE: "Kanno + distancia hipocentral, frágil",
}
COORDINATE_DECIMALS = 5
TEMPLATE_PATH = Path(__file__).resolve().parent / "map_template.html"


def link_features(connection: Any) -> dict[str, Any]:
    rows = fetch_all(
        connection,
        "SELECT e.edge_id, e.source_layer, e.length_m, f.failure_probability, f.intensity, f.distance_km, "
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(e.geom, %s), %s) AS geometry "
        "FROM network_edges e JOIN edge_failure f USING (edge_id) ORDER BY e.edge_id",
        (config.MAP_SIMPLIFY_TOLERANCE_DEG, COORDINATE_DECIMALS),
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row["geometry"]),
                "properties": {
                    "id": row["edge_id"],
                    "layer": row["source_layer"],
                    "km": round(row["length_m"] / config.METERS_PER_KM, config.DISPLAY_DECIMALS_KM),
                    "p": round(row["failure_probability"], config.DISPLAY_DECIMALS_PROBABILITY),
                    "pgv": round(row["intensity"], config.DISPLAY_DECIMALS_INTENSITY),
                    "d": round(row["distance_km"], config.DISPLAY_DECIMALS_INTENSITY),
                },
            }
            for row in rows
        ],
    }


def node_features(connection: Any, impact: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_node = {row["node_id"]: row for row in impact}
    rows = fetch_all(
        connection,
        "SELECT k.node_id, k.name, k.role, k.justification, k.is_rapa_nui, k.vertex_id, k.anchor_distance_m, "
        "ST_X(k.geom) AS lon, ST_Y(k.geom) AS lat, array_agg(r.role ORDER BY r.role) AS roles "
        "FROM key_nodes k JOIN key_node_roles r USING (node_id) GROUP BY k.node_id ORDER BY k.node_id",
    )
    return [
        {
            "id": row["node_id"],
            "name": row["name"],
            "role": row["role"],
            "roles": [ROLE_LABELS[role] for role in row["roles"]],
            "why": row["justification"],
            "anchored": row["vertex_id"] is not None,
            "anchor_m": round(row["anchor_distance_m"] or 0.0),
            "rapa_nui": row["is_rapa_nui"],
            "lat": row["lat"],
            "lon": row["lon"],
            "loss": round(by_node[row["node_id"]]["partner_loss_probability"], config.DISPLAY_DECIMALS_IMPACT) if row["node_id"] in by_node else None,
            "partners_before": by_node[row["node_id"]]["baseline_partners"] if row["node_id"] in by_node else None,
            "partners_after": round(by_node[row["node_id"]]["expected_partners_after"], config.DISPLAY_DECIMALS_KM) if row["node_id"] in by_node else None,
        }
        for row in rows
    ]


def attr_panel(report: dict[str, Any]) -> dict[str, Any]:
    operational = {(row["scenario"], row["scope"]): row for row in report["operational"]}
    base = operational[(config.BASE_SCENARIO, "continental")]
    post = [row for row in report["post_earthquake"] if row["scenario"] == config.BASE_SCENARIO]
    primary = next(row for row in post if row["variant"] == config.VARIANT_PRIMARY)
    all_layers_post = next(row for row in report["post_earthquake"] if row["scenario"] == config.ALL_LAYERS_SCENARIO)
    return {
        "before": base["attr"],
        "n": base["n"],
        "pairs": base["total_pairs"],
        "connected": base["connected_pairs"],
        "after": primary["attr_after"],
        "std": primary["std"],
        "ci": primary["ci95"],
        "p5": primary["percentiles"]["5"],
        "p95": primary["percentiles"]["95"],
        "runs": primary["runs"],
        "relative_loss": primary["relative_loss"],
        "deterministic": report["deterministic"]["attr_after"],
        "deterministic_threshold": report["deterministic"]["threshold"],
        "all_layers_before": operational[(config.ALL_LAYERS_SCENARIO, "continental")]["attr"],
        "all_layers_after": all_layers_post["attr_after"],
        "variants": [{"label": VARIANT_LABELS[row["variant"]], "after": row["attr_after"]} for row in post],
    }


def map_payload(connection: Any, report: dict[str, Any], epicenter: Epicenter) -> dict[str, Any]:
    return {
        "links": link_features(connection),
        "nodes": node_features(connection, report.get("node_impact", [])),
        "epicenter": {
            "lat": epicenter.lat,
            "lon": epicenter.lon,
            "magnitude": epicenter.magnitude,
            "depth": epicenter.depth_km,
            "date": epicenter.event_time.strftime("%d-%m-%Y %H:%M UTC"),
            "url": config.USGS_EVENT_PAGE,
        },
        "rings": list(config.DISTANCE_RINGS_KM),
        "attr": attr_panel(report),
        "layerLabels": LAYER_LABELS,
        "layerColors": LAYER_COLORS,
        "layerWeights": LAYER_WEIGHTS,
        "roleLabels": ROLE_LABELS,
        "roleColors": ROLE_COLORS,
        "damageBins": damage_bins(),
        "center": list(config.MAP_CENTER),
        "zoom": config.MAP_ZOOM,
        "kmPerDegreeLat": config.METERS_PER_DEGREE_LAT / config.METERS_PER_KM,
    }


def build_map(connection: Any, report: dict[str, Any], epicenter: Epicenter, path: Path = config.MAP_PATH) -> dict[str, Any]:
    payload = json.dumps(map_payload(connection, report, epicenter), ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("__LEAFLET_VERSION__", config.LEAFLET_VERSION).replace("__MAP_DATA__", payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return {"path": str(path), "bytes": path.stat().st_size}
