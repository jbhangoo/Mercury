import logging
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.db import find_xrs_observations_covering_point

xrs_router = APIRouter()
log = logging.getLogger(__name__)

@xrs_router.get("/xrs")
def get_xrs_details(
    request: Request,
    lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """
    Return observations whose loaded footprint covers the selected coordinate.

        GET /api/xrs?lon=<float>&lat=<float>
    The response is capped at ``limit`` observations and includes ``has_more``.
    Records without footprints are not spatially matched.
    """
    try:
        rows = find_xrs_observations_covering_point(
            request.app.state.db_engine,
            lon,
            lat,
            limit + 1,
        )
    except SQLAlchemyError as exc:
        log.exception("Failed to retrieve XRS observations at lon=%s, lat=%s", lon, lat)
        raise HTTPException(status_code=503, detail="XRS database is unavailable") from exc

    has_more = len(rows) > limit
    observations = []
    for row in rows[:limit]:
        observation = dict(row)
        for key in ("observed_start", "observed_end"):
            observation[key] = observation[key].astimezone(timezone.utc).isoformat()
        observations.append(observation)

    return {
        "lon": lon,
        "lat": lat,
        "observations": observations,
        "has_more": has_more,
    }
