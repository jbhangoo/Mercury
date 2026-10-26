"""
Tests the xrs endpoint call.
Valid calls must include lat and lon parameters and may include radius_km and limit.
The tests check for valid requests, missing and extra parameters, invalid lat/lon/radius values,
boundary values, special characters, and the shape of the response built from database rows.
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
    assert data["radius_km"] == 0

    # Test the xrs route works even with extra parameters.
    data = get_data(
        client,
        "/api/xrs?lat=37.7749&lon=-122.41944&extra_param=extra",
        200,
    )
    assert "lat" in data
    assert "lon" in data

    # Test the xrs route with boundary values for latitude, longitude and radius.
    data = get_data(client, "/api/xrs?lat=-90.0&lon=0.0", 200)
    assert "lat" in data
    assert "lon" in data
    get_data(client, "/api/xrs?lat=0&lon=180&radius_km=2500", 200)

    # Odd but valid way to specify the north pole
    data = get_data(client, "/api/xrs?lat=90.0&lon=-180.0", 200)
    assert "lat" in data
    assert "lon" in data

    # Examine the response for a specific lat/lon to ensure it returns the expected structure.
    data = get_data(client, "/api/xrs?lon=83.25&lat=-74.875&radius_km=150", 200)
    assert data["lon"] == 83.25 and data["lat"] == -74.875 and data["radius_km"] == 150
    assert data["observations"] == []
    assert data["has_more"] is False
    assert "aggregatedValue" not in data
    assert "solarIntensity" not in data
    assert "composition" not in data


def observation_row(**overrides):
    row = {
        "id": 7,
        "source_file": "xrscdr2013101.dat",
        "met": 123456,
        "orbit_number": 25,
        "observed_start": datetime(2013, 4, 11, 0, tzinfo=timezone.utc),
        "observed_end": datetime(2013, 4, 11, 0, 5, tzinfo=timezone.utc),
        "fov_status": 1,
        "intersection": True,
        "data_quality": 0,
        "boresight_lon": -80.5,
        "boresight_lat": 30,
        "footprint_radius_km": 303.4,
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
        "distance_km": 12.5,
        "weight": 0.9966,
    }
    return {**row, **overrides}


def test_xrs_route_returns_database_observations_as_utc(client):
    client.app.state.db_engine = EmptyEngine([observation_row()])

    data = get_data(client, "/api/xrs?lon=-80.5&lat=30", 200)

    observation = data["observations"][0]
    assert observation["met"] == 123456
    assert observation["observed_start"] == "2013-04-11T00:00:00+00:00"
    assert observation["gpc1_mg_spectrum"] == [1, 2]
    assert (observation["boresight_lat"], observation["boresight_lon"]) == (30, -80.5)
    assert (observation["footprint_radius_km"], observation["distance_km"], observation["weight"]) == (303.4, 12.5, 0.9966)
    assert client.app.state.db_engine.last_query_parameters == {
        "lon": -80.5,
        "lat": 30.0,
        "roi_radius_km": 0.0,
        "limit": 101,
    }


def test_xrs_route_passes_the_circle_radius_and_limit_to_the_search(client):
    client.app.state.db_engine = EmptyEngine([])
    get_data(client, "/api/xrs?lon=10&lat=-20&radius_km=250.5&limit=25", 200)
    assert client.app.state.db_engine.last_query_parameters == {
        "lon": 10.0, "lat": -20.0, "roi_radius_km": 250.5, "limit": 26,
    }


def test_xrs_route_reports_when_more_observations_exist(client):
    rows = [observation_row(id=i, met=i) for i in range(3)]
    client.app.state.db_engine = EmptyEngine(rows)
    data = get_data(client, "/api/xrs?lon=0&lat=0&limit=2", 200)
    assert [o["id"] for o in data["observations"]] == [0, 1] and data["has_more"] is True


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

    get_data(client, "/api/xrs?lat=nan&lon=0", 422)


def test_xrs_route_bad_radius_or_limit(client):
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=-1", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=2500.1", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=abc", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=inf", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&limit=0", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&limit=501", 422)