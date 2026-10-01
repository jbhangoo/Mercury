-- Execute from psql as an administrator.
-- This removes application tables and indexes, but keeps the mercury database,
-- mercury role, and PostGIS extension.
-- Assumes psql. Results not guaranteed for a generic SQL processor!

\set ON_ERROR_STOP on
\c mercury

-- Drop explicit and constraint-generated indexes before dropping their tables.
DROP INDEX IF EXISTS xrs_observed_at_idx;
DROP INDEX IF EXISTS xrs_h3_id;
DROP INDEX IF EXISTS xrs_location_gist_idx;
DROP INDEX IF EXISTS xrs_location_geography_idx;
DROP INDEX IF EXISTS xrs_source_idx;
DROP INDEX IF EXISTS xrs_pkey;
DROP INDEX IF EXISTS xrs_observed_at_key;

-- CASCADE also removes owned sequences and any remaining dependent objects.
DROP TABLE IF EXISTS xrs CASCADE;
