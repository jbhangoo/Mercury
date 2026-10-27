import logging
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.db import find_xrs_observations_near, get_max_xrs_search_radius_km

xrs_router = APIRouter()
log = logging.getLogger(__name__)


@xrs_router.get("/xrs")
def get_xrs_details(
    request: Request,
    lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    radius_km: float = Query(0.0, ge=0, le=get_max_xrs_search_radius_km(), allow_inf_nan=False),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """
    Return valid observations that overlap a circle of interest around the selected coordinate.

        GET /api/xrs?lon=<float>&lat=<float>[&radius_km=<float>]

    An observation overlaps when the distance from its boresight point to the selected
    coordinate is at most its footprint radius plus ``radius_km`` (0 means just the point).
    Each observation carries ``distance_km`` and a Gaussian ``weight`` (1.0 at its boresight
    point), and observations come back with the highest weight first. The response is capped
    at ``limit`` observations and includes ``has_more``. Observations without a loaded
    footprint, or with a data-length quality flag, are not matched.
    """
    try:
        rows = find_xrs_observations_near(
            request.app.state.db_engine,
            lon,
            lat,
            radius_km,
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
        "radius_km": radius_km,
        "observations": observations,
        "has_more": has_more,
    }