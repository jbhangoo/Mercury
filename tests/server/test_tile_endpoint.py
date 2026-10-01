from xmlrpc import client

import pytest

def test_fetch_surface_tile() -> None:
    """
    Test the /mercury_tile endpoint with a sample request.
    """

    response = client.get("/api/mercury_tile?lat=0&lon=0")
    assert response.status_code == 200
    assert response.content is not None
    assert len(response.content) > 0  # Ensure the response is not empty
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")  # Check for PNG signature


def test_fetch_invalid_tile() -> None:
    """
    Test the /mercury_tile endpoint with invalid coordinates that are not on the surface
    """
    response = client.get("/api/mercury_tile?lat=90.25&lon=20.5")
    assert response.status_code == 404
    response = client.get("/api/mercury_tile?lat=20.25&lon=220.5")
    assert response.status_code == 404
    response = client.get("/api/mercury_tile?lat=-0.5&lon=20.5")
    assert response.status_code == 404
    response = client.get("/api/mercury_tile?lon=20.5")
    assert response.status_code == 404
