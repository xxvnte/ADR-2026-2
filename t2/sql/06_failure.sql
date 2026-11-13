DROP TABLE IF EXISTS edge_subsegments CASCADE;

CREATE TABLE edge_subsegments AS
WITH segmentized AS (
    SELECT e.edge_id,
           ST_Segmentize(e.geom::geography, %(step_m)s)::geometry AS geom
    FROM network_edges e
),
pieces AS (
    SELECT s.edge_id, (ST_DumpSegments(s.geom)).geom AS geom
    FROM segmentized s
)
SELECT p.edge_id,
       ST_Length(p.geom::geography) AS length_m,
       ST_X(ST_LineInterpolatePoint(p.geom, 0.5)) AS mid_lon,
       ST_Y(ST_LineInterpolatePoint(p.geom, 0.5)) AS mid_lat,
       ST_Distance(ST_LineInterpolatePoint(p.geom, 0.5)::geography, q.geom::geography) AS epicentral_distance_m
FROM pieces p
CROSS JOIN (SELECT geom FROM earthquake LIMIT 1) q;

CREATE INDEX edge_subsegments_edge_idx ON edge_subsegments (edge_id);

DROP TABLE IF EXISTS edge_failure_variants CASCADE;
CREATE TABLE edge_failure_variants (
    edge_id BIGINT NOT NULL REFERENCES network_edges (edge_id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    distance_km DOUBLE PRECISION NOT NULL,
    model_distance_km DOUBLE PRECISION,
    intensity DOUBLE PRECISION NOT NULL,
    repair_rate DOUBLE PRECISION NOT NULL,
    expected_repairs DOUBLE PRECISION NOT NULL,
    failure_probability DOUBLE PRECISION NOT NULL CHECK (failure_probability BETWEEN 0 AND 1),
    PRIMARY KEY (edge_id, variant)
);

DROP TABLE IF EXISTS edge_failure CASCADE;
CREATE TABLE edge_failure (
    edge_id BIGINT PRIMARY KEY REFERENCES network_edges (edge_id) ON DELETE CASCADE,
    distance_km DOUBLE PRECISION NOT NULL,
    intensity DOUBLE PRECISION NOT NULL,
    repair_rate DOUBLE PRECISION NOT NULL,
    expected_repairs DOUBLE PRECISION NOT NULL,
    failure_probability DOUBLE PRECISION NOT NULL CHECK (failure_probability BETWEEN 0 AND 1)
);
