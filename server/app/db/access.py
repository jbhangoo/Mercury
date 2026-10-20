"""
Database access routines for API operations.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, RowMapping

from .schema import DETAIL_COLUMNS, SRID, xrs


XRS_INSERT_SQL = text(f"""
INSERT INTO xrs (
    source_file, source_id, met, orbit_number, observed_start, observed_end,
    fov_status, intersection, data_quality, center, spacecraft_altitude_km,
    solar_flare_detected, solar_monitor_rate, solar_monitor_spect_shift,
    gpc1_mg_spectrum, gpc2_al_spectrum, gpc3_un_spectrum, solar_mon_spectrum,
    housekeeping, processing_version
) VALUES (
    :source_file, :source_id, :met, :orbit_number, :observed_start, :observed_end,
    :fov_status, :intersection, :data_quality,
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                      CAST(:lat AS double precision)), {SRID}) END,
    :scalt, :solar_flare_detected, :solar_monitor_rate, :solar_monitor_spect_shift,
    CAST(:gpc1_mg_spectrum AS integer[]), CAST(:gpc2_al_spectrum AS integer[]),
    CAST(:gpc3_un_spectrum AS integer[]), CAST(:solar_mon_spectrum AS integer[]),
    :housekeeping, :processing_version
)
ON CONFLICT (source_file, source_id) DO UPDATE SET
    met = EXCLUDED.met, orbit_number = EXCLUDED.orbit_number,
    observed_start = EXCLUDED.observed_start, observed_end = EXCLUDED.observed_end,
    fov_status = EXCLUDED.fov_status, intersection = EXCLUDED.intersection,
    data_quality = EXCLUDED.data_quality, center = EXCLUDED.center,
    spacecraft_altitude_km = EXCLUDED.spacecraft_altitude_km,
    solar_flare_detected = EXCLUDED.solar_flare_detected,
    solar_monitor_rate = EXCLUDED.solar_monitor_rate,
    solar_monitor_spect_shift = EXCLUDED.solar_monitor_spect_shift,
    gpc1_mg_spectrum = EXCLUDED.gpc1_mg_spectrum, gpc2_al_spectrum = EXCLUDED.gpc2_al_spectrum,
    gpc3_un_spectrum = EXCLUDED.gpc3_un_spectrum, solar_mon_spectrum = EXCLUDED.solar_mon_spectrum,
    housekeeping = EXCLUDED.housekeeping, processing_version = EXCLUDED.processing_version
""").bindparams(bindparam("housekeeping", type_=JSONB))

"""SQL for turning a footprint polygon from rdr_parser into the final xrs.footprint geometry."""
SRID = 4326  # WGS84

# A scalar expression that takes the WKT of an unwrapped polygon (bind parameter :wkt) and
# returns a valid MultiPolygon with every longitude inside -180..180:
#   1. repair the ring (method=structure keeps the ring's inside filled, so the
#      anomalous interior vertices the SIS mentions do not punch holes),
#   2. cut it at +/-180 by intersecting with the map and with its copies one
#      world to the east and west, moving those copies back,
#   3. union the pieces and keep only polygons.
# Needs PostGIS 3.2+ with GEOS 3.10+ (for method=structure). An empty result means the
# polygon had no area; callers should treat that as a failure.
FOOTPRINT_GEOMETRY_SQL = f"""(
    SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(ARRAY[
               ST_Intersection(v.g, ST_MakeEnvelope(-180, -90, 180, 90, {SRID})),
               ST_Translate(ST_Intersection(v.g, ST_MakeEnvelope(180, -90, 540, 90, {SRID})), -360, 0),
               ST_Translate(ST_Intersection(v.g, ST_MakeEnvelope(-540, -90, -180, 90, {SRID})), 360, 0)
           ]), 'method=structure'), 3))
    FROM (SELECT ST_MakeValid(ST_SetSRID(ST_GeomFromText(:wkt), {SRID}), 'method=structure') AS g) AS v
)"""

XRS_UPDATE_SQL = text(f"""
UPDATE xrs SET  """).bindparams(bindparam("housekeeping", type_=JSONB))

def db_xrs_insert(engine: Engine, records: Sequence[Mapping[str, object]]) -> None:
    """Insert or update XRS records atomically."""
    with engine.begin() as connection:
        connection.execute(XRS_INSERT_SQL, records)

def db_xrs_update(engine: Engine, records: Sequence[Mapping[str, object]]) -> None:
    """Update XRS records atomically."""
    with engine.begin() as connection:
        connection.execute(XRS_UPDATE_SQL, records)

def find_xrs_observations_covering_point(engine: Engine, lon: float, lat: float, limit: int) -> list[RowMapping]:
    """
    Return all XRS observations whose footprints overlap a point.
    These are ordered in descending order of observed_start, 
    so they can be limited to the given number of rows
    """

    point = func.ST_SetSRID(
        func.ST_MakePoint(bindparam("lon"), bindparam("lat")),
        SRID,
    )
    statement = (
        select(*DETAIL_COLUMNS)
        .where(
            xrs.c.footprint.is_not(None),
            func.ST_Covers(xrs.c.footprint, point),
        )
        .order_by(xrs.c.observed_start.desc(), xrs.c.id.desc())
        .limit(bindparam("limit"))
    )
    with engine.connect() as connection:
        result = connection.execute(
            statement,
            {"lon": lon, "lat": lat, "limit": limit},
        ).mappings()
        return result.all()
