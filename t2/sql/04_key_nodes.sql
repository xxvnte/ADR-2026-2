DROP TABLE IF EXISTS key_node_anchors CASCADE;
DROP TABLE IF EXISTS key_node_roles CASCADE;
DROP TABLE IF EXISTS key_nodes CASCADE;

CREATE TABLE key_nodes (
    node_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('generate', 'exchange', 'receive')),
    source TEXT NOT NULL,
    justification TEXT NOT NULL,
    is_rapa_nui BOOLEAN NOT NULL DEFAULT FALSE,
    geom geometry(Point, 4326) NOT NULL,
    vertex_id BIGINT,
    anchor_distance_m DOUBLE PRECISION
);

CREATE TABLE key_node_roles (
    node_id INTEGER NOT NULL REFERENCES key_nodes (node_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('generate', 'exchange', 'receive')),
    source TEXT NOT NULL,
    justification TEXT NOT NULL,
    PRIMARY KEY (node_id, role)
);

CREATE TABLE key_node_anchors (
    node_id INTEGER NOT NULL REFERENCES key_nodes (node_id) ON DELETE CASCADE,
    scenario TEXT NOT NULL,
    vertex_id BIGINT NOT NULL,
    distance_m DOUBLE PRECISION NOT NULL,
    is_anchored BOOLEAN NOT NULL,
    PRIMARY KEY (node_id, scenario)
);

CREATE INDEX key_nodes_geom_idx ON key_nodes USING GIST (geom);
