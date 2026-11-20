from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from src import config
from src.database import connect, execute, fetch_scalar

logger = logging.getLogger(__name__)

EXPORT_TABLE = "edge_failure_probability"
VERIFY_DATABASE = "main_sql_verification"
GEOMETRY_DECIMALS = 7
CONTAINER_WORKSPACE = "/workspace"

HEADER = f"""CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS {EXPORT_TABLE};

CREATE TABLE {EXPORT_TABLE} (
    edge_id BIGINT PRIMARY KEY,
    source BIGINT NOT NULL,
    target BIGINT NOT NULL,
    source_layer TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,
    epicentral_distance_km DOUBLE PRECISION NOT NULL,
    pgv_cm_s DOUBLE PRECISION NOT NULL,
    repair_rate_per_km DOUBLE PRECISION NOT NULL,
    failure_probability DOUBLE PRECISION NOT NULL CHECK (failure_probability BETWEEN 0 AND 1),
    model_variant TEXT NOT NULL,
    geom geometry(LineString, 4326) NOT NULL
);

BEGIN;
"""

FOOTER = f"""COMMIT;

CREATE INDEX {EXPORT_TABLE}_geom_idx ON {EXPORT_TABLE} USING GIST (geom);
CREATE INDEX {EXPORT_TABLE}_probability_idx ON {EXPORT_TABLE} (failure_probability);
"""

INSERT_QUERY = f"""
SELECT format(
    'INSERT INTO {EXPORT_TABLE} VALUES (%s, %s, %s, %L, %L, %s, %s, %s, %s, %s, %L, ST_GeomFromEWKT(%L));',
    e.edge_id, e.source, e.target, e.source_layer, e.is_synthetic,
    round(e.length_m::numeric, 3), round(f.distance_km::numeric, 4), round(f.intensity::numeric, 4),
    f.repair_rate, e.failure_probability, '{{variant}}',
    ST_AsEWKT(e.geom, {GEOMETRY_DECIMALS})
) AS statement
FROM network_edges e
JOIN edge_failure f USING (edge_id)
ORDER BY e.edge_id
"""


def build_statements(connection: Any) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(INSERT_QUERY.replace("{variant}", config.VARIANT_PRIMARY))
        return [row[0] for row in cursor.fetchall()]


def export_main_sql(connection: Any, path: Path = config.MAIN_SQL_PATH) -> dict[str, Any]:
    statements = build_statements(connection)
    path.write_text(HEADER + "\n".join(statements) + "\n" + FOOTER, encoding="utf-8", newline="\n")
    edges = int(fetch_scalar(connection, "SELECT count(*) FROM network_edges"))
    return {"path": str(path), "inserts": len(statements), "edges": edges, "bytes": path.stat().st_size}


def verify_in_clean_database(path: Path = config.MAIN_SQL_PATH) -> dict[str, Any]:
    settings = config.database_settings()
    admin = connect(dbname="postgres")
    try:
        execute(admin, f"DROP DATABASE IF EXISTS {VERIFY_DATABASE}")
        execute(admin, f"CREATE DATABASE {VERIFY_DATABASE}")
    finally:
        admin.close()
    relative = path.relative_to(config.PROJECT_ROOT).as_posix()
    completed = subprocess.run(
        [
            "docker", "exec", settings.container, "psql", "-U", settings.user, "-d", VERIFY_DATABASE,
            "-v", "ON_ERROR_STOP=1", "-q", "-f", f"{CONTAINER_WORKSPACE}/{relative}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    verification = connect(dbname=VERIFY_DATABASE)
    try:
        rows = fetch_scalar(verification, f"SELECT count(*) FROM {EXPORT_TABLE}") if completed.returncode == 0 else None
    finally:
        verification.close()
    return {"returncode": completed.returncode, "rows": rows, "stderr": completed.stderr.strip()}
