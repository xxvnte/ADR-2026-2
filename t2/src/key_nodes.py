from __future__ import annotations

import json
import logging
import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src import config
from src.database import execute, fetch_all, run_sql_file

logger = logging.getLogger(__name__)

ROLE_PRIORITY = (config.ROLE_GENERATE, config.ROLE_EXCHANGE, config.ROLE_RECEIVE)
SOURCES_MANIFEST = config.EXTERNAL_DIR / "sources_manifest.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search?q=Hanga+Roa,+Isla+de+Pascua,+Chile&format=json&limit=1"
SOURCE_NOMINATIM = "OpenStreetMap Nominatim"

LICENSES_BY_PREFIX = {
    "landing_": "CC BY-SA 4.0 (TeleGeography)",
    "peeringdb_": "PeeringDB Acceptable Use Policy (datos públicos)",
    "natural_earth_": "Dominio público (Natural Earth)",
    "hanga_roa_": "ODbL 1.0 (OpenStreetMap)",
}


@dataclass
class Candidate:
    name: str
    lon: float
    lat: float
    roles: dict[str, tuple[str, str]] = field(default_factory=dict)
    is_rapa_nui: bool = False


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return stripped.strip().lower()


def _record_source(file_name: str, url: str) -> None:
    manifest = json.loads(SOURCES_MANIFEST.read_text(encoding="utf-8")) if SOURCES_MANIFEST.exists() else {}
    manifest[file_name] = {
        "url": url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "license": next((value for prefix, value in LICENSES_BY_PREFIX.items() if file_name.startswith(prefix)), "ver fuente"),
    }
    SOURCES_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def download_json(url: str, file_name: str) -> Any:
    path = config.EXTERNAL_DIR / file_name
    if not path.exists():
        config.EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": config.HTTP_USER_AGENT})
        response.raise_for_status()
        path.write_bytes(response.content)
        _record_source(file_name, url)
    return json.loads(path.read_text(encoding="utf-8"))


def haversine_m(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(lon_b - lon_a)
    chord = math.sin(delta_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    return 2 * config.EARTH_RADIUS_KM * config.METERS_PER_KM * math.asin(math.sqrt(chord))


def landing_candidates() -> list[Candidate]:
    collection = download_json(config.LANDING_POINTS_URL, "landing_points.json")
    candidates: list[Candidate] = []
    for feature in collection["features"]:
        properties = feature["properties"]
        if not properties["name"].endswith(f", {config.CHILE_NAME}"):
            continue
        detail = download_json(
            config.LANDING_POINT_DETAIL_URL.format(landing_id=properties["id"]),
            f"landing_{properties['id']}.json",
        )
        cables = sorted(cable["name"] for cable in detail.get("cables", []))
        international = sorted(
            cable["name"]
            for cable in detail.get("cables", [])
            if any(not landing.endswith(config.CHILE_LANDING_SUFFIX) for landing in cable.get("landing_points", []))
        )
        lon, lat = feature["geometry"]["coordinates"]
        city = properties["name"].rsplit(",", 1)[0]
        candidate = Candidate(f"Aterrizaje cable submarino {city}", lon, lat)
        cable_text = ", ".join(cables)
        if international:
            candidate.roles[config.ROLE_GENERATE] = (
                config.SOURCE_TELEGEOGRAPHY,
                f"Aterrizaje de cables internacionales ({', '.join(international)}): puerta de entrada de tráfico y contenido al país",
            )
        else:
            candidate.roles[config.ROLE_EXCHANGE] = (
                config.SOURCE_TELEGEOGRAPHY,
                f"Aterrizaje de cable submarino doméstico ({cable_text}): punto de traspaso entre troncal submarina y terrestre",
            )
        candidates.append(candidate)
    return candidates


def _facility_index() -> dict[int, dict[str, Any]]:
    facilities = download_json(config.PEERINGDB_FAC_URL, "peeringdb_fac.json")["data"]
    return {facility["id"]: facility for facility in facilities}


def _exchanges_by_facility() -> tuple[dict[int, list[str]], list[dict[str, Any]]]:
    exchanges = download_json(config.PEERINGDB_IX_URL, "peeringdb_ix.json")["data"]
    by_facility: dict[int, list[str]] = {}
    without_facility: list[dict[str, Any]] = []
    for exchange in exchanges:
        links = download_json(config.PEERINGDB_IXFAC_URL.format(ix_id=exchange["id"]), f"peeringdb_ixfac_{exchange['id']}.json")["data"]
        if not links:
            without_facility.append(exchange)
        for link in links:
            by_facility.setdefault(link["fac_id"], []).append(exchange["name"])
    return by_facility, without_facility


def facility_candidates() -> tuple[list[Candidate], list[dict[str, Any]]]:
    facilities = _facility_index()
    by_facility, without_facility = _exchanges_by_facility()
    candidates: list[Candidate] = []
    for facility_id, facility in facilities.items():
        if facility.get("latitude") is None or facility.get("longitude") is None:
            continue
        candidate = Candidate(facility["name"], float(facility["longitude"]), float(facility["latitude"]))
        networks = int(facility.get("net_count") or 0)
        if networks >= config.DATA_CENTER_MIN_NETWORKS:
            candidate.roles[config.ROLE_GENERATE] = (
                config.SOURCE_PEERINGDB,
                f"Data center con {networks} redes presentes (PeeringDB): aloja contenido/CDN que origina tráfico",
            )
        if facility_id in by_facility:
            candidate.roles[config.ROLE_EXCHANGE] = (
                config.SOURCE_PEERINGDB,
                f"Sede de punto de intercambio de tráfico: {', '.join(sorted(set(by_facility[facility_id])))}",
            )
        if candidate.roles:
            candidates.append(candidate)
    return candidates, without_facility


def city_candidates() -> list[Candidate]:
    places = download_json(config.NATURAL_EARTH_PLACES_URL, "natural_earth_places.geojson")
    wanted = {_normalize(name): name for name in config.RECEIVER_CITIES}
    found: dict[str, Candidate] = {}
    for feature in places["features"]:
        properties = feature["properties"]
        key = _normalize(properties["name"])
        if properties["iso_a2"] != config.CHILE_COUNTRY_CODE or key not in wanted or key in found:
            continue
        candidate = Candidate(wanted[key], float(properties["longitude"]), float(properties["latitude"]))
        candidate.roles[config.ROLE_RECEIVE] = (
            config.SOURCE_NATURAL_EARTH,
            f"Centro urbano de consumo final (población aprox. {int(properties['pop_max']):,} hab.)".replace(",", "."),
        )
        found[key] = candidate
    missing = sorted(set(wanted) - set(found))
    if missing:
        logger.warning("cities not found in natural earth: %s", missing)
    return list(found.values())


def rapa_nui_candidate() -> Candidate:
    result = download_json(NOMINATIM_URL, "hanga_roa_nominatim.json")[0]
    candidate = Candidate(config.RAPA_NUI_CITY, float(result["lon"]), float(result["lat"]), is_rapa_nui=True)
    candidate.roles[config.ROLE_RECEIVE] = (
        SOURCE_NOMINATIM,
        "Única localidad de Rapa Nui: consumo final aislado del continente (solo análisis de sensibilidad)",
    )
    return candidate


def attach_orphan_exchanges(cities: list[Candidate], exchanges: list[dict[str, Any]]) -> list[str]:
    by_city = {_normalize(city.name): city for city in cities}
    unattached: list[str] = []
    for exchange in exchanges:
        city = by_city.get(_normalize(exchange.get("city") or ""))
        if city is None:
            unattached.append(exchange["name"])
            continue
        existing = city.roles.get(config.ROLE_EXCHANGE)
        names = exchange["name"] if existing is None else f"{existing[1].split(': ', 1)[1]}, {exchange['name']}"
        city.roles[config.ROLE_EXCHANGE] = (config.SOURCE_PEERINGDB, f"Punto de intercambio sin sede georreferenciada, ubicado en la ciudad: {names}")
    return unattached


def merge_candidates(candidates: list[Candidate], radius_m: float) -> list[Candidate]:
    merged: list[Candidate] = []
    for candidate in candidates:
        target = next(
            (node for node in merged if haversine_m(node.lon, node.lat, candidate.lon, candidate.lat) <= radius_m),
            None,
        )
        if target is None:
            merged.append(Candidate(candidate.name, candidate.lon, candidate.lat, dict(candidate.roles), candidate.is_rapa_nui))
            continue
        target.name = f"{target.name} / {candidate.name}"
        for role, detail in candidate.roles.items():
            target.roles.setdefault(role, detail)
    return merged


def primary_role(roles: dict[str, tuple[str, str]]) -> str:
    return next(role for role in ROLE_PRIORITY if role in roles)


def collect_candidates() -> tuple[list[Candidate], list[str]]:
    cities = city_candidates()
    facilities, orphan_exchanges = facility_candidates()
    unattached = attach_orphan_exchanges(cities, orphan_exchanges)
    ordered = landing_candidates() + facilities + cities + [rapa_nui_candidate()]
    return merge_candidates(ordered, config.KEY_NODE_MERGE_RADIUS_M), unattached


def store_key_nodes(connection: Any, nodes: list[Candidate]) -> None:
    run_sql_file(connection, config.SQL_DIR / "04_key_nodes.sql")
    for node in nodes:
        role = primary_role(node.roles)
        source, justification = node.roles[role]
        execute(
            connection,
            "INSERT INTO key_nodes (name, role, source, justification, is_rapa_nui, geom) "
            "VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), %s)) RETURNING node_id",
            (node.name, role, source, justification, node.is_rapa_nui, node.lon, node.lat, config.SRID_WGS84),
        )
        for node_role, (role_source, role_justification) in node.roles.items():
            execute(
                connection,
                "INSERT INTO key_node_roles (node_id, role, source, justification) "
                "SELECT node_id, %s, %s, %s FROM key_nodes WHERE name = %s",
                (node_role, role_source, role_justification, node.name),
            )


def anchor_key_nodes(connection: Any) -> None:
    for scenario, layers in config.SCENARIO_LAYERS.items():
        execute(
            connection,
            "INSERT INTO key_node_anchors (node_id, scenario, vertex_id, distance_m, is_anchored) "
            "SELECT k.node_id, %(scenario)s, nearest.id, nearest.distance_m, nearest.distance_m <= %(threshold)s "
            "FROM key_nodes k CROSS JOIN LATERAL ("
            "  SELECT v.id, ST_Distance(v.the_geom::geography, k.geom::geography) AS distance_m "
            "  FROM network_vertices v "
            "  WHERE EXISTS (SELECT 1 FROM network_edges e WHERE (e.source = v.id OR e.target = v.id) "
            "                AND e.source_layer = ANY(%(layers)s)) "
            "  ORDER BY v.the_geom::geography <-> k.geom::geography LIMIT 1"
            ") nearest",
            {"scenario": scenario, "threshold": config.KEY_NODE_ANCHOR_MAX_DISTANCE_M, "layers": list(layers)},
        )
    execute(
        connection,
        "UPDATE key_nodes k SET vertex_id = CASE WHEN a.is_anchored THEN a.vertex_id END, anchor_distance_m = a.distance_m "
        "FROM key_node_anchors a WHERE a.node_id = k.node_id AND a.scenario = %s",
        (config.BASE_SCENARIO,),
    )


def build_key_nodes(connection: Any) -> dict[str, Any]:
    nodes, unattached = collect_candidates()
    store_key_nodes(connection, nodes)
    anchor_key_nodes(connection)
    return {"nodes": len(nodes), "unattached_exchanges": unattached, "by_role": role_counts(connection)}


def role_counts(connection: Any) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT r.role, count(*) AS nodes, count(*) FILTER (WHERE a.is_anchored) AS anchored "
        "FROM key_node_roles r JOIN key_nodes k USING (node_id) "
        "JOIN key_node_anchors a ON a.node_id = k.node_id AND a.scenario = %s "
        "WHERE NOT k.is_rapa_nui GROUP BY r.role ORDER BY r.role",
        (config.BASE_SCENARIO,),
    )


def key_node_table(connection: Any) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT k.node_id, k.name, k.role, string_agg(r.role, ',' ORDER BY r.role) AS roles, "
        "k.vertex_id, round(k.anchor_distance_m::numeric, 0) AS anchor_distance_m, k.is_rapa_nui, k.justification, "
        "ST_X(k.geom) AS lon, ST_Y(k.geom) AS lat "
        "FROM key_nodes k JOIN key_node_roles r USING (node_id) "
        "GROUP BY k.node_id ORDER BY k.node_id",
    )


def export_key_nodes(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
