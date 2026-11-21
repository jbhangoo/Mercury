"""XRS endpoint: exposure-normalized spectra for observations overlapping a selected coordinate."""
import logging
import math

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.db import (
    SPECTRUM_COLUMNS,
    find_xrs_observations_near,
    get_max_xrs_search_radius_km,
)
from app.db.access import SPECTRUM_RATE_SEARCH_COLUMNS

xrs_router = APIRouter()
log = logging.getLogger(__name__)

SPECTRUM_UNITS = "counts per second per unit solar monitor rate"


def _exposure(row) -> float | None:
    """Integration time (seconds) times solar monitor rate for one observation.

    Returns None when the observation cannot be normalized: no solar monitor rate (or a rate
    of zero or less), or an integration interval that is not positive.

    ASSUMPTION: solar_monitor_rate is a rate (counts per second). If it turns out to be the
    total count over the integration interval, drop the time factor and return the rate alone.
    """
    start, end, rate = row["observed_start"], row["observed_end"], row["solar_monitor_rate"]
    if start is None or end is None or rate is None or rate <= 0:
        return None
    seconds = (end - start).total_seconds()
    return seconds * rate if seconds > 0 else None


def integrate_spectra(rows, column_name: str) -> tuple[list | None, list | None]:
    """Spatially weighted, exposure-normalized spectrum for one spectrum column.

    For every channel c, over the observations i that have a value in that channel:

        rate_c  = sum(w_i * counts_ic) / sum(w_i * exposure_i)
        error_c = sqrt(sum(w_i**2 * counts_ic)) / sum(w_i * exposure_i)

    w_i is the spatial (Gaussian) weight of the observation and exposure_i is integration time
    times solar monitor rate. This is a ratio estimator: it is unbiased for the surface's rate
    if each footprint's average equals the value at the point, and w_i only says how far to
    trust an observation. The error is the Poisson error of the weighted counts. Missing
    channel values do not contribute to that channel's numerator or denominator, and
    observations that cannot be normalized are skipped. Returns (None, None) when nothing
    contributed.
    """
    numerator: list[float] = []
    denominator: list[float] = []
    variance: list[float] = []
    for row in rows:
        values = row[column_name]
        weight = float(row["weight"])
        exposure = _exposure(row)
        if values is None or weight <= 0 or exposure is None:
            continue
        for index, value in enumerate(values):
            if value is None:
                continue
            while index >= len(numerator):
                numerator.append(0.0)
                denominator.append(0.0)
                variance.append(0.0)
            counts = float(value)
            numerator[index] += weight * counts
            denominator[index] += weight * exposure
            variance[index] += weight * weight * counts
    if not numerator:
        return None, None
    rates = [n / d if d else None for n, d in zip(numerator, denominator)]
    errors = [math.sqrt(v) / d if d else None for v, d in zip(variance, denominator)]
    return rates, errors


@xrs_router.get("/xrs")
def get_xrs_spectra(
    request: Request,
    lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    radius_km: float = Query(0.0, ge=0, le=get_max_xrs_search_radius_km(), allow_inf_nan=False),
    flare_only: bool = Query(False),
) -> dict:
    """
    Return exposure-normalized spectra for all observations overlapping the selected coordinate.

        GET /api/xrs?lon=<float>&lat=<float>[&radius_km=<float>][&flare_only=<bool>]

    An observation overlaps when the distance from its boresight point to the selected
    coordinate is at most its footprint radius plus ``radius_km`` (0 means just the point).
    Observations without a footprint, or with a data-length quality flag, are not matched;
    with ``flare_only`` neither are observations not flagged as taken during a solar flare.

    Each channel is the spatially weighted sum of counts divided by the weighted sum of
    (integration time x solar monitor rate), in ``units``; ``spectra_error`` holds the Poisson
    error of each value. Observations with no usable solar monitor rate or integration time
    are matched but left out of the spectra: ``observations_used`` counts those that remain.
    """
    try:
        rows = find_xrs_observations_near(
            request.app.state.db_engine,
            lon,
            lat,
            radius_km,
            columns=SPECTRUM_RATE_SEARCH_COLUMNS,
            flare_only=flare_only,
        )
    except SQLAlchemyError as exc:
        log.exception("Failed to retrieve XRS observations at lon=%s, lat=%s", lon, lat)
        raise HTTPException(status_code=503, detail="XRS database is unavailable") from exc

    spectra = {}
    spectra_error = {}
    for column in SPECTRUM_COLUMNS:
        spectra[column.name], spectra_error[column.name] = integrate_spectra(rows, column.name)

    return {
        "lon": lon,
        "lat": lat,
        "radius_km": radius_km,
        "flare_only": flare_only,
        "observation_count": len(rows),
        "observations_used": sum(
            1 for row in rows if float(row["weight"]) > 0 and _exposure(row) is not None
        ),
        "units": SPECTRUM_UNITS,
        "spectra": spectra,
        "spectra_error": spectra_error,
    }