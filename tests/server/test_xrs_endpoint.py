"""
Tests the xrs endpoint call.
Valid calls must include both lat and lon parameters. 
The tests check for various scenarios including valid requests, 
missing parameters, extra parameters, invalid lat/lon values, 
boundary values, negative values, large values, zero values, 
special characters and missing lat/lon parameters.
"""
from xmlrpc import client

def test_xrs_route(client):
    """
    Test the xrs route with a sample request.
    """
    response = client.get("/api/xrs?lat=37.7749&lon=-122.4194")
    assert response.status_code == 200
    data = response.json()
    assert "lat" in data
    assert "lon" in data
    assert "color" in data

def test_xrs_route_extra_params(client):
    """
    Test the xrs route works even with extra parameters.
    """
    response = client.get("/api/xrs?lat=37.7749&lon=-122.41944&extra_param=extra")
    assert response.status_code == 200
    data = response.json()
    assert "lat" in data
    assert "lon" in data
    assert "color" in data

def test_xrs_route_boundary_values(client):
    """
    Test the xrs route with boundary values for latitude and longitude.
    """
    response = client.get("/api/xrs?lat=90.0&lon=180.0")
    assert response.status_code == 200
    data = response.json()
    assert "lat" in data
    assert "lon" in data
    assert "color" in data

def test_xrs_route_lat_lon(client): 
    """
    Test the xrs route with latitude and longitude parameters.
    """
    response = client.get("/api/xrs?lat=91&lon=0")
    assert response.status_code == 422  # Unprocessable Entity due to invalid 'lat' parameter

    response = client.get("/api/xrs?lat=0&lon=181")
    assert response.status_code == 422  # Unprocessable Entity due to invalid 'lon' parameter

    response = client.get("/api/xrs?lat=abc&lon=xyz")
    assert response.status_code == 422  # Unprocessable Entity due to non-numeric 'lat' and 'lon' parameters

    response = client.get("/api/xrs?lat=37.7749")
    assert response.status_code == 422  # Unprocessable Entity due to missing 'lon' parameter

    response = client.get("/api/xrs?lon=-122.4194")
    assert response.status_code == 422  # Unprocessable Entity due to missing 'lat' parameter

    response = client.get("/api/xrs?lat=invalid_lat&lon=invalid_lon")
    assert response.status_code == 422  # Unprocessable Entity due to invalid 'lat' and 'lon' parameters

    response = client.get("/api/xrs?lat=1000.0&lon=1000.0")
    assert response.status_code == 422  # Unprocessable Entity due to out-of-range 'lat' and 'lon' parameters

    response = client.get("/api/xrs?lat=0.0&lon=0.0")
    assert response.status_code == 200
    data = response.json()
    assert "lat" in data
    assert "lon" in data
    assert "color" in data

def test_xrs_coordinate_lookup_returns_one_detail_object(client):
    response = client.get("/api/xrs?lon=83.25&lat=-74.875")

    assert response.status_code == 200
    data = response.json()
    assert data["lon"] == 83.25
    assert data["lat"] == -74.875
    assert {"aggregatedValue", "solarIntensity", "composition"} <= data.keys()
    