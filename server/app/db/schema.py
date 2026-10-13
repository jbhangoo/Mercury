"""
SQLAlchemy definition of the xrs table, used to build queries.

The table itself is created by database/DB_Create.sql. This module mirrors it
so the API can write ``select(xrs.c.met).where(...)`` instead of repeating
column names in SQL strings; it is never used to create or migrate tables
(constraints and indexes live only in the SQL). tests/server/test_db_schema.py
checks this module against that SQL, so a change to one without the other
fails a test.

    from app.db.schema import xrs, SUMMARY_COLUMNS
    stmt = (select(*SUMMARY_COLUMNS)
            .where(xrs.c.solar_flare_detected)
            .order_by(xrs.c.observed_start.desc()))

Geometry columns (center, footprint) are declared but should rarely be
selected: ask the database for what you need (center_lon/center_lat, or
func.ST_AsGeoJSON(xrs.c.footprint)) rather than the raw geometry.
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Computed, DateTime, Integer, MetaData, SmallInteger, Table, Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB, REAL
from sqlalchemy.types import UserDefinedType

SRID = 910001   # spherical Mercury lon/lat CRS registered in DB_Create.sql


class Geometry(UserDefinedType):
    """A PostGIS geometry column: enough to declare it and use it with func.ST_*()."""

    cache_ok = True

    def __init__(self, geometry_type: str, srid: int = SRID) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **kw) -> str:
        return f"geometry({self.geometry_type},{self.srid})"


metadata = MetaData()

xrs = Table(
    "xrs",
    metadata,
    Column("id", BigInteger, primary_key=True),

    # Provenance: source_file is the CDR day file, source_id the MET as text.
    Column("source_file", Text, nullable=False),
    Column("source_id", Text, nullable=False),

    # Spacecraft clock and orbit.
    Column("met", BigInteger, nullable=False),
    Column("sclk_partition", SmallInteger),
    Column("orbit_number", Integer, nullable=False),

    # Integration interval (UTC).
    Column("observed_start", DateTime(timezone=True), nullable=False),
    Column("observed_end", DateTime(timezone=True), nullable=False),

    # 0 off planet; 1 on planet, lit; 2 on planet, dark; 3 partly off, lit; 4 partly off, dark.
    Column("fov_status", SmallInteger, nullable=False),
    Column("intersection", Boolean, nullable=False),
    Column("data_quality", BigInteger, nullable=False),

    # Boresight intercept and field-of-view outline; lon/lat are generated from center.
    Column("center", Geometry("Point")),
    Column("center_lon", DOUBLE_PRECISION, Computed("ST_X(center)", persisted=True)),
    Column("center_lat", DOUBLE_PRECISION, Computed("ST_Y(center)", persisted=True)),
    Column("footprint", Geometry("MultiPolygon")),
    Column("spacecraft_altitude_km", REAL),

    # The instrument's own solar monitor, plus an optional external flux (W/m^2).
    Column("solar_flare_detected", Boolean, nullable=False),
    Column("solar_monitor_rate", BigInteger),
    Column("solar_monitor_spect_shift", SmallInteger),
    Column("solar_intensity", DOUBLE_PRECISION),
    Column("solar_intensity_source", Text),

    # Counts per channel: GPC channels 10-253 (244 values), solar monitor 23-253 (231).
    Column("gpc1_mg_spectrum", ARRAY(Integer)),
    Column("gpc2_al_spectrum", ARRAY(Integer)),
    Column("gpc3_un_spectrum", ARRAY(Integer)),
    Column("solar_mon_spectrum", ARRAY(Integer)),

    # Every other CDR column, keyed by lower-case name.
    Column("housekeeping", JSONB, nullable=False, server_default=text("'{}'::jsonb")),

    Column("geometry_source", Text, nullable=False, server_default=text("'pds-cdr-boresight'")),
    Column("processing_version", Text, nullable=False, server_default=text("'initial'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

SPECTRUM_COLUMNS = (
    xrs.c.gpc1_mg_spectrum,
    xrs.c.gpc2_al_spectrum,
    xrs.c.gpc3_un_spectrum,
    xrs.c.solar_mon_spectrum,
)

# Light projection for lists and map popups (no spectra, no housekeeping).
SUMMARY_COLUMNS = (
    xrs.c.id,
    xrs.c.source_file,
    xrs.c.met,
    xrs.c.orbit_number,
    xrs.c.observed_start,
    xrs.c.observed_end,
    xrs.c.fov_status,
    xrs.c.intersection,
    xrs.c.data_quality,
    xrs.c.center_lon,
    xrs.c.center_lat,
    xrs.c.spacecraft_altitude_km,
    xrs.c.solar_flare_detected,
    xrs.c.solar_monitor_rate,
    xrs.c.solar_intensity,
    xrs.c.solar_intensity_source,
)

# Full record for a single observation: the summary plus spectra and housekeeping.
DETAIL_COLUMNS = (
    *SUMMARY_COLUMNS,
    xrs.c.solar_monitor_spect_shift,
    *SPECTRUM_COLUMNS,
    xrs.c.housekeeping,
)