CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS xrs (
    id bigserial PRIMARY KEY,
    observed_at timestamptz UNIQUE NOT NULL,
    source_file text,
    source_id text,
    energy double precision,
    solar_intensity double precision,
    uncertainty double precision,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    h3_id text,
    location geometry(Point, 4326),
    processing_version text NOT NULL DEFAULT 'initial',
    raw_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS xrs_observed_at_idx ON xrs (observed_at);
CREATE INDEX IF NOT EXISTS xrs_h3_id ON xrs (h3_id);
CREATE INDEX IF NOT EXISTS xrs_location_gist_idx ON xrs USING gist (location);
CREATE INDEX IF NOT EXISTS xrs_source_idx ON xrs (source_file, source_id);
CREATE INDEX IF NOT EXISTS xrs_location_geography_idx
    ON xrs USING gist ((location::geography));