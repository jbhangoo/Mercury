-- Execute from psql as an administrator.
-- This removes application tables and indexes, but keeps the mercury database,
-- mercury role, and PostGIS extension.
-- Assumes psql. Results not guaranteed for a generic SQL processor!

\set ON_ERROR_STOP on
\c mercury

-- Drop the explicit indexes created in DB_Create.sql.
DROP INDEX IF EXISTS xrs_footprint_gist_idx  ;
DROP INDEX IF EXISTS xrs_center_gist_idx  ;
DROP INDEX IF EXISTS xrs_observed_start_idx  ;
DROP INDEX IF EXISTS xrs_met_idx   ;
DROP INDEX IF EXISTS xrs_flare_idx    ;
DROP INDEX IF EXISTS xrs_solar_intensity_idx;

-- CASCADE removes constraint-backed indexes, owned sequences, and remaining dependents.
DROP TABLE IF EXISTS xrs CASCADE;
