"""
Mock data generators.

Creates mock data for testing purposes, such as XRS details for a given longitude and latitude.
"""

import random

def generate_mock_xrs_details(lon: float, lat: float) -> dict[str, float | int | str]:
    """Generate mock XRS details for a clicked lon/lat coordinate."""
    return {
        "lon": lon,
        "lat": lat,
        "aggregatedValue": random.randint(0, 100),
        "solarIntensity": random.randint(0, 1000),
        "composition": "Iron/Silicate Regolith",
    }
