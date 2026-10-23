-- Migrate an existing geometry-based xrs table to the boresight/radius schema.
-- Back up the database before running: this clears spatial data and drops the
-- old geometry columns, but preserves all observation rows and other columns.
-- Execute from psql as an administrator. Results are not guaranteed for a
-- generic SQL processor.

\set ON_ERROR_STOP on
\c mercury

BEGIN;

DROP INDEX IF EXISTS xrs_footprint_gist_idx;
DROP INDEX IF EXISTS xrs_center_gist_idx;

ALTER TABLE xrs
    ADD COLUMN boresight_lat double precision CHECK (boresight_lat BETWEEN -90 AND 90),
    ADD COLUMN boresight_lon double precision CHECK (boresight_lon BETWEEN -180 AND 180),
    ADD COLUMN footprint_radius_km real CHECK (footprint_radius_km > 0),
    ADD CONSTRAINT xrs_boresight_point_pair_check
        CHECK ((boresight_lat IS NULL) = (boresight_lon IS NULL)),
    ADD CONSTRAINT xrs_footprint_radius_requires_boresight_check
        CHECK (footprint_radius_km IS NULL OR boresight_lat IS NOT NULL);

-- Existing observations have no radius in the revised representation.
UPDATE xrs
SET center = NULL,
    footprint = NULL,
    boresight_lat = NULL,
    boresight_lon = NULL,
    footprint_radius_km = NULL;

ALTER TABLE xrs
    DROP COLUMN center_lon,
    DROP COLUMN center_lat,
    DROP COLUMN center,
    DROP COLUMN footprint;

COMMIT;
