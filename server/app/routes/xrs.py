from fastapi import APIRouter, HTTPException, Query
from app.mock_data import generate_mock_xrs_details

xrs_router = APIRouter()

@xrs_router.get("/xrs")
def get_xrs_details(lon: float | None = Query(default=None),
                    lat: float | None = Query(default=None)) -> dict:
    """
    Delivers data requested in app.ts's handleCellClick().
    Retrieves all XRS data overlapping a given lon/lat coordinate.

        GET /api/xrs?lon=<float>&lat=<float>

    Returns a CellDetailPayload:
        { aggregatedValue, solarIntensity, composition }

    404 for missing ones?
    """
    if lon is not None and lat is not None:
        # Retrieve all XRS data over the given lon/lat coordinates
        details = generate_mock_xrs_details(lon, lat)
    else:
        raise HTTPException(status_code=400, detail="Missing required query parameters")

    return details
