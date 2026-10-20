"""
Turns a footprint's perimeter vertices (see rdr_reader) into polygon geometry.

The perimeter is stored as latitude and east longitude pairs, and longitudes run
0 to 360. The table wants -180 to 180, and a footprint can straddle the +/-180
meridian or encircle a pole, so a plain list of (lon, lat) pairs would give a
polygon that wraps the wrong way around the planet. build_footprint_polygon()
works in "unwrapped" longitudes instead:

- Longitude steps are taken the short way round (so 359.9 -> 0.1 is a 0.2 degree
  step, not a jump), which makes the ring continuous even where the values wrap.
- If the ring winds once around a pole (net longitude change of 360 degrees), it
  is closed along that pole's edge of the map (latitude +/-90), so the polygon
  covers the cap between the perimeter and the pole.
- The ring is shifted by a multiple of 360 degrees to sit around longitude 0. It
  may then extend past +/-180; footprint_geometry_sql() in rdr_consts.py makes
  PostGIS cut it at the antimeridian and fold the overflow back.

The result is a WKT polygon in unwrapped coordinates, not yet the final
geometry. The SIS notes that pole-spanning footprints can contain a few
anomalous interior vertices; PostGIS repairs the resulting self-overlaps.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

REPEAT_TOLERANCE_DEGREES = 1e-9
MIN_AREA_SQUARE_DEGREES = 1e-9


class DegenerateFootprint(ValueError):
    """The perimeter does not enclose an area (too few distinct vertices, or all in a line)."""


@dataclass(frozen=True)
class FootprintPolygon:
    ring: np.ndarray                 # (n, 2) closed ring of (lon, lat); lon may lie outside -180..180
    pole: int                        # +1 or -1 if the perimeter encircles that pole, else 0
    crosses_antimeridian: bool       # the ring extends past +/-180, so it will be split on load

    @property
    def vertex_count(self) -> int:
        return len(self.ring) - 1

    @property
    def wkt(self) -> str:
        points = ", ".join(f"{x:.6f} {y:.6f}" for x, y in self.ring)
        return f"POLYGON(({points}))"


def normalize_longitude(lon):
    """East longitude in degrees mapped into [-180, 180)."""
    return (np.asarray(lon, dtype=np.float64) + 180.0) % 360.0 - 180.0


def _wrap_delta(delta):
    """A longitude difference mapped to the shortest signed equivalent, in [-180, 180)."""
    return (np.asarray(delta, dtype=np.float64) + 180.0) % 360.0 - 180.0


def _drop_repeats(lat: np.ndarray, lon: np.ndarray):
    """Remove consecutive repeated vertices, and a final vertex that repeats the first."""
    keep = [0]
    for i in range(1, len(lat)):
        same_lat = abs(lat[i] - lat[keep[-1]]) <= REPEAT_TOLERANCE_DEGREES
        same_lon = abs(_wrap_delta(lon[i] - lon[keep[-1]])) <= REPEAT_TOLERANCE_DEGREES
        if not (same_lat and same_lon):
            keep.append(i)
    if len(keep) > 1:
        first, last = keep[0], keep[-1]
        if (abs(lat[last] - lat[first]) <= REPEAT_TOLERANCE_DEGREES
                and abs(_wrap_delta(lon[last] - lon[first])) <= REPEAT_TOLERANCE_DEGREES):
            keep.pop()
    return lat[keep], lon[keep]


def _shoelace_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))


def build_footprint_polygon(vertices) -> FootprintPolygon:
    """Polygon (in unwrapped longitude) for a footprint's perimeter vertices.

    `vertices` is anything with "latitude" and "longitude" fields, such as the
    array read_rdr() returns. Raises DegenerateFootprint if the perimeter
    encloses no area, and ValueError if it winds more than once around a pole."""
    lat = np.asarray(vertices["latitude"], dtype=np.float64)
    lon = np.asarray(vertices["longitude"], dtype=np.float64)
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise ValueError("footprint has non-finite coordinates")
    if len(lat) == 0:
        raise DegenerateFootprint("footprint has no vertices")

    lat, lon = _drop_repeats(lat, lon)
    if len(lat) < 3:
        raise DegenerateFootprint(f"footprint has only {len(lat)} distinct vertices")

    steps = _wrap_delta(np.diff(lon))                 # shortest signed step between neighbours
    closing = float(_wrap_delta(lon[0] - lon[-1]))    # last vertex back to the first
    turns = int(round((steps.sum() + closing) / 360.0))
    if abs(turns) > 1:
        raise ValueError(f"perimeter winds {abs(turns)} times around the pole")

    unwrapped = lon[0] + np.concatenate(([0.0], np.cumsum(steps)))
    points = np.column_stack([unwrapped, lat])
    pole = 0
    if turns:
        pole = 1 if lat.mean() > 0 else -1
        far = unwrapped[0] + 360.0 * turns            # the first vertex, one full turn along
        edge = 90.0 * pole
        points = np.vstack([points, [far, lat[0]], [far, edge], [unwrapped[0], edge]])

    centre = 0.5 * (points[:, 0].min() + points[:, 0].max())
    points[:, 0] -= 360.0 * round(centre / 360.0)     # centre the ring on longitude 0
    ring = np.vstack([points, points[0]])

    if abs(_shoelace_area(ring)) < MIN_AREA_SQUARE_DEGREES:
        raise DegenerateFootprint("perimeter encloses no area")
    crosses = bool(ring[:, 0].min() < -180.0 - 1e-9 or ring[:, 0].max() > 180.0 + 1e-9)
    return FootprintPolygon(ring=ring, pole=pole, crosses_antimeridian=crosses)


def footprint_wkt(vertices) -> str:
    return build_footprint_polygon(vertices).wkt


def footprint_record(footprint) -> dict:
    """Parameters for loading one footprint (a rdr_reader.Footprint) into the database.

    Matching a footprint to its CDR row uses partition + met, and start_time as
    a cross-check, since MET alone repeats between clock partitions."""
    polygon = build_footprint_polygon(footprint.vertices)
    return {
        "source_file": Path(footprint.path).name.lower(),
        "partition": footprint.partition,
        "met": footprint.met,
        "start_time": footprint.start_time,
        "stop_time": footprint.stop_time,
        "stop_met": footprint.stop_met,
        "wkt": polygon.wkt,
        "pole": polygon.pole,
        "crosses_antimeridian": polygon.crosses_antimeridian,
        "vertex_count": polygon.vertex_count,
    }
