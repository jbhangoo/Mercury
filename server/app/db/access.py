"""
Database access routines for API operations.
"""

from sqlalchemy import bindparam, func, select
from sqlalchemy.engine import Engine, RowMapping

from app.db.schema import DETAIL_COLUMNS, SRID, xrs


def db_xrs_covers_point(engine: Engine, lon: float, lat: float, limit: int) -> list[RowMapping]:
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
