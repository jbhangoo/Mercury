"""
Tests for app.db.access: the statements the API and the loaders run, and the search
around a point. Tests that use a database need TEST_DATABASE_URL (see tests/conftest.py).
"""
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.db import access
from app.db.access import (
    FOOTPRINT_TIME_TOLERANCE, MERCURY_RADIUS_KM, WEIGHT_SIGMA_FRACTION,
    db_xrs_find_for_footprint_by_time, db_xrs_nearest_by_time, db_xrs_set_footprint,
    get_max_xrs_search_radius_km,
    find_xrs_observations_near, near_observations_statement,
)

KM_PER_DEGREE = MERCURY_RADIUS_KM * math.pi / 180


# --- no database ------------------------------------------------------------------------------

def test_radius_matches_the_value_the_loaders_use():
    consts = pytest.importorskip("database.pds2db.consts")
    assert MERCURY_RADIUS_KM == consts.MERCURY_RADIUS_KM


def test_max_search_radius_is_exposed_by_database_access():
    assert get_max_xrs_search_radius_km() == 2500.0


def test_search_statement_describes_the_overlap_test_and_the_weight():
    sql = str(near_observations_statement().compile(dialect=postgresql.dialect()))
    assert "acos" in sql and "radians" in sql and "exp(" in sql
    assert "footprint_radius_km IS NOT NULL" in sql and "boresight_lat IS NOT NULL" in sql
    assert "data_quality &" in sql                                       # bit 0 of the quality word
    assert "distance_km <= candidates.footprint_radius_km +" in sql
    assert "ORDER BY weight DESC" in sql and "LIMIT" in sql
    assert "ST_" not in sql                                              # plain numbers, no PostGIS


def test_search_passes_its_parameters_and_returns_the_rows():
    seen = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return ["row"]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, parameters):
            seen["parameters"] = parameters
            return Result()

    class Engine:
        def connect(self):
            return Connection()

    assert find_xrs_observations_near(Engine(), -80.5, 30, 150, 11) == ["row"]
    assert seen["parameters"] == {"lon": -80.5, "lat": 30, "roi_radius_km": 150, "limit": 11}


# --- searching around a point (database) -------------------------------------------------------

def ids(rows):
    return [row["id"] for row in rows]


def test_overlap_is_distance_to_the_boresight_point_against_both_radii(xrs_engine, insert_xrs):
    on_point = insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100)
    near = insert_xrs(boresight_lat=0, boresight_lon=1, footprint_radius_km=100)          # 42.6 km away
    far = insert_xrs(boresight_lat=0, boresight_lon=3, footprint_radius_km=100)           # 127.7 km away
    point_only = find_xrs_observations_near(xrs_engine, 0, 0, 0, 50)
    assert set(ids(point_only)) == {on_point, near}                                       # far is outside its own radius
    with_region = find_xrs_observations_near(xrs_engine, 0, 0, 50, 50)
    assert set(ids(with_region)) == {on_point, near, far}                                 # 127.7 <= 100 + 50
    assert far not in ids(find_xrs_observations_near(xrs_engine, 0, 0, 27, 50))           # 127.7 > 100 + 27


def test_rows_carry_distance_and_gaussian_weight_and_come_back_strongest_first(xrs_engine, insert_xrs):
    far = insert_xrs(boresight_lat=0, boresight_lon=2, footprint_radius_km=200)
    on_point = insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100)
    near = insert_xrs(boresight_lat=0, boresight_lon=1, footprint_radius_km=100)
    rows = find_xrs_observations_near(xrs_engine, 0, 0, 0, 50)
    assert ids(rows) == [on_point, near, far]
    assert rows[0]["distance_km"] == pytest.approx(0, abs=1e-6) and rows[0]["weight"] == pytest.approx(1.0)
    for row in rows[1:]:
        sigma = WEIGHT_SIGMA_FRACTION * row["footprint_radius_km"]
        assert row["distance_km"] == pytest.approx(KM_PER_DEGREE * (1 if row["id"] == near else 2), rel=1e-6)
        assert row["weight"] == pytest.approx(math.exp(-row["distance_km"] ** 2 / (2 * sigma ** 2)), rel=1e-6)
    assert rows[0]["weight"] > rows[1]["weight"] > rows[2]["weight"]
    assert math.exp(-2) == pytest.approx(0.1353, abs=1e-4)                                # the weight at the radius itself


def test_weight_at_the_edge_of_the_certain_circle_is_exp_minus_two(xrs_engine, insert_xrs):
    insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=KM_PER_DEGREE)       # radius is 1 degree
    # The radius is stored as a 4-byte real, so a distance exactly equal to it can fall either side
    # of the test; a hundredth of a kilometer of region radius keeps this about the weight.
    (row,) = find_xrs_observations_near(xrs_engine, 0, 1.0, 0.01, 5)
    assert row["weight"] == pytest.approx(math.exp(-2), rel=1e-5)


def test_observations_that_are_not_valid_are_never_returned(xrs_engine, insert_xrs):
    good = insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100)
    insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100, data_quality=1)         # length mismatch
    insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100, data_quality=3)
    insert_xrs(boresight_lat=0, boresight_lon=0)                                                 # footprint not loaded
    insert_xrs()                                                                                 # boresight missed the planet
    still_valid = insert_xrs(boresight_lat=0, boresight_lon=0, footprint_radius_km=100, data_quality=2)
    assert set(ids(find_xrs_observations_near(xrs_engine, 0, 0, 500, 50))) == {good, still_valid}  # only bit 0 is defined


def test_distances_wrap_correctly_at_the_antimeridian(xrs_engine, insert_xrs):
    across = insert_xrs(boresight_lat=0, boresight_lon=-179.9, footprint_radius_km=50)
    (row,) = find_xrs_observations_near(xrs_engine, 179.9, 0, 0, 50)
    assert row["id"] == across and row["distance_km"] == pytest.approx(0.2 * KM_PER_DEGREE, rel=1e-6)
    assert find_xrs_observations_near(xrs_engine, 0, 0, 0, 50) == []


def test_distances_are_right_near_a_pole(xrs_engine, insert_xrs):
    opposite = insert_xrs(boresight_lat=89.9, boresight_lon=180, footprint_radius_km=50)   # 0.2 degrees away over the pole
    insert_xrs(boresight_lat=89.9, boresight_lon=90, footprint_radius_km=5)                # also 0.14 degrees, but radius too small
    rows = find_xrs_observations_near(xrs_engine, 0, 89.9, 0, 50)
    assert opposite in ids(rows)
    row = next(r for r in rows if r["id"] == opposite)
    assert row["distance_km"] == pytest.approx(0.2 * KM_PER_DEGREE, rel=1e-4)


def test_limit_keeps_the_highest_weights_and_ties_go_to_the_latest_observation(xrs_engine, insert_xrs):
    closest = insert_xrs(boresight_lat=0, boresight_lon=0.1, footprint_radius_km=300)
    older = insert_xrs(boresight_lat=0, boresight_lon=1, footprint_radius_km=300, observed_start="2013-04-10T00:00:00Z",
                       observed_end="2013-04-10T00:05:00Z")
    newer = insert_xrs(boresight_lat=0, boresight_lon=1, footprint_radius_km=300)
    insert_xrs(boresight_lat=0, boresight_lon=4, footprint_radius_km=300)
    assert ids(find_xrs_observations_near(xrs_engine, 0, 0, 0, 3)) == [closest, newer, older]
    assert ids(find_xrs_observations_near(xrs_engine, 0, 0, 0, 2)) == [closest, newer]


def test_search_returns_the_columns_the_api_needs(xrs_engine, insert_xrs):
    insert_xrs(boresight_lat=10, boresight_lon=20, footprint_radius_km=100, gpc1_mg_spectrum=[3] * 244)
    (row,) = find_xrs_observations_near(xrs_engine, 20, 10, 0, 5)
    for key in ("id", "met", "observed_start", "boresight_lat", "boresight_lon", "footprint_radius_km",
                "gpc1_mg_spectrum", "housekeeping", "distance_km", "weight"):
        assert key in row
    assert row["gpc1_mg_spectrum"] == [3] * 244


# --- matching footprints to CDR rows (database) -------------------------------------------------

START = datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc)


@contextmanager
def connection_of(engine):
    with engine.begin() as connection:
        yield connection


def test_footprint_candidates_are_ordered_by_nearest_start_time(xrs_engine, insert_xrs):
    near = insert_xrs(met=7184993, observed_start=START + timedelta(milliseconds=250))
    farther = insert_xrs(met=7184992, observed_start=START - timedelta(seconds=1))
    insert_xrs(met=7184994, observed_start=START + timedelta(seconds=3))
    with connection_of(xrs_engine) as connection:
        rows = db_xrs_find_for_footprint_by_time(connection, START)
        assert [row["id"] for row in rows] == [near, farther]


def test_footprint_candidates_use_the_two_second_tolerance(xrs_engine, insert_xrs):
    inside = insert_xrs(met=7184992, observed_start=START + FOOTPRINT_TIME_TOLERANCE)
    insert_xrs(
        met=7184993,
        observed_start=START + FOOTPRINT_TIME_TOLERANCE + timedelta(microseconds=1),
    )
    with connection_of(xrs_engine) as connection:
        assert [row["id"] for row in db_xrs_find_for_footprint_by_time(connection, START)] == [inside]


def test_setting_a_footprint_stores_radius_and_partition(xrs_engine, insert_xrs):
    row_id = insert_xrs(met=7184992, observed_start=START, boresight_lat=64.6, boresight_lon=-169.1)
    with connection_of(xrs_engine) as connection:
        db_xrs_set_footprint(connection, row_id, 2, 302.94)
        row = db_xrs_find_for_footprint_by_time(connection, START)[0]
    assert row["sclk_partition"] == 2 and row["footprint_radius_km"] == pytest.approx(302.94, rel=1e-6)


def test_nearest_rows_by_time_are_ordered_and_limited_to_a_day(xrs_engine, insert_xrs):
    insert_xrs(met=1, observed_start=START + timedelta(seconds=30))
    insert_xrs(met=2, observed_start=START - timedelta(seconds=10))
    insert_xrs(met=3, observed_start=START + timedelta(hours=5))
    insert_xrs(met=4, observed_start=START + timedelta(days=2))                      # too far
    with connection_of(xrs_engine) as connection:
        assert [r["met"] for r in db_xrs_nearest_by_time(connection, START)] == [2, 1, 3]
        assert [r["met"] for r in db_xrs_nearest_by_time(connection, START, count=1)] == [2]
        assert db_xrs_nearest_by_time(connection, START + timedelta(days=30)) == []