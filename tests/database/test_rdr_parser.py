"""
Tests for rdr_parser (pure Python) and the PostGIS expression in rdr_consts that
finishes the geometry (needs TEST_DATABASE_URL, a PostGIS 3.2+ database; those
tests are skipped without it and create nothing).
"""
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database.pds2db.rdr_consts import FOOTPRINT_GEOMETRY_SQL
from database.pds2db.rdr_parser import (
    DegenerateFootprint, _wrap_delta, build_footprint_polygon, footprint_record, footprint_wkt,
    normalize_longitude,
)
from database.pds2db.rdr_reader import RDRReader, VERTEX_DTYPE

DATA = Path(__file__).parent / "data"
REAL_CSV = DATA / "xrs_fp_2_007184992.csv"          # a complete real footprint (with its label beside it)
URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


def vertices(pairs):
    """Structured array from (lat, lon) pairs."""
    array = np.empty(len(pairs), dtype=VERTEX_DTYPE)
    array["latitude"], array["longitude"] = zip(*pairs) if pairs else ((), ())
    return array


def real_vertices():
    return RDRReader().read(REAL_CSV)


def cap(lat, step=10, descending=False):
    """A ring of vertices all at one latitude, all the way round the planet."""
    lons = range(350, -1, -step) if descending else range(0, 360, step)
    return vertices([(lat, float(lon)) for lon in lons])


# --- longitude helpers --------------------------------------------------------------------------

def test_normalize_longitude_maps_into_minus_180_to_180():
    np.testing.assert_allclose(normalize_longitude([0, 90, 179.9, 180, 181.85, 270, 359.9, 360, -190]),
                               [0, 90, 179.9, -180, -178.15, -90, -0.1, 0, 170])


# --- a complete real footprint -----------------------------------------------------------------------
# xrs_fp_2_007184992: 357 vertices, longitudes 165.68 to 223.22, so it straddles the antimeridian.

def test_real_footprint_is_read_whole_and_closed():
    footprint = RDRReader().read_footprint(REAL_CSV)
    assert (footprint.partition, footprint.met, len(footprint.vertices)) == (2, 7184992, 357)
    assert footprint.vertices[0] == footprint.vertices[-1]                     # the file repeats its first vertex


def test_real_footprint_perimeter_is_one_continuous_ring():
    v = real_vertices()
    step_lat = np.diff(v["latitude"])
    step_lon = _wrap_delta(np.diff(v["longitude"])) * np.cos(np.radians(v["latitude"][:-1]))
    assert np.hypot(step_lat, step_lon).max() < 0.5                            # no gaps or jumps (degrees)


def test_real_footprint_straddles_the_antimeridian_and_is_shifted_into_range():
    polygon = build_footprint_polygon(real_vertices())
    assert (polygon.pole, polygon.crosses_antimeridian, polygon.vertex_count) == (0, True, 356)
    np.testing.assert_array_equal(polygon.ring[0], polygon.ring[-1])
    np.testing.assert_allclose([polygon.ring[:, 0].min(), polygon.ring[:, 0].max()], [165.68 - 360, 223.22 - 360])
    np.testing.assert_allclose([polygon.ring[:, 1].min(), polygon.ring[:, 1].max()], [49.31, 76.63])
    assert polygon.wkt.startswith("POLYGON((-178.150000 76.630000, -176.920000 76.630000,")


# --- shapes the real data can take ----------------------------------------------------------------

def test_ring_crossing_zero_360_is_made_continuous():
    polygon = build_footprint_polygon(vertices([(10, 359), (10, 1), (20, 1), (20, 359)]))
    assert polygon.ring[:, 0].min() == -1 and polygon.ring[:, 0].max() == 1
    assert polygon.crosses_antimeridian is False


def test_ring_crossing_the_antimeridian_is_flagged():
    polygon = build_footprint_polygon(vertices([(0, 170), (0, 190), (10, 190), (10, 170)]))
    assert polygon.crosses_antimeridian is True and polygon.pole == 0
    assert polygon.ring[:, 0].max() - polygon.ring[:, 0].min() == 20


@pytest.mark.parametrize("lat, descending, pole", [(80, False, 1), (80, True, 1), (-75, False, -1), (-75, True, -1)])
def test_ring_round_a_pole_is_closed_along_that_pole(lat, descending, pole):
    polygon = build_footprint_polygon(cap(lat, descending=descending))
    assert polygon.pole == pole and polygon.crosses_antimeridian is True
    assert set(polygon.ring[-4:-1, 1]) >= {90.0 * pole}
    area = abs(0.5 * (np.dot(polygon.ring[:-1, 0], polygon.ring[1:, 1]) - np.dot(polygon.ring[1:, 0], polygon.ring[:-1, 1])))
    assert area == pytest.approx(360 * (90 - abs(lat)))


def test_closed_ring_and_repeated_vertices_give_the_same_polygon():
    base = [(0, 10), (0, 20), (10, 20), (10, 10)]
    reference = footprint_wkt(vertices(base))
    assert footprint_wkt(vertices(base + [base[0]])) == reference
    assert footprint_wkt(vertices([base[0]] + base)) == reference
    assert footprint_wkt(vertices([base[0], base[1], base[1], base[2], base[3]])) == reference


@pytest.mark.parametrize("pairs", [
    [], [(0, 0)], [(0, 0), (1, 1)], [(5, 5)] * 4,
    [(0, 0), (0, 5), (0, 10)],                      # all on one line: no area
])
def test_perimeters_without_area_are_rejected(pairs):
    with pytest.raises(DegenerateFootprint):
        build_footprint_polygon(vertices(pairs))


def test_ring_winding_twice_is_rejected():
    twice = vertices([(80.0, float(lon)) for lon in range(0, 720, 10)])
    with pytest.raises(ValueError, match="winds 2 times"):
        build_footprint_polygon(twice)


def test_non_finite_coordinates_are_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        build_footprint_polygon(vertices([(0, 0), (0, 5), (5, float("nan"))]))


def test_footprint_record_carries_what_the_loader_needs(tmp_path):
    csv_path = tmp_path / "XRS_FP_2_007184992.csv"
    angles = np.linspace(0, 2 * np.pi, 357, endpoint=False)               # 357 vertices, as the label says
    csv_path.write_text("".join(f"{20 + 3 * np.sin(a):7.3f},{100 + 4 * np.cos(a):7.3f}\r\n" for a in angles),
                        newline="")
    shutil.copy(DATA / "xrs_fp_2_007184992.xml", tmp_path / "XRS_FP_2_007184992.xml")
    record = footprint_record(RDRReader().read_footprint(csv_path))
    assert record["source_file"] == "xrs_fp_2_007184992.csv"
    assert (record["partition"], record["met"], record["stop_met"]) == (2, 7184992, 7185192)
    assert record["start_time"] == datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc)
    assert record["wkt"].startswith("POLYGON((") and record["pole"] == 0 and record["vertex_count"] == 357
    assert record["crosses_antimeridian"] is False


# --- finishing the geometry in PostGIS --------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    url = make_url(URL)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(url)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def finish(conn, wkt, *points):
    """(geometry facts, [does the result contain each (lon, lat) in points])."""
    contains = "".join(f", ST_Contains(g, ST_SetSRID(ST_MakePoint({lon}, {lat}), 910001))"
                       for lon, lat in points)
    row = conn.execute(text(
        f"WITH f AS (SELECT {FOOTPRINT_GEOMETRY_SQL} AS g) "
        f"SELECT ST_GeometryType(g), ST_NumGeometries(g), ST_IsValid(g), ST_SRID(g), ST_Area(g), "
        f"ST_XMin(g), ST_XMax(g), ST_YMin(g), ST_YMax(g), ST_IsEmpty(g){contains} FROM f"), {"wkt": wkt}).one()
    facts = dict(zip(("type", "parts", "valid", "srid", "area", "xmin", "xmax", "ymin", "ymax", "empty"), row))
    return facts, list(row[10:])


@needs_db
def test_real_footprint_is_split_into_two_valid_parts_at_the_antimeridian(conn):
    polygon = build_footprint_polygon(real_vertices())
    inside_points = [(-175, 60), (170, 70), (-160, 70), (-140, 72), (-170, 66), (-170, 50)]
    outside_points = [(175, 60), (-150, 60), (0, 0), (-137, 72)]
    facts, inside = finish(conn, polygon.wkt, *inside_points, *outside_points)
    assert (facts["type"], facts["parts"], facts["valid"], facts["srid"]) == ("ST_MultiPolygon", 2, True, 910001)
    assert (facts["xmin"], facts["xmax"]) == (-180.0, 180.0)
    assert (facts["ymin"], facts["ymax"]) == (49.31, 76.63)
    assert facts["area"] == pytest.approx(871.226, abs=0.01)                    # same area as the uncut ring
    assert inside == [True] * len(inside_points) + [False] * len(outside_points)


@needs_db
def test_real_footprint_is_found_by_regions_on_either_side_of_the_antimeridian(conn):
    polygon = build_footprint_polygon(real_vertices())
    query = text(f"WITH f AS (SELECT {FOOTPRINT_GEOMETRY_SQL} AS g) SELECT "
                 "ST_Intersects(g, ST_MakeEnvelope(175, 65, 176, 66.5, 910001)), "
                 "ST_Intersects(g, ST_MakeEnvelope(-170, 65, -169, 66, 910001)), "
                 "ST_Intersects(g, ST_MakeEnvelope(0, 0, 1, 1, 910001)) FROM f")
    assert tuple(conn.execute(query, {"wkt": polygon.wkt}).one()) == (True, True, False)


@needs_db
def test_footprint_across_the_antimeridian_is_split_into_two_valid_parts(conn):
    polygon = build_footprint_polygon(vertices([(0, 170), (0, 190), (10, 190), (10, 170)]))
    facts, inside = finish(conn, polygon.wkt, (175, 5), (-175, 5), (0, 5))
    assert (facts["parts"], facts["valid"]) == (2, True)
    assert (facts["xmin"], facts["xmax"]) == (-180.0, 180.0)
    assert facts["area"] == pytest.approx(200.0)                    # nothing lost or duplicated in the cut
    assert inside == [True, True, False]


@needs_db
@pytest.mark.parametrize("lat, descending, pole", [(80, False, 90), (-75, True, -90)])
def test_polar_cap_covers_the_pole_and_the_whole_circle(conn, lat, descending, pole):
    polygon = build_footprint_polygon(cap(lat, descending=descending))
    sign = 1 if pole > 0 else -1
    facts, inside = finish(conn, polygon.wkt, (0, pole - sign * 0.1), (179, pole - sign * 5),
                           (-179, pole - sign * 5), (0, lat - sign * 10))
    assert facts["valid"] and not facts["empty"]
    assert (facts["xmin"], facts["xmax"]) == (-180.0, 180.0)
    assert facts["area"] == pytest.approx(360 * (90 - abs(lat)))
    assert inside == [True, True, True, False]
    assert facts["ymax" if pole > 0 else "ymin"] == pole


@needs_db
def test_self_intersecting_ring_is_repaired_not_rejected(conn):
    facts, _ = finish(conn, "POLYGON((0 0, 10 10, 10 0, 0 10, 0 0))")      # a bow tie
    assert facts["valid"] and not facts["empty"] and facts["area"] == pytest.approx(50.0)


@needs_db
def test_polygon_without_area_gives_an_empty_geometry_for_the_loader_to_reject(conn):
    facts, _ = finish(conn, "POLYGON((0 0, 5 0, 10 0, 0 0))")
    assert facts["empty"] is True


@needs_db
def test_region_queries_find_a_footprint_from_either_side_of_the_antimeridian(conn):
    polygon = build_footprint_polygon(vertices([(0, 170), (0, 190), (10, 190), (10, 170)]))
    query = text(f"WITH f AS (SELECT {FOOTPRINT_GEOMETRY_SQL} AS g) SELECT "
                 "ST_Intersects(g, ST_MakeEnvelope(178, 2, 179, 4, 910001)), "
                 "ST_Intersects(g, ST_MakeEnvelope(-179, 2, -178, 4, 910001)), "
                 "ST_Intersects(g, ST_MakeEnvelope(0, 2, 1, 4, 910001)) FROM f")
    assert tuple(conn.execute(query, {"wkt": polygon.wkt}).one()) == (True, True, False)