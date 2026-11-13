UPDATE network_edges SET source = NULL, target = NULL;

DROP TABLE IF EXISTS network_edges_vertices_pgr CASCADE;

SELECT pgr_createTopology('network_edges', %(tolerance)s, 'geom', 'edge_id', 'source', 'target', clean := true);

CREATE INDEX IF NOT EXISTS network_edges_source_idx ON network_edges (source);
CREATE INDEX IF NOT EXISTS network_edges_target_idx ON network_edges (target);

SELECT pgr_analyzeGraph('network_edges', %(tolerance)s, 'geom', 'edge_id', 'source', 'target');

DROP TABLE IF EXISTS network_vertices CASCADE;

CREATE TABLE network_vertices AS
WITH incidence AS (
    SELECT source AS vertex_id, source_layer FROM network_edges
    UNION ALL
    SELECT target, source_layer FROM network_edges
)
SELECT v.id,
       v.the_geom,
       v.cnt AS analyze_count,
       v.chk AS analyze_check,
       count(i.vertex_id) AS degree,
       count(i.vertex_id) FILTER (WHERE i.source_layer = 'fiber') AS degree_fiber,
       ST_X(v.the_geom) < %(rapa_nui_lon)s AS is_rapa_nui
FROM network_edges_vertices_pgr v
LEFT JOIN incidence i ON i.vertex_id = v.id
GROUP BY v.id, v.the_geom, v.cnt, v.chk;

ALTER TABLE network_vertices ADD PRIMARY KEY (id);
CREATE INDEX network_vertices_geom_idx ON network_vertices USING GIST (the_geom);
CREATE INDEX network_vertices_geog_idx ON network_vertices USING GIST ((the_geom::geography));
