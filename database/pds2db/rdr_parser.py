"""
Measures a footprint around the instrument's boresight point.

A footprint file (see rdr_reader) lists the perimeter of the surface an observation
saw: latitude and east longitude pairs, longitudes 0 to 360. The database keeps no
polygon. It keeps the boresight point from the CDR and one number from the footprint,
the radius of the circle around that point which is certain to lie inside the
footprint: the distance from the point to the nearest perimeter *vertex*. (The nearest
point of an edge can be a little closer, but vertices are only about 0.2 degrees,
roughly 10 km, apart, so the circle can poke out of the footprint by at most a few km.)

Everything is done with 3-D unit vectors on a sphere of Mercury's radius, so the
antimeridian, the 0/360 wrap and the poles need no special handling.

    from database.pds2db.rdr_parser import footprint_radius
    result = footprint_radius(64.61, -169.11, vertices)
    result.radius_km, result.inside

The radius is only meaningful when the boresight point lies inside the perimeter.
That is expected whenever the boresight hits the planet (the point is then part of
the field of view's footprint), so footprint_radius() checks it and reports it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pds_consts import MERCURY_RADIUS_KM

# A "nearest vertex" closer than this means the boresight point sits on the perimeter.
MIN_RADIUS_KM = 1e-3
# No footprint is anywhere near this big (the largest are a few thousand km across), so a
# boresight point more than a quarter of the way round the planet from a vertex of its own
# footprint cannot be inside it. It also keeps the azimuth sums in the inside test meaningful.
MAX_VERTEX_ANGLE = np.pi / 2


@dataclass(frozen=True)
class FootprintRadius:
    radius_km: float        # great-circle distance from the boresight point to the nearest vertex
    inside: bool            # the boresight point lies inside the perimeter
    vertex_count: int


def unit_vectors(lat, lon) -> np.ndarray:
    """(n, 3) unit vectors for latitudes and east longitudes in degrees."""
    phi, lam = np.radians(np.atleast_1d(lat)), np.radians(np.atleast_1d(lon))
    return np.column_stack([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])


def _angles_from(center: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Angular distance in radians from `center` to each of `points` (stable for small angles)."""
    return np.arctan2(np.linalg.norm(np.cross(center, points), axis=1), points @ center)


def _perimeter_vectors(vertices) -> np.ndarray:
    lat = np.asarray(vertices["latitude"], dtype=np.float64)
    lon = np.asarray(vertices["longitude"], dtype=np.float64)
    if len(lat) < 3:
        raise ValueError(f"footprint has only {len(lat)} vertices")
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise ValueError("footprint has non-finite coordinates")
    return unit_vectors(lat, lon)


def _check_point(boresight_lat: float, boresight_lon: float) -> np.ndarray:
    if not (np.isfinite(boresight_lat) and np.isfinite(boresight_lon)):
        raise ValueError("boresight point is not finite")
    if abs(boresight_lat) > 90:
        raise ValueError(f"boresight latitude {boresight_lat} is outside -90..90")
    return unit_vectors(boresight_lat, boresight_lon)[0]


def nearest_vertex_distance_km(boresight_lat: float, boresight_lon: float, vertices,
                               *, radius_km: float = MERCURY_RADIUS_KM) -> float:
    """Great-circle distance in km from the boresight point to the nearest perimeter vertex."""
    center = _check_point(boresight_lat, boresight_lon)
    return float(radius_km * _angles_from(center, _perimeter_vectors(vertices)).min())


def boresight_inside_perimeter(boresight_lat: float, boresight_lon: float, vertices) -> bool:
    """True if the boresight point lies inside the footprint's perimeter.

    Looks from the boresight point at the perimeter and adds up the turns between
    neighbouring vertices: a perimeter that encloses the point turns once around it
    (a full 360 degrees, either way), one that does not turns back and forth to nothing.
    Returns False if any vertex is more than 90 degrees from the point (see MAX_VERTEX_ANGLE)."""
    center = _check_point(boresight_lat, boresight_lon)
    points = _perimeter_vectors(vertices)
    if (_angles_from(center, points) > MAX_VERTEX_ANGLE).any():
        return False

    reference = np.array([0.0, 0.0, 1.0]) if abs(center[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    east = np.cross(reference, center)
    east /= np.linalg.norm(east)
    north = np.cross(center, east)
    azimuth = np.arctan2(points @ north, points @ east)
    steps = np.diff(np.append(azimuth, azimuth[0]))
    steps = (steps + np.pi) % (2 * np.pi) - np.pi                # each turn the short way round
    return bool(abs(steps.sum()) > np.pi)


def footprint_radius(boresight_lat: float, boresight_lon: float, vertices,
                     *, radius_km: float = MERCURY_RADIUS_KM) -> FootprintRadius:
    """The radius to store for an observation, and whether it can be trusted.

    `inside` is False when the boresight point is not inside the perimeter, or sits on it
    (a radius under a meter): the circle would not lie within the footprint."""
    nearest = nearest_vertex_distance_km(boresight_lat, boresight_lon, vertices, radius_km=radius_km)
    inside = boresight_inside_perimeter(boresight_lat, boresight_lon, vertices) and nearest > MIN_RADIUS_KM
    return FootprintRadius(radius_km=nearest, inside=inside, vertex_count=len(vertices))