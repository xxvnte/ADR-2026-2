from __future__ import annotations

import logging
from typing import Any, Iterable

import shapefile

from src import config
from src.database import execute, execute_many, fetch_all, run_sql_file

logger = logging.getLogger(__name__)


class ShapefileMissingError(FileNotFoundError):
    pass


def _linestring_wkt(points: Iterable[tuple[float, float]]) -> str:
    coordinates = ", ".join(f"{lon:.10f} {lat:.10f}" for lon, lat in points)
    return f"LINESTRING({coordinates})"


def _shape_to_wkts(shape: Any) -> list[str]:
    parts = list(shape.parts) + [len(shape.points)]
    return [
        _linestring_wkt(shape.points[start:end])
        for start, end in zip(parts[:-1], parts[1:])
        if end - start >= 2
    ]


def read_layer(layer: config.LayerSpec) -> list[tuple[str, str]]:
    path = config.SHAPEFILE_DIR / f"{layer.shapefile}.shp"
    if not path.exists():
        raise ShapefileMissingError(str(path))
    reader = shapefile.Reader(str(path), encoding=config.SHAPEFILE_ENCODING)
    rows: list[tuple[str, str]] = []
    for shape_record in reader.iterShapeRecords():
        original_id = str(shape_record.record["id"])
        rows.extend((original_id, wkt) for wkt in _shape_to_wkts(shape_record.shape))
    return rows


def load_raw_layer(connection: Any, layer: config.LayerSpec) -> int:
    rows = read_layer(layer)
    execute_many(
        connection,
        f"INSERT INTO {layer.raw_table} (original_id, geom) VALUES %s",
        rows,
        page_size=config.INSERT_BATCH_SIZE,
        template=_insert_template(),
    )
    execute(
        connection,
        "INSERT INTO load_log (stage, source_layer, segments, length_km) "
        f"SELECT 'raw', %s, count(*), coalesce(sum(ST_Length(geom::geography)), 0) / %s FROM {layer.raw_table}",
        (layer.source_layer, config.METERS_PER_KM),
    )
    logger.info("loaded %s rows into %s", len(rows), layer.raw_table)
    return len(rows)


def _insert_template() -> str:
    return f"(%s, ST_GeomFromText(%s, {config.SRID_WGS84}))"


def load_all(connection: Any) -> list[dict[str, Any]]:
    run_sql_file(connection, config.SQL_DIR / "01_schema.sql")
    for layer in config.LAYERS:
        load_raw_layer(connection, layer)
    run_sql_file(connection, config.SQL_DIR / "02_normalize.sql")
    execute(
        connection,
        "UPDATE network_edges SET is_rapa_nui = ST_XMax(geom) < %s",
        (config.RAPA_NUI_MAX_LONGITUDE,),
    )
    return layer_summary(connection)


def layer_summary(connection: Any) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT r.source_layer, r.segments AS raw_segments, round(r.length_km::numeric, 1) AS raw_km, "
        "n.segments AS clean_segments, round(n.length_km::numeric, 1) AS clean_km "
        "FROM load_log r JOIN load_log n ON n.source_layer = r.source_layer AND n.stage = 'normalized' "
        "WHERE r.stage = 'raw' ORDER BY r.source_layer",
    )
