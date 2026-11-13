from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src import config
from src.database import execute, fetch_one

logger = logging.getLogger(__name__)

SHAKEMAP_PRODUCT = "shakemap"
GRID_CONTENT = "download/grid.xml"
RUPTURE_CONTENT = "download/rupture.json"
MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True)
class Epicenter:
    event_id: str
    magnitude: float
    lon: float
    lat: float
    depth_km: float
    event_time: datetime
    place: str


class EarthquakeValidationError(ValueError):
    pass


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": config.HTTP_USER_AGENT})
    response.raise_for_status()
    path.write_bytes(response.content)
    logger.info("downloaded %s", url)


def _record_download(name: str, url: str) -> None:
    manifest_path = config.EXTERNAL_DIR / "sources_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest[name] = {
        "url": url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "license": "Dominio público (USGS)",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def download_event() -> dict[str, Any]:
    if not config.EARTHQUAKE_GEOJSON_PATH.exists():
        _download(config.USGS_EVENT_URL, config.EARTHQUAKE_GEOJSON_PATH)
        _record_download(config.EARTHQUAKE_GEOJSON_PATH.name, config.USGS_EVENT_URL)
    return json.loads(config.EARTHQUAKE_GEOJSON_PATH.read_text(encoding="utf-8"))


def shakemap_urls(feature: dict[str, Any]) -> dict[str, str]:
    product = feature["properties"]["products"][SHAKEMAP_PRODUCT][0]
    contents = product["contents"]
    return {"grid": contents[GRID_CONTENT]["url"], "rupture": contents[RUPTURE_CONTENT]["url"]}


def download_shakemap(feature: dict[str, Any]) -> None:
    urls = shakemap_urls(feature)
    for key, path in (("grid", config.SHAKEMAP_GRID_PATH), ("rupture", config.RUPTURE_PATH)):
        if not path.exists():
            _download(urls[key], path)
            _record_download(path.name, urls[key])


def parse_epicenter(feature: dict[str, Any]) -> Epicenter:
    lon, lat, depth = feature["geometry"]["coordinates"]
    properties = feature["properties"]
    return Epicenter(
        event_id=feature["id"],
        magnitude=float(properties["mag"]),
        lon=float(lon),
        lat=float(lat),
        depth_km=float(depth),
        event_time=datetime.fromtimestamp(properties["time"] / MILLISECONDS_PER_SECOND, tz=timezone.utc),
        place=str(properties["place"]),
    )


def validate(epicenter: Epicenter) -> list[str]:
    problems: list[str] = []
    if abs(epicenter.magnitude - config.EXPECTED_MAGNITUDE) > config.MAGNITUDE_TOLERANCE:
        problems.append(f"magnitud {epicenter.magnitude} distinta de {config.EXPECTED_MAGNITUDE}")
    min_lon, min_lat, max_lon, max_lat = config.CHILE_BBOX
    if not (min_lon <= epicenter.lon <= max_lon and min_lat <= epicenter.lat <= max_lat):
        problems.append("epicentro fuera del recuadro de Chile")
    min_depth, max_depth = config.DEPTH_RANGE_KM
    if not (min_depth <= epicenter.depth_km <= max_depth):
        problems.append(f"profundidad {epicenter.depth_km} km fuera del rango esperado")
    return problems


def store_event(connection: Any, feature: dict[str, Any], epicenter: Epicenter) -> None:
    properties = {key: value for key, value in feature["properties"].items() if key != "products"}
    properties["product_types"] = sorted(feature["properties"].get("products", {}).keys())
    execute(connection, (config.SQL_DIR / "05_earthquake.sql").read_text(encoding="utf-8"))
    execute(
        connection,
        "INSERT INTO earthquake (event_id, magnitude, place, event_time, depth_km, geom, raw_properties) "
        "VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), %s), %s::jsonb)",
        (
            epicenter.event_id,
            epicenter.magnitude,
            epicenter.place,
            epicenter.event_time,
            epicenter.depth_km,
            epicenter.lon,
            epicenter.lat,
            config.SRID_WGS84,
            json.dumps(properties),
        ),
    )


def load_earthquake(connection: Any) -> Epicenter:
    feature = download_event()
    download_shakemap(feature)
    epicenter = parse_epicenter(feature)
    problems = validate(epicenter)
    if problems:
        raise EarthquakeValidationError("; ".join(problems))
    store_event(connection, feature, epicenter)
    return epicenter


def read_epicenter(connection: Any) -> Epicenter:
    row = fetch_one(
        connection,
        "SELECT event_id, magnitude, ST_X(geom) AS lon, ST_Y(geom) AS lat, depth_km, event_time, place FROM earthquake LIMIT 1",
    )
    if not row:
        raise EarthquakeValidationError("la tabla earthquake está vacía")
    return Epicenter(**row)
