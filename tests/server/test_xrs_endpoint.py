"""
Tests the xrs endpoint call.
Valid calls must include lat and lon parameters and may include radius_km and limit.
The tests check for valid requests, missing and extra parameters, invalid lat/lon/radius values,
boundary values, special characters, and the shape of the response built from database rows.
"""
from get_data import get_data
from datetime import datetime, timezone

import pytest

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
    assert data["observation_count"] == 0
    assert data["spectra"] == {
        "gpc1_mg_spectrum": None,
        "gpc2_al_spectrum": None,
        "gpc3_un_spectrum": None,
        "solar_mon_spectrum": None,
    }


def observation_row(**overrides):
    """A row from the spectrum search, including distance, weight, and exposure fields."""
    row = {
        "id": 7,
        "observed_start": datetime(2013, 4, 11, 0, tzinfo=timezone.utc),
        "observed_end": datetime(2013, 4, 11, 0, 0, 1, tzinfo=timezone.utc),
        "solar_monitor_rate": 1,
        "boresight_lon": -80.5,
        "boresight_lat": 30,
        "footprint_radius_km": 303.4,
        "solar_intensity": None,
        "gpc1_mg_spectrum": None,
        "gpc2_al_spectrum": None,
        "gpc3_un_spectrum": None,
        "solar_mon_spectrum": None,
        "distance_km": 12.5,
        "weight": 0.9966,
    }
    return {**row, **overrides}


def test_xrs_route_returns_weighted_spectra_for_all_matching_observations(client):
    client.app.state.db_engine = EmptyEngine([
        observation_row(
            id=7,
            gpc1_mg_spectrum=[10, 20, 30],
            gpc2_al_spectrum=[4, 8],
            weight=1.0,
        ),
        observation_row(
            id=8,
            gpc1_mg_spectrum=[20, 40, 60],
            gpc2_al_spectrum=[8],
            gpc3_un_spectrum=[None, 5],
            solar_mon_spectrum=[1, 3],
            weight=0.5,
        ),
    ])

    data = get_data(client, "/api/xrs?lon=-80.5&lat=30", 200)

    assert data["observation_count"] == 2
    assert data["spectra"]["gpc1_mg_spectrum"] == pytest.approx([20 / 1.5, 40 / 1.5, 60 / 1.5])
    assert data["spectra"]["gpc2_al_spectrum"] == pytest.approx([8 / 1.5, 8])
    assert data["spectra"]["gpc3_un_spectrum"] == [None, 5]
    assert data["spectra"]["solar_mon_spectrum"] == [1, 3]
    assert client.app.state.db_engine.last_query_parameters == {
        "lon": -80.5,
        "lat": 30.0,
        "roi_radius_km": 0.0,
    }


def test_xrs_route_passes_the_circle_radius_and_does_not_limit_search_results(client):
    client.app.state.db_engine = EmptyEngine([])
    get_data(client, "/api/xrs?lon=10&lat=-20&radius_km=250.5", 200)
    assert client.app.state.db_engine.last_query_parameters == {
        "lon": 10.0, "lat": -20.0, "roi_radius_km": 250.5,
    }


def test_xrs_route_summarizes_every_matching_observation(client):
    rows = [observation_row(id=i) for i in range(3)]
    client.app.state.db_engine = EmptyEngine(rows)
    data = get_data(client, "/api/xrs?lon=0&lat=0", 200)
    assert data["observation_count"] == 3
    assert data["observations_used"] == 3


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


def test_xrs_route_bad_radius(client):
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=-1", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=2500.1", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=abc", 422)
    get_data(client, "/api/xrs?lat=0&lon=0&radius_km=inf", 422)