"""
Database access routines for API operations and for the data loaders.

Positions are plain latitude/longitude numbers on a sphere the size of Mercury, so
distances are great-circle distances and no PostGIS functions are involved.

Searching around a point
------------------------
Each observation is described by its boresight point (where the instrument was
pointing) and footprint_radius_km, the distance from that point to the nearest
perimeter vertex of its footprint. A circle of interest (lon, lat, radius) overlaps
an observation when

    distance(boresight point, circle center) <= footprint_radius_km + circle radius

and the observation's contribution to a result is weighted by a Gaussian of the
distance between its boresight point and the circle center,

    weight = exp(-distance**2 / (2 * sigma**2)),  sigma = WEIGHT_SIGMA_FRACTION * footprint_radius_km

so the weight is 1.0 at the boresight point and exp(-2) = 0.135 at the edge of the
certain-coverage circle. sigma is a modelling choice, not something in the data.
With a circle radius above zero the weight is that of the circle's center.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine, RowMapping

from .schema import DETAIL_COLUMNS, xrs

# Same value as database/pds2db/consts.py (the server image does not contain that package;
# tests/server/test_db_access.py checks the two stay equal).
MERCURY_RADIUS_KM = 2439.4

# Gaussian width as a fraction of the observation's footprint radius.
WEIGHT_SIGMA_FRACTION = 0.5

# An observation is "valid" for a spatial search when it has a boresight point and a
# footprint radius, and bit 0 of data_quality (packet length mismatch) is clear.
VALID_FOR_SEARCH = and_(
    xrs.c.boresight_lat.is_not(None),
    xrs.c.footprint_radius_km.is_not(None),
    xrs.c.data_quality.op("&")(1) == 0,
)

# How far (in time) a CDR row's start may be from a footprint label's start and still
# match it; MET alone repeats between spacecraft clock partitions, which are years apart.
FOOTPRINT_MATCH_WINDOW = timedelta(hours=1)


XRS_INSERT_SQL = text("""
INSERT INTO xrs (
    source_file, source_id, met, orbit_number, observed_start, observed_end,
    fov_status, intersection, data_quality, boresight_lat, boresight_lon,
    spacecraft_altitude_km, solar_flare_detected, solar_monitor_rate, solar_monitor_spect_shift,
    gpc1_mg_spectrum, gpc2_al_spectrum, gpc3_un_spectrum, solar_mon_spectrum,
    housekeeping, processing_version
) VALUES (
    :source_file, :source_id, :met, :orbit_number, :observed_start, :observed_end,
    :fov_status, :intersection, :data_quality, :boresight_lat, :boresight_lon,
    :scalt, :solar_flare_detected, :solar_monitor_rate, :solar_monitor_spect_shift,
    CAST(:gpc1_mg_spectrum AS integer[]), CAST(:gpc2_al_spectrum AS integer[]),
    CAST(:gpc3_un_spectrum AS integer[]), CAST(:solar_mon_spectrum AS integer[]),
    :housekeeping, :processing_version
)
ON CONFLICT (source_file, source_id) DO UPDATE SET
    met = EXCLUDED.met, orbit_number = EXCLUDED.orbit_number,
    observed_start = EXCLUDED.observed_start, observed_end = EXCLUDED.observed_end,
    fov_status = EXCLUDED.fov_status, intersection = EXCLUDED.intersection,
    data_quality = EXCLUDED.data_quality,
    boresight_lat = EXCLUDED.boresight_lat, boresight_lon = EXCLUDED.boresight_lon,
    footprint_radius_km = CASE
        WHEN xrs.boresight_lat IS NOT DISTINCT FROM EXCLUDED.boresight_lat
         AND xrs.boresight_lon IS NOT DISTINCT FROM EXCLUDED.boresight_lon
        THEN xrs.footprint_radius_km END,
    spacecraft_altitude_km = EXCLUDED.spacecraft_altitude_km,
    solar_flare_detected = EXCLUDED.solar_flare_detected,
    solar_monitor_rate = EXCLUDED.solar_monitor_rate,
    solar_monitor_spect_shift = EXCLUDED.solar_monitor_spect_shift,
    gpc1_mg_spectrum = EXCLUDED.gpc1_mg_spectrum, gpc2_al_spectrum = EXCLUDED.gpc2_al_spectrum,
    gpc3_un_spectrum = EXCLUDED.gpc3_un_spectrum, solar_mon_spectrum = EXCLUDED.solar_mon_spectrum,
    housekeeping = EXCLUDED.housekeeping, processing_version = EXCLUDED.processing_version
""").bindparams(bindparam("housekeeping", type_=JSONB))
# A reload keeps footprint_radius_km, sclk_partition and the external solar_intensity columns,
# unless the boresight point changed: the radius was measured from it, so it is cleared.

XRS_FOOTPRINT_LOOKUP_SQL = text("""
SELECT id, observed_start, boresight_lat, boresight_lon, footprint_radius_km, sclk_partition
FROM xrs
WHERE met = :met
  AND observed_start BETWEEN :window_start AND :window_end
ORDER BY abs(extract(epoch FROM observed_start - :start_time)), id
LIMIT 1
""")

XRS_FOOTPRINT_UPDATE_SQL = text("""
UPDATE xrs SET sclk_partition = :partition, footprint_radius_km = :radius_km WHERE id = :id
""")


def db_xrs_insert(engine: Engine, records: Sequence[Mapping[str, object]]) -> None:
    """Insert or update XRS records atomically."""
    with engine.begin() as connection:
        connection.execute(XRS_INSERT_SQL, records)


def db_xrs_find_for_footprint(connection: Connection, met: int, start_time: datetime) -> RowMapping | None:
    """The CDR row a footprint belongs to: same MET, with a start time within FOOTPRINT_MATCH_WINDOW
    of the footprint label's start (the closest one if several). None if there is no such row."""
    return connection.execute(XRS_FOOTPRINT_LOOKUP_SQL, {
        "met": met,
        "start_time": start_time,
        "window_start": start_time - FOOTPRINT_MATCH_WINDOW,
        "window_end": start_time + FOOTPRINT_MATCH_WINDOW,
    }).mappings().first()


def db_xrs_set_footprint(connection: Connection, row_id: int, partition: int, radius_km: float) -> None:
    """Record a footprint's radius and clock partition on its CDR row."""
    connection.execute(XRS_FOOTPRINT_UPDATE_SQL, {"id": row_id, "partition": partition, "radius_km": radius_km})


def great_circle_distance_km(lat_column, lon_column, lat, lon):
    """SQL expression: distance in km on Mercury from (lat_column, lon_column) to (lat, lon)."""
    lat_a, lat_b = func.radians(lat_column), func.radians(lat)
    cosine = (func.sin(lat_a) * func.sin(lat_b)
              + func.cos(lat_a) * func.cos(lat_b) * func.cos(func.radians(lon_column - lon)))
    return MERCURY_RADIUS_KM * func.acos(func.least(1.0, func.greatest(-1.0, cosine)))


def near_observations_statement():
    """Valid observations overlapping a circle of interest, strongest weight first.

    Bind parameters: lon, lat (center, degrees), roi_radius_km (>= 0) and limit."""
    distance = great_circle_distance_km(
        xrs.c.boresight_lat, xrs.c.boresight_lon, bindparam("lat"), bindparam("lon")
    ).label("distance_km")
    candidates = select(*DETAIL_COLUMNS, distance).where(VALID_FOR_SEARCH).subquery("candidates")
    sigma = WEIGHT_SIGMA_FRACTION * candidates.c.footprint_radius_km
    weight = func.exp(-(candidates.c.distance_km * candidates.c.distance_km) / (2.0 * sigma * sigma)).label("weight")
    return (
        select(candidates, weight)
        .where(candidates.c.distance_km <= candidates.c.footprint_radius_km + bindparam("roi_radius_km"))
        .order_by(weight.desc(), candidates.c.observed_start.desc(), candidates.c.id.desc())
        .limit(bindparam("limit"))
    )


def find_xrs_observations_near(
    engine: Engine, lon: float, lat: float, radius_km: float, limit: int
) -> list[RowMapping]:
    """Valid XRS observations overlapping the circle of interest (lon, lat, radius_km).

    Each row has the observation's columns plus distance_km (from its boresight point to the
    center of the circle) and weight (see the module docstring). Rows come back in descending
    weight, so a limit keeps the observations that matter most."""
    with engine.connect() as connection:
        result = connection.execute(
            near_observations_statement(),
            {"lon": lon, "lat": lat, "roi_radius_km": radius_km, "limit": limit},
        ).mappings()
        return result.all()