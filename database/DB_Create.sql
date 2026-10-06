-- Execute from psql while connected as an administrator (for example, to the
-- postgres database).
-- Assumes psql. Results not guaranteed for a generic SQL processor!
--

\set ON_ERROR_STOP on

-- PostgreSQL has no CREATE USER IF NOT EXISTS syntax.
-- DEVELOPMENT DEFAULTS!
-- Change this password before using the database
-- anywhere other than a local dev machine, and update DATABASE_URL in
-- server/.env to match.
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

-- Put settings in server/.env, not in this SQL script!
-- These are default values for development; change them for production!
-- USE_DATABASE=1
-- DATABASE_URL=postgresql+psycopg://mercury_user:Merc33Ury##@localhost:5432/mercury_gis

-- XRS --
-- xrs table for MESSENGER XRS CDR observations (replaces the earlier draft).
-- Assumes psql and the postgis extension.

-- Mercury is not Earth: geography/WGS84 casts give wrong distances and areas.
-- Register a spherical Mercury lon/lat CRS (IAU radius 2439.4 km) and use it
-- for every geometry. Any unused SRID <= 998999 works; 910001 is arbitrary.
INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text)
VALUES (
    910001, 'LOCAL', 910001,
    'GEOGCS["Mercury (sphere)",DATUM["Mercury_sphere",SPHEROID["Mercury_sphere",2439400,0]],PRIMEM["Reference Meridian",0],UNIT["degree",0.0174532925199433]]',
    '+proj=longlat +a=2439400 +b=2439400 +no_defs'
)
ON CONFLICT (srid) DO NOTHING;

BEGIN;

CREATE TABLE xrs (
    id bigserial PRIMARY KEY,

    -- Provenance. For CDR rows source_file is the day file (xrscdr2013101.dat)
    -- and source_id is the MET as text: the CDR SIS recommends the spacecraft
    -- clock as the key that ties footprints to CDR records.
    source_file text NOT NULL,
    source_id   text NOT NULL,
    UNIQUE (source_file, source_id),

    -- Spacecraft clock seconds. The CDR does not carry the clock partition;
    -- fill sclk_partition from footprint file names (xrs_fp_<P>_<MET>).
    met            bigint NOT NULL,
    sclk_partition smallint,
    orbit_number   integer NOT NULL,       -- 0 before Mercury orbit insertion

    -- Integration interval, UTC. observed_start comes from the CDR's UTC
    -- column and observed_end = start + actual integration time. That treats
    -- the CDR time tag as the integration start; confirm against a footprint
    -- label's START_TIME/STOP_TIME.
    observed_start timestamptz NOT NULL,
    observed_end   timestamptz NOT NULL,
    CHECK (observed_end >= observed_start),

    -- 0 FOV entirely off planet; 1 on planet and at least partly lit;
    -- 2 on planet and dark; 3 partly off planet, lit; 4 partly off planet, dark.
    fov_status   smallint NOT NULL CHECK (fov_status BETWEEN 0 AND 4),
    intersection boolean  NOT NULL,        -- boresight hits the planet
    data_quality bigint   NOT NULL,        -- 32-bit flag word; 0 = nothing flagged

    -- center = boresight intercept (from the CDR's Mercury-fixed vector).
    -- footprint = FOV outline, loaded later from the PDS footprints (or SPICE).
    -- Split footprints at +/-180 lon; extend ones enclosing a pole to +/-90.
    center     geometry(Point, 910001),
    center_lon double precision GENERATED ALWAYS AS (ST_X(center)) STORED,
    center_lat double precision GENERATED ALWAYS AS (ST_Y(center)) STORED,
    footprint  geometry(MultiPolygon, 910001),
    spacecraft_altitude_km real,           -- SCALT, sub-spacecraft point

    -- The instrument's own solar monitor (not a flux in W/m^2).
    solar_flare_detected      boolean NOT NULL,
    solar_monitor_rate        bigint,      -- counts per integration period
    solar_monitor_spect_shift smallint,    -- right-shift applied to solar_mon_spectrum

    -- Optional external solar flux (W/m^2); NULL unless loaded from another
    -- source. Note the source/band and any scaling from Earth to Mercury.
    solar_intensity        double precision,
    solar_intensity_source text,

    -- Counts per channel. GPC channels 10-253 (244), solar monitor 23-253 (231).
    -- Energy axis: keV = gain * channel + zero (gains/zeros are in housekeeping).
    gpc1_mg_spectrum integer[] CHECK (cardinality(gpc1_mg_spectrum) = 244),
    gpc2_al_spectrum integer[] CHECK (cardinality(gpc2_al_spectrum) = 244),
    gpc3_un_spectrum integer[] CHECK (cardinality(gpc3_un_spectrum) = 244),
    solar_mon_spectrum integer[] CHECK (cardinality(solar_mon_spectrum) = 231),

    -- Every other CDR column (live times, gains, voltages, angles, areas, ...),
    -- keyed by lower-case column name, so source files can be discarded.
    -- e.g.  housekeeping->>'gpc1_mg_live_time'
    housekeeping jsonb NOT NULL DEFAULT '{}'::jsonb,

    geometry_source    text NOT NULL DEFAULT 'pds-cdr-boresight',
    processing_version text NOT NULL DEFAULT 'initial',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX xrs_footprint_gist_idx  ON xrs USING gist (footprint);
CREATE INDEX xrs_center_gist_idx     ON xrs USING gist (center);
CREATE INDEX xrs_observed_start_idx  ON xrs (observed_start);
CREATE INDEX xrs_met_idx             ON xrs (met);
CREATE INDEX xrs_flare_idx           ON xrs (observed_start) WHERE solar_flare_detected;
CREATE INDEX xrs_solar_intensity_idx ON xrs (solar_intensity) WHERE solar_intensity IS NOT NULL;

COMMIT;

-- Assign xrs table ownership to the mercury role
ALTER TABLE xrs OWNER TO mercury;

-- Typical query: flare observations overlapping a user-drawn region.
--   SELECT id, observed_start, center_lon, center_lat
--   FROM xrs
--   WHERE solar_flare_detected
--     AND footprint && ST_SetSRID(ST_GeomFromGeoJSON(:region), 910001)
--     AND ST_Intersects(footprint, ST_SetSRID(ST_GeomFromGeoJSON(:region), 910001));