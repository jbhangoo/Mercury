import logging
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

xrs_router = APIRouter()
log = logging.getLogger(__name__)

XRS_AT_POINT = text("""
    SELECT
        id,
        source_file,
        met,
        orbit_number,
        observed_start,
        observed_end,
        fov_status,
        intersection,
        data_quality,
        center_lon,
        center_lat,
        spacecraft_altitude_km,
        solar_flare_detected,
        solar_monitor_rate,
        solar_monitor_spect_shift,
        solar_intensity,
        solar_intensity_source,
        gpc1_mg_spectrum,
        gpc2_al_spectrum,
        gpc3_un_spectrum,
        solar_mon_spectrum,
        housekeeping
    FROM xrs
    WHERE footprint IS NOT NULL
      AND ST_Covers(
          footprint,
          ST_SetSRID(ST_MakePoint(:lon, :lat), 910001)
      )
    ORDER BY observed_start DESC, id DESC
    LIMIT :limit
""")

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
        with request.app.state.db_engine.connect() as connection:
            result = connection.execute(
                XRS_AT_POINT,
                {"lon": lon, "lat": lat, "limit": limit + 1},
            ).mappings()
            rows = result.all()
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
