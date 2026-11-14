"""XRS endpoint: Aggregate spectra for observations overlapping a selected coordinate."""
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.db import (
    SPECTRUM_COLUMNS,
    SPECTRUM_SEARCH_COLUMNS,
    find_xrs_observations_near,
    get_max_xrs_search_radius_km,
)

xrs_router = APIRouter()
log = logging.getLogger(__name__)


@xrs_router.get("/xrs")
def get_xrs_spectra(
    request: Request,
    lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    radius_km: float = Query(0.0, ge=0, le=get_max_xrs_search_radius_km(), allow_inf_nan=False),
) -> dict:
    """
    Return weighted-average spectra for all observations overlapping the selected coordinate.

        GET /api/xrs?lon=<float>&lat=<float>[&radius_km=<float>]

    An observation overlaps when the distance from its boresight point to the selected
    coordinate is at most its footprint radius plus ``radius_km`` (0 means just the point).
    Observations without a footprint, or with a data-length quality flag, are not matched.
    Each channel is averaged using the query's spatial weight; missing channel values do not
    contribute to that channel's denominator.
    """
    try:
        rows = find_xrs_observations_near(
            request.app.state.db_engine,
            lon,
            lat,
            radius_km,
            columns=SPECTRUM_SEARCH_COLUMNS,
        )
    except SQLAlchemyError as exc:
        log.exception("Failed to retrieve XRS observations at lon=%s, lat=%s", lon, lat)
        raise HTTPException(status_code=503, detail="XRS database is unavailable") from exc

    spectra = {}
    for column in SPECTRUM_COLUMNS:
        weighted_totals = []
        channel_weights = []
        for row in rows:
            values = row[column.name]
            weight = float(row["weight"])
            if values is None or weight <= 0:
                continue
            for index, value in enumerate(values):
                if value is None:
                    continue
                while index >= len(weighted_totals):
                    weighted_totals.append(0.0)
                    channel_weights.append(0.0)
                weighted_totals[index] += float(value) * weight
                channel_weights[index] += weight
        spectra[column.name] = (
            [total / weight if weight else None for total, weight in zip(weighted_totals, channel_weights)]
            if weighted_totals
            else None
        )

    return {
        "lon": lon,
        "lat": lat,
        "radius_km": radius_km,
        "observation_count": len(rows),
        "spectra": spectra,
    }