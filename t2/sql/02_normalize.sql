DROP TABLE IF EXISTS network_edges CASCADE;

CREATE TABLE network_edges (
    edge_id BIGSERIAL PRIMARY KEY,
    source_layer TEXT NOT NULL,
    original_id TEXT NOT NULL,
    is_rapa_nui BOOLEAN NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    geom geometry(LineString, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,
    source BIGINT,
    target BIGINT,
    cost DOUBLE PRECISION,
    reverse_cost DOUBLE PRECISION
);

WITH raw_union AS (
    SELECT 'fiber' AS source_layer, original_id, gid, geom FROM raw_fiber
    UNION ALL SELECT 'power_poles', original_id, gid, geom FROM raw_poles_path
    UNION ALL SELECT 'road_no_poles', original_id, gid, geom FROM raw_roads_no_poles
    UNION ALL SELECT 'ferry', original_id, gid, geom FROM raw_ferry
),
dumped AS (
    SELECT source_layer, original_id, gid, (ST_Dump(ST_LineMerge(ST_Multi(geom)))).geom AS geom
    FROM raw_union
),
cleaned AS (
    SELECT source_layer, original_id, gid, ST_RemoveRepeatedPoints(geom) AS geom
    FROM dumped
    WHERE geom IS NOT NULL
      AND NOT ST_IsEmpty(geom)
      AND ST_IsValid(geom)
      AND GeometryType(geom) = 'LINESTRING'
),
fingerprinted AS (
    SELECT source_layer, original_id, gid, geom,
           LEAST(md5(ST_AsBinary(geom)), md5(ST_AsBinary(ST_Reverse(geom)))) AS fingerprint
    FROM cleaned
    WHERE ST_NPoints(geom) >= 2 AND ST_Length(geom::geography) > 0
),
deduplicated AS (
    SELECT DISTINCT ON (source_layer, fingerprint) source_layer, original_id, gid, geom
    FROM fingerprinted
    ORDER BY source_layer, fingerprint, gid
)
INSERT INTO network_edges (source_layer, original_id, is_rapa_nui, geom, length_m)
SELECT source_layer,
       original_id,
       FALSE,
       geom,
       ST_Length(geom::geography)
FROM deduplicated
ORDER BY source_layer, gid;

UPDATE network_edges SET cost = length_m, reverse_cost = length_m;

UPDATE network_edges SET is_synthetic = source_layer <> 'fiber';

CREATE INDEX network_edges_geom_idx ON network_edges USING GIST (geom);
CREATE INDEX network_edges_layer_idx ON network_edges (source_layer);

INSERT INTO load_log (stage, source_layer, segments, length_km)
SELECT 'normalized', source_layer, count(*), sum(length_m) / 1000.0
FROM network_edges
GROUP BY source_layer;
