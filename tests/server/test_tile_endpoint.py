"""
Tests the mercury_tile endpoint call.
Valid calls must include bounding box parameters. 
The tests check for various scenarios including valid requests, 
missing parameters, missing values, invalid limit values, 
boundary values, negative values, large values, zero values, 
invalid data types, and special characters.
"""
from get_data import get_data

def test_fetch_surface_tile(client) -> None:
    # Typical request for a tile that is on the surface of Mercury
    response = client.get("/api/mercury-tile?north=20.5&south=20.25&east=20.75&west=20.5")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

    # A bounding box that is a single point (north=south, east=west) is valid and should return a tile
    response = client.get("/api/mercury-tile?north=20.5&south=20.5&east=20.5&west=20.5")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

    # A bounding box of (0,0,0,0) is valid and should return a tile
    response = client.get("/api/mercury-tile?north=0&south=0&east=0&west=0")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

    # A bounding box that wraps around the prime meridian (west=-0.5, east=0.5) is valid
    response = client.get("/api/mercury-tile?north=0.25&south=-0.25&east=0.25&west=-0.25")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

    # A bounding box that wraps around the antimeridian (at longitude 180) is invalid
    get_data(client, "/api/mercury-tile?north=20.25&south=20.5&east=-179.25&west=179.5", 422)

    # A very wide bounding box that wraps around the equator is valid.
    response = client.get("/api/mercury-tile?north=0.25&south=-0.25&east=179.75&west=-179.75")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

def test_fetch_invalid_tile(client) -> None:
    # Invalid coordinates that are not on the surface
    get_data(client, "/api/mercury-tile?north=90.25&south=20.5&east=20.75&west=20.5", 422)
    get_data(client, "/api/mercury-tile?north=20.25&south=20.5&east=-180.01&west=20.5", 422)

    # Invalid bounding box where west > east or south > north should return 422
    get_data(client, "/api/mercury-tile?north=20.5&south=20.25&east=179.25&west=179.5", 422)
    get_data(client, "/api/mercury-tile?north=20.25&south=20.5&east=179.75&west=179.5", 422)

    # Height is not used so very tall bounding box is allowed 
    response = client.get("/api/mercury-tile?north=80.5&south=-80.5&east=0.25&west=-0.25")
    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8\xff")

    # Test the /mercury-tile endpoint with missing parameters
    get_data(client, "/api/mercury-tile?north=0", 422)
    get_data(client, "/api/mercury-tile?north=&south=&east=&west=", 422)
    get_data(client, "/api/mercury-tile?north=A&south=B&east=C&west=D", 422)
    get_data(client, "/api/mercury-tile?north=20.5&south=20.25&east=20.75", 422)
    get_data(client, "/api/mercury-tile?lat=-0.5&lon=20.5", 422)
    get_data(client, "/api/mercury-tile", 422)
