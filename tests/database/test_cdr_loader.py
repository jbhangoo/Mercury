"""
Tests for loading CDR day files into the xrs table: the boresight columns, and how a reload treats
a footprint radius that was measured from them. Needs TEST_DATABASE_URL (see tests/conftest.py).
"""
import pytest
from sqlalchemy import text

from database.pds2db import pds_consts
from database.pds2db.cdr_loader import CDRLoader
from server.app.db.access import db_xrs_set_footprint
from fake_cdr import POINTS, write_day


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT met, boresight_lat, boresight_lon, footprint_radius_km, sclk_partition, intersection, "
            "data_quality, processing_version FROM xrs ORDER BY met")).mappings().all()


def test_boresight_columns_come_from_the_boresight_vector(xrs_engine, tmp_path):
    dat, _ = write_day(tmp_path, "xrscdr2013101")
    CDRLoader(xrs_engine).load_file(dat)
    loaded = rows(xrs_engine)
    assert len(loaded) == len(POINTS)
    first = loaded[0]
    assert (first["boresight_lon"], first["boresight_lat"]) == (pytest.approx(-120.0, abs=1e-3), pytest.approx(35.0, abs=1e-3))
    assert loaded[1]["boresight_lat"] == pytest.approx(-80.0, abs=1e-3)
    assert -180 <= loaded[2]["boresight_lon"] <= 180 and loaded[2]["boresight_lon"] == pytest.approx(179.9, abs=1e-3)
    assert (loaded[3]["boresight_lat"], loaded[3]["boresight_lon"]) == (None, None)          # no intersection
    assert (loaded[4]["boresight_lat"], loaded[4]["boresight_lon"]) == (None, None)          # vector of the wrong length
    assert all(r["footprint_radius_km"] is None and r["sclk_partition"] is None for r in loaded)
    assert {r["processing_version"] for r in loaded} == {pds_consts.LOADER_VERSION}


def test_reloading_a_file_does_not_duplicate_rows_and_keeps_the_footprint_radius(xrs_engine, tmp_path):
    dat, _ = write_day(tmp_path, "xrscdr2013101")
    loader = CDRLoader(xrs_engine)
    loader.load_file(dat)
    with xrs_engine.begin() as connection:
        row_id = connection.execute(text("SELECT id FROM xrs WHERE met = 1000000")).scalar_one()
        db_xrs_set_footprint(connection, row_id, 2, 303.0)
    loader.load_file(dat)
    assert len(rows(xrs_engine)) == len(POINTS)
    first = rows(xrs_engine)[0]
    assert first["footprint_radius_km"] == pytest.approx(303.0) and first["sclk_partition"] == 2


def test_radius_is_cleared_when_a_reload_changes_the_boresight_point(xrs_engine, tmp_path):
    dat, _ = write_day(tmp_path, "xrscdr2013101")
    loader = CDRLoader(xrs_engine)
    loader.load_file(dat)
    with xrs_engine.begin() as connection:
        for met in (1000000, 1000001):
            row_id = connection.execute(text("SELECT id FROM xrs WHERE met = :met"), {"met": met}).scalar_one()
            db_xrs_set_footprint(connection, row_id, 2, 303.0)
    moved = [(-100.0, 35.0, *POINTS[0][2:])] + list(POINTS[1:])                   # first observation now points elsewhere
    write_day(tmp_path, "xrscdr2013101", points=moved)
    loader.load_file(dat)
    loaded = rows(xrs_engine)
    assert loaded[0]["boresight_lon"] == pytest.approx(-100.0, abs=1e-3) and loaded[0]["footprint_radius_km"] is None
    assert loaded[1]["footprint_radius_km"] == pytest.approx(303.0)               # unchanged observation keeps its radius


def test_data_quality_flags_are_stored(xrs_engine, tmp_path):
    dat, _ = write_day(tmp_path, "xrscdr2013101")
    CDRLoader(xrs_engine).load_file(dat)
    assert {r["data_quality"] for r in rows(xrs_engine)} == {0}