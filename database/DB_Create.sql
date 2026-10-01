-- Execute from psql while connected as an administrator (for example, to the
-- postgres database).
-- Assumes psql. Results not guaranteed for a generic SQL processor!
--

\set ON_ERROR_STOP on

-- PostgreSQL has no CREATE USER IF NOT EXISTS syntax.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mercury') THEN
        CREATE ROLE mercury LOGIN PASSWORD 'Mer33cury##';
    END IF;
END
$$;

-- CREATE DATABASE cannot run inside a transaction, so generate it for psql.
SELECT 'CREATE DATABASE mercury OWNER mercury'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mercury')\gexec

\c mercury

CREATE EXTENSION IF NOT EXISTS postgis;

-- Put these settings in server/.env, not in this SQL script:
-- USE_DATABASE=1
-- DATABASE_URL=postgresql+psycopg://mercury_user:Merc33Ury##@localhost:5432/mercury_gis

-- XRS Records Table
BEGIN; -- Create the xrs table and indexes in a transaction to ensure atomicity.
CREATE TABLE xrs (
    id bigserial PRIMARY KEY,
    observed_at timestamptz UNIQUE NOT NULL,

    source_file text,
    source_id text,

    energy double precision, -- Energy in keV
    solar_intensity double precision, -- Solar intensity in W/m^2
    uncertainty double precision,

    latitude double precision,
    longitude double precision,
    altitude double precision,  -- In km

    h3_id text,
    location geometry(Point, 4326),

    processing_version text NOT NULL DEFAULT 'initial',
    raw_data jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX xrs_observed_at_idx ON xrs (observed_at);

CREATE INDEX xrs_h3_id ON xrs (h3_id);

CREATE INDEX xrs_location_gist_idx ON xrs USING gist (location);

CREATE INDEX xrs_source_idx ON xrs (source_file, source_id);

CREATE INDEX xrs_location_geography_idx ON xrs USING gist ((location::geography));

COMMIT; -- End of transaction for xrs table creation.
