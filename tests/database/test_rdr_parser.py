"""Tests for rdr_parser: the radius of the circle around the boresight point that lies inside a footprint."""
import math

import numpy as np
import pytest

from database.database_consts import XRS_ARCHIVE_DIR
from database.pds2db.rdr_parser import (
    boresight_inside_perimeter, footprint_radius, nearest_vertex_distance_km, unit_vectors,
)
from database.pds2db.rdr_reader import RDRReader
from fake_footprint import MERCURY_RADIUS_KM, destination, ring, vertices

REAL_CSV = (
    XRS_ARCHIVE_DIR / "footprints" / "2013" / "04" / "02" / "00"
    / "xrs_fp_2_007184992.csv"
)
KM_PER_DEGREE = MERCURY_RADIUS_KM * math.pi / 180


def real_vertices():
    missing = [path for path in (REAL_CSV, REAL_CSV.with_suffix(".xml")) if not path.is_file()]
    if missing:
        pytest.skip(f"real footprint archive file(s) are not available: {', '.join(map(str, missing))}")
    return RDRReader().read(REAL_CSV)


# --- distances -------------------------------------------------------------------------------------

def test_unit_vectors_are_unit_length_and_accept_longitudes_over_180():
    points = unit_vectors([0, 90, -45, 30], [0, 0, 190, 350])
    np.testing.assert_allclose(np.linalg.norm(points, axis=1), 1.0)
    np.testing.assert_allclose(unit_vectors(30, 190), unit_vectors(30, -170), atol=1e-12)


def test_nearest_vertex_distance_is_a_great_circle_distance_in_km():
    perimeter = vertices([(0, 1), (0, 5), (5, 5)])
    assert nearest_vertex_distance_km(0, 0, perimeter) == pytest.approx(KM_PER_DEGREE, rel=1e-9)
    assert nearest_vertex_distance_km(0, 0, perimeter, radius_km=1000.0) == pytest.approx(1000 * math.pi / 180, rel=1e-9)


def test_distance_to_a_circle_of_vertices_is_its_radius():
    assert nearest_vertex_distance_km(30, 40, ring(30, 40, 300)) == pytest.approx(300, abs=0.01)


# --- inside, and the radius that is stored ------------------------------------------------------------

def test_boresight_at_the_center_gives_the_ring_radius():
    result = footprint_radius(30, 40, ring(30, 40, 300))
    assert result.inside is True and result.radius_km == pytest.approx(300, abs=0.01) and result.vertex_count == 120


def test_off_center_boresight_gets_the_distance_to_the_nearest_vertex():
    boresight = destination(30, 40, 90, 100)                         # 100 km east of the ring's center
    result = footprint_radius(*boresight, ring(30, 40, 300, count=720))
    assert result.inside is True and result.radius_km == pytest.approx(200, abs=0.2)


def test_boresight_outside_the_perimeter_is_not_inside():
    boresight = destination(30, 40, 90, 400)                         # 100 km beyond the edge
    result = footprint_radius(*boresight, ring(30, 40, 300))
    assert result.inside is False
    assert not boresight_inside_perimeter(*boresight, ring(30, 40, 300))


@pytest.mark.parametrize("clockwise", [False, True])
def test_direction_of_the_perimeter_does_not_matter(clockwise):
    assert footprint_radius(30, 40, ring(30, 40, 300, clockwise=clockwise)).inside is True


def test_closing_vertex_that_repeats_the_first_makes_no_difference():
    perimeter = ring(30, 40, 300)
    closed = vertices(list(zip(perimeter["latitude"], perimeter["longitude"])) + [(perimeter["latitude"][0], perimeter["longitude"][0])])
    assert footprint_radius(30, 40, closed) == footprint_radius(30, 40, perimeter).__class__(
        radius_km=pytest.approx(300, abs=0.01), inside=True, vertex_count=121)


@pytest.mark.parametrize("lat, lon", [(10, 180), (10, 179.5), (10, -179.5), (0, 0), (-60, 359.9)])
def test_works_across_the_antimeridian_and_the_zero_360_wrap(lat, lon):
    result = footprint_radius(lat, lon, ring(lat, lon, 400))
    assert result.inside is True and result.radius_km == pytest.approx(400, abs=0.01)


def test_longitude_convention_of_the_boresight_does_not_matter():
    perimeter = ring(20, 190, 300)                                   # footprint files use east longitude 0..360
    assert footprint_radius(20, 190, perimeter).radius_km == pytest.approx(footprint_radius(20, -170, perimeter).radius_km)


@pytest.mark.parametrize("lat", [90.0, -90.0, 89.5, -89.5])
def test_footprints_around_a_pole(lat):
    perimeter = ring(lat, 0, 400, count=180)
    result = footprint_radius(lat, 0, perimeter)
    assert result.inside is True and result.radius_km == pytest.approx(400, abs=0.01)
    off_pole = destination(lat, 0, 90, 100) if abs(lat) == 90 else (lat, 0)
    assert footprint_radius(*off_pole, perimeter).inside is True


def test_perimeter_that_does_not_surround_the_point_is_not_inside_even_when_close():
    side = vertices([(0, 5), (0, 6), (1, 6), (1, 5)])                # a small box away from the origin
    assert footprint_radius(0.5, 0, side).inside is False


def test_vertex_spike_inside_the_perimeter_shrinks_the_radius():
    """An anomalous interior vertex (the SIS mentions them at the poles) counts like any other vertex."""
    points = list(zip(*[ring(30, 40, 300)[name] for name in ("latitude", "longitude")]))
    spike = destination(30, 40, 10, 50)
    points.insert(10, spike)                                         # one vertex 50 km from the boresight point
    result = footprint_radius(30, 40, vertices(points))
    assert result.inside is True and result.radius_km == pytest.approx(50, abs=0.01)


def test_boresight_on_the_perimeter_is_not_usable():
    perimeter = ring(30, 40, 300)
    on_vertex = (perimeter["latitude"][3], perimeter["longitude"][3])
    result = footprint_radius(*on_vertex, perimeter)
    assert result.radius_km == pytest.approx(0, abs=1e-6) and result.inside is False


def test_a_boresight_point_a_quarter_planet_away_is_not_inside():
    assert footprint_radius(-30, 220, ring(30, 40, 300)).inside is False


# --- validation -------------------------------------------------------------------------------------

def test_too_few_vertices_or_bad_numbers_are_rejected():
    with pytest.raises(ValueError, match="only 2 vertices"):
        footprint_radius(0, 0, vertices([(0, 1), (1, 1)]))
    with pytest.raises(ValueError, match="non-finite"):
        footprint_radius(0, 0, vertices([(0, 1), (1, 1), (1, float("nan"))]))
    with pytest.raises(ValueError, match="not finite"):
        footprint_radius(float("nan"), 0, ring(0, 0, 100))
    with pytest.raises(ValueError, match="outside -90..90"):
        footprint_radius(91, 0, ring(0, 0, 100))


# --- a complete real footprint (xrs_fp_2_007184992) -----------------------------------------------------
# The boresight for this MET was not available, so the area centroid stands in for it.
CENTROID = (64.6099, 190.8911)


def test_real_footprint_radius_at_its_centroid():
    result = footprint_radius(*CENTROID, real_vertices())
    assert result.inside is True and result.vertex_count == 357
    assert result.radius_km == pytest.approx(302.94, abs=0.05)               # the nearest of the vertices


def test_real_footprint_gives_the_same_answer_for_either_longitude_convention():
    assert footprint_radius(CENTROID[0], CENTROID[1] - 360, real_vertices()).radius_km == pytest.approx(302.94, abs=0.05)


@pytest.mark.parametrize("point, inside", [
    ((56.0, 192.0), True), ((50.0, -170.0), True),                           # near the southern edge
    ((30.0, 10.0), False), ((80.0, 190.0), False), ((64.6, 150.0), False),
])
def test_real_footprint_inside_and_outside_points(point, inside):
    assert footprint_radius(*point, real_vertices()).inside is inside


def test_real_footprint_radius_grows_toward_the_middle_and_shrinks_toward_the_edge():
    perimeter = real_vertices()
    middle = footprint_radius(*CENTROID, perimeter).radius_km
    near_edge = footprint_radius(50.0, -170.0, perimeter).radius_km
    assert near_edge < 20 < 250 < middle