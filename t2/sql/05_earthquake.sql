DROP TABLE IF EXISTS earthquake CASCADE;

CREATE TABLE earthquake (
    event_id TEXT PRIMARY KEY,
    magnitude DOUBLE PRECISION NOT NULL,
    place TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    depth_km DOUBLE PRECISION NOT NULL,
    geom geometry(Point, 4326) NOT NULL,
    raw_properties JSONB NOT NULL
);
