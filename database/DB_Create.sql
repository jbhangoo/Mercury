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
-- xrs table for MESSENGER XRS CDR observations.
-- Positions are plain latitude/longitude numbers on a sphere (Mercury's radius,
-- 2439.4 km); the table needs no PostGIS types, and PostGIS geography/WGS84
-- functions would give wrong distances here because they assume Earth.

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
    -- 32-bit flag word. Only bit 0 is defined: 1 = the data length in the packet
    -- did not match the length the instrument reported. Search with
    -- (data_quality & 1) = 0 rather than data_quality = 0.
    data_quality bigint   NOT NULL,

    -- Where the instrument was pointing: the boresight's intercept with the
    -- surface, from the CDR's Mercury-fixed vector. Degrees, east longitude in
    -- -180..180. NULL (both) when the boresight misses the planet.
    boresight_lat double precision CHECK (boresight_lat BETWEEN -90 AND 90),
    boresight_lon double precision CHECK (boresight_lon BETWEEN -180 AND 180),
    CHECK ((boresight_lat IS NULL) = (boresight_lon IS NULL)),

    -- Radius in km of the circle around the boresight point that lies inside the
    -- observation's footprint: the distance to the nearest perimeter vertex of
    -- the PDS RDR footprint. NULL until the footprint is loaded, and when the
    -- footprint cannot be used (no boresight point, or the point is not inside
    -- the footprint). Observations without it are not found by spatial searches.
    footprint_radius_km real CHECK (footprint_radius_km > 0),
    CHECK (footprint_radius_km IS NULL OR boresight_lat IS NOT NULL),

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

CREATE INDEX xrs_observed_start_idx  ON xrs (observed_start);
CREATE INDEX xrs_met_idx             ON xrs (met);
CREATE INDEX xrs_flare_idx           ON xrs (observed_start) WHERE solar_flare_detected;
CREATE INDEX xrs_solar_intensity_idx ON xrs (solar_intensity) WHERE solar_intensity IS NOT NULL;

COMMIT;

-- Assign xrs table ownership to the mercury role
ALTER TABLE xrs OWNER TO mercury;

-- Searching around a point (see server/app/db/access.py): an observation overlaps a
-- circle of interest (lon, lat, radius) when the great-circle distance from its
-- boresight point to the center is at most footprint_radius_km + the circle's
-- radius. No spatial index is needed: a scan of 350,000 rows takes tens of ms.