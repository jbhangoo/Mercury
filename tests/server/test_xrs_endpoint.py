"""
Tests the xrs endpoint call.
Valid calls must include both lat and lon parameters. 
The tests check for various scenarios including valid requests, 
missing parameters, extra parameters, invalid lat/lon values, 
boundary values, negative values, large values, zero values, 
special characters and missing lat/lon parameters.
"""
from get_data import get_data
from datetime import datetime, timezone

from conftest import EmptyEngine

def test_xrs_route(client):
    """
    Test the xrs route with a sample request.
    """
    data = get_data(client, "/api/xrs?lat=37.7749&lon=-122.4194", 200)
    assert "lat" in data
    assert "lon" in data

    # Test the xrs route works even with extra parameters.
    data = get_data(
        client,
        "/api/xrs?lat=37.7749&lon=-122.41944&extra_param=extra",
        200,
    )
    assert "lat" in data
    assert "lon" in data

    # Test the xrs route with boundary values for latitude and longitude.
    data = get_data(client, "/api/xrs?lat=-90.0&lon=0.0", 200)
    assert "lat" in data
    assert "lon" in data

    # Odd but valid way to specify the north pole
    data = get_data(client, "/api/xrs?lat=90.0&lon=-180.0", 200)
    assert "lat" in data
    assert "lon" in data

    # Examine the response for a specific lat/lon to ensure it returns the expected structure.
    data = get_data(client, "/api/xrs?lon=83.25&lat=-74.875", 200)
    assert "lat" in data
    assert "lon" in data
    assert data["observations"] == []
    assert data["has_more"] is False
    assert "aggregatedValue" not in data
    assert "solarIntensity" not in data
    assert "composition" not in data


def test_xrs_route_returns_database_observations_as_utc(client):
    client.app.state.db_engine = EmptyEngine([{
        "id": 7,
        "source_file": "xrscdr2013101.dat",
        "met": 123456,
        "orbit_number": 25,
        "observed_start": datetime(2013, 4, 11, 0, tzinfo=timezone.utc),
        "observed_end": datetime(2013, 4, 11, 0, 5, tzinfo=timezone.utc),
        "fov_status": 1,
        "intersection": True,
        "data_quality": 0,
        "center_lon": -80.5,
        "center_lat": 30,
        "spacecraft_altitude_km": 400,
        "solar_flare_detected": True,
        "solar_monitor_rate": None,
        "solar_monitor_spect_shift": None,
        "solar_intensity": None,
        "solar_intensity_source": None,
        "gpc1_mg_spectrum": [1, 2],
        "gpc2_al_spectrum": [3, 4],
        "gpc3_un_spectrum": [5, 6],
        "solar_mon_spectrum": [7, 8],
        "housekeeping": {},
    }])

    data = get_data(client, "/api/xrs?lon=-80.5&lat=30", 200)

    assert data["observations"][0]["met"] == 123456
    assert data["observations"][0]["observed_start"] == "2013-04-11T00:00:00+00:00"
    assert data["observations"][0]["gpc1_mg_spectrum"] == [1, 2]
    assert client.app.state.db_engine.last_query_parameters == {
        "lon": -80.5,
        "lat": 30.0,
        "limit": 101,
    }


def test_xrs_route_bad_lat_lon(client): 
    """
    Test the xrs route with invalid latitude and longitude parameters.
    """
    get_data(client, "/api/xrs?lat=91&lon=0", 422)

    get_data(client, "/api/xrs?lat=0&lon=181", 422)

    get_data(client, "/api/xrs?lat=37.7749", 422)

    get_data(client, "/api/xrs?lon=-122.4194", 422)

    get_data(client, "/api/xrs?lat=invalid_lat&lon=invalid_lon", 422)
    
    get_data(client, "/api/xrs?lat=&lon=", 422)
