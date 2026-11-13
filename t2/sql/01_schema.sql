CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

DROP TABLE IF EXISTS raw_fiber CASCADE;
DROP TABLE IF EXISTS raw_poles_path CASCADE;
DROP TABLE IF EXISTS raw_roads_no_poles CASCADE;
DROP TABLE IF EXISTS raw_ferry CASCADE;

CREATE TABLE raw_fiber (gid SERIAL PRIMARY KEY, original_id TEXT, geom geometry(Geometry, 4326));
CREATE TABLE raw_poles_path (gid SERIAL PRIMARY KEY, original_id TEXT, geom geometry(Geometry, 4326));
CREATE TABLE raw_roads_no_poles (gid SERIAL PRIMARY KEY, original_id TEXT, geom geometry(Geometry, 4326));
CREATE TABLE raw_ferry (gid SERIAL PRIMARY KEY, original_id TEXT, geom geometry(Geometry, 4326));

DROP TABLE IF EXISTS load_log CASCADE;
CREATE TABLE load_log (
    stage TEXT NOT NULL,
    source_layer TEXT NOT NULL,
    segments INTEGER NOT NULL,
    length_km DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (stage, source_layer)
);
