"""
Tests for cdr_loader against a real PostGIS database.

Set TEST_DATABASE_URL to a database that has the postgis extension; the tests
create and drop their own throw-away schema, so existing tables are untouched.
The table definition is extracted from DB_Create.sql (or supplied with
XRS_TABLE_SQL).
"""
import math
import os
import re
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import make_url

from database import CDR_Loader
from database.CDR_Loader import CDRLoader, _truthy, load_cdr_file, load_cdr_tree
from database.sqlalchemy_db import create_database_engine
from app.routes.xrs import XRS_AT_POINT

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")
DDL = os.environ.get("XRS_TABLE_SQL")

NS = "http://pds.nasa.gov/pds4/pds/v1"
R = 2439.4
SCALARS = [  # name, PDS4 type, numpy format
    ("met", "UnsignedMSB4", ">u4"), ("orbit_number", "UnsignedMSB4", ">u4"),
    ("actual_integration_time", "UnsignedMSB4", ">u4"), ("fov_status", "UnsignedByte", "u1"),
    ("intersection", "UnsignedByte", "u1"), ("data_quality", "UnsignedMSB4", ">u4"),
    ("solar_flare_detected", "UnsignedByte", "u1"), ("scalt", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_x", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_y", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_z", "IEEE754MSBSingle", ">f4"),
    ("solar_monitor_rate", "UnsignedMSB4", ">u4"), ("solar_monitor_spect_shift", "UnsignedMSB2", ">u2"),
    ("lvps_plus_5v", "IEEE754MSBDouble", ">f8"), ("gpc1_mg_real_gain", "IEEE754MSBSingle", ">f4"),
    ("spare", "UnsignedByte", "u1"), ("utc", "ASCII_String", "S23"),
]
GROUPS = [("solar_stability", 10), ("solar_mon_spectrum_23_253", 231), ("gpc1_mg_spectrum_10_253", 244),
          ("gpc2_al_spectrum_10_253", 244), ("gpc3_un_spectrum_10_253", 244)]


def layout():
    names, formats, offsets, pos = [], [], [], 0
    for name, _, fmt in SCALARS:
        names.append(name); formats.append(fmt); offsets.append(pos); pos += np.dtype(fmt).itemsize
    for name, reps in GROUPS:
        names.append(name); formats.append((">u2", (reps,))); offsets.append(pos); pos += 2 * reps
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": pos})


def label_xml(dtype, n):
    parts = []
    for name, ptype, fmt in SCALARS:
        parts.append(f"<Field_Binary><name>{name}</name><field_location unit=\"byte\">{dtype.fields[name][1] + 1}"
                     f"</field_location><data_type>{ptype}</data_type>"
                     f"<field_length unit=\"byte\">{np.dtype(fmt).itemsize}</field_length></Field_Binary>")
    for number, (name, reps) in enumerate(GROUPS, 1):
        parts.append(f"<Group_Field_Binary><group_number>{number}</group_number><repetitions>{reps}</repetitions>"
                     f"<group_location unit=\"byte\">{dtype.fields[name][1] + 1}</group_location>"
                     f"<group_length unit=\"byte\">{2 * reps}</group_length><Field_Binary><name>{name}</name>"
                     f"<field_location unit=\"byte\">1</field_location><data_type>UnsignedMSB2</data_type>"
                     f"<field_length unit=\"byte\">2</field_length></Field_Binary></Group_Field_Binary>")
    return (f'<?xml version="1.0"?><Product_Observational xmlns="{NS}"><Table_Binary><records>{n}</records>'
            f'<Record_Binary><record_length unit="byte">{dtype.itemsize}</record_length>{"".join(parts)}'
            f"</Record_Binary></Table_Binary></Product_Observational>")


# (lon, lat, radius, fov_status, intersection, flare)
POINTS = [(-120.0, 35.0, 2440.0, 1, 1, 1), (10.0, -80.0, R, 1, 1, 0), (179.9, 0.0, R, 3, 1, 0),
          (0.0, 0.0, 0.0, 0, 0, 0), (45.0, 10.0, 1000.0, 2, 1, 0)]


def write_day(folder: Path, name="xrscdr2013101", met0=1_000_000, points=POINTS, dup_met=False):
    folder.mkdir(parents=True, exist_ok=True)
    dtype = layout()
    rng = np.random.default_rng(7)
    rec = np.zeros(len(points), dtype=dtype)
    for i, (lon, lat, radius, fov, inter, flare) in enumerate(points):
        rec["met"][i] = met0 if dup_met else met0 + i
        rec["orbit_number"][i] = 100 + i
        rec["actual_integration_time"][i] = 300
        rec["fov_status"][i], rec["intersection"][i], rec["solar_flare_detected"][i] = fov, inter, flare
        rec["scalt"][i] = 400.5 + i
        rec["instr_boresight_mercury_x"][i] = radius * math.cos(math.radians(lat)) * math.cos(math.radians(lon))
        rec["instr_boresight_mercury_y"][i] = radius * math.cos(math.radians(lat)) * math.sin(math.radians(lon))
        rec["instr_boresight_mercury_z"][i] = radius * math.sin(math.radians(lat))
        rec["solar_monitor_rate"][i], rec["solar_monitor_spect_shift"][i] = 5000 + i, i
        rec["lvps_plus_5v"][i] = float("nan") if i == 1 else 5.0 + i
        rec["gpc1_mg_real_gain"][i] = 0.0383
        rec["spare"][i] = 9
        rec["utc"][i] = f"2013-04-11T04:{i:02d}:00.250".encode()
    for g, reps in GROUPS:
        rec[g] = rng.integers(0, 65535, (len(points), reps))
    (folder / f"{name}.dat").write_bytes(rec.tobytes())
    (folder / f"{name}.xml").write_text(label_xml(dtype, len(points)))
    return folder / f"{name}.dat", rec


def _xrs_schema_statements():
    if DDL:
        return [Path(DDL).read_text()]
    source = (Path(__file__).resolve().with_name("DB_Create.sql")).read_text()
    table = re.search(r"CREATE TABLE xrs \(.*?\n\);", source, re.DOTALL)
    if table is None:
        raise ValueError("DB_Create.sql does not define the xrs table")
    indexes = re.findall(r"CREATE INDEX xrs_[^;]+;", source)
    return [table.group(), *indexes]


@pytest.fixture
def conn():
    schema = f"test_cdr_{uuid.uuid4().hex[:8]}"
    admin_engine = create_database_engine(DSN)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    test_url = make_url(DSN)
    if test_url.drivername in {"postgres", "postgresql"}:
        test_url = test_url.set(drivername="postgresql+psycopg")
    test_url = test_url.update_query_dict({
        "options": f"-csearch_path={schema},public -ctimezone=UTC"
    })
    test_engine = create_database_engine(test_url)
    try:
        with test_engine.begin() as connection:
            for statement in _xrs_schema_statements():
                connection.exec_driver_sql(statement)
        yield test_engine
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()


def fetch(conn, sql, *args):
    with conn.connect() as connection:
        return connection.exec_driver_sql(sql, args).fetchall()


def execute(engine, sql):
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


def test_rows_are_loaded_with_expected_values(conn, tmp_path):
    dat, rec = write_day(tmp_path)
    assert CDRLoader(conn).load_file(dat) == 5
    with conn.connect() as connection:
        rows = connection.exec_driver_sql("SELECT * FROM xrs ORDER BY met").mappings().all()
    first = rows[0]
    assert (first["source_file"], first["source_id"], first["met"]) == ("xrscdr2013101.dat", "1000000", 1_000_000)
    assert first["orbit_number"] == 100 and first["fov_status"] == 1 and first["intersection"] is True
    assert first["solar_flare_detected"] is True and rows[1]["solar_flare_detected"] is False
    assert first["observed_start"].isoformat() == "2013-04-11T04:00:00.250000+00:00"
    assert (first["observed_end"] - first["observed_start"]).total_seconds() == 300
    assert first["spacecraft_altitude_km"] == pytest.approx(400.5)
    assert first["solar_monitor_rate"] == 5000 and rows[2]["solar_monitor_spect_shift"] == 2
    assert first["gpc1_mg_spectrum"] == rec["gpc1_mg_spectrum_10_253"][0].tolist()
    assert first["solar_mon_spectrum"] == rec["solar_mon_spectrum_23_253"][0].tolist()
    assert len(first["gpc2_al_spectrum"]) == len(first["gpc3_un_spectrum"]) == 244
    assert first["geometry_source"] == "pds-cdr-boresight" and first["processing_version"] == CDR_Loader.LOADER_VERSION


def test_center_comes_from_the_boresight_vector(conn, tmp_path):
    load_cdr_file(conn, write_day(tmp_path)[0])
    centers = {met: (lon, lat) for met, lon, lat in fetch(conn, "SELECT met, center_lon, center_lat FROM xrs")}
    assert centers[1_000_000] == pytest.approx((-120.0, 35.0), abs=1e-3)
    assert centers[1_000_001] == pytest.approx((10.0, -80.0), abs=1e-3)
    assert centers[1_000_002][0] == pytest.approx(179.9, abs=1e-3)       # stays inside [-180, 180]
    assert centers[1_000_003] == (None, None)                            # no intersection
    assert centers[1_000_004] == (None, None)                            # vector length not Mercury's radius
    srids = {s for (s,) in fetch(conn, "SELECT ST_SRID(center) FROM xrs WHERE center IS NOT NULL")}
    assert srids == {910001}


def test_housekeeping_holds_the_other_columns(conn, tmp_path):
    dat, rec = write_day(tmp_path)
    load_cdr_file(conn, dat)
    hk = {met: h for met, h in fetch(conn, "SELECT met, housekeeping FROM xrs")}
    row = hk[1_000_000]
    assert row["lvps_plus_5v"] == 5.0 and row["utc"] == "2013-04-11T04:00:00.250"
    assert row["actual_integration_time"] == 300 and row["solar_stability"] == rec["solar_stability"][0].tolist()
    assert row["gpc1_mg_real_gain"] == pytest.approx(0.0383, rel=1e-5)
    assert hk[1_000_001]["lvps_plus_5v"] is None                         # NaN became null
    assert "spare" not in row and "met" not in row and "gpc1_mg_spectrum_10_253" not in row


def test_housekeeping_can_be_skipped(conn, tmp_path):
    load_cdr_file(conn, write_day(tmp_path)[0], keep_housekeeping=False)
    assert {h for (h,) in fetch(conn, "SELECT housekeeping::text FROM xrs")} == {"{}"}


def test_reload_is_idempotent_and_keeps_later_additions(conn, tmp_path):
    dat, _ = write_day(tmp_path)
    load_cdr_file(conn, dat)
    execute(conn, "UPDATE xrs SET footprint = ST_Multi(ST_SetSRID(ST_MakeEnvelope(-130,25,-110,45), 910001)),"
                  " solar_intensity = 1e-5, solar_intensity_source = 'test', sclk_partition = 2 WHERE met = 1000000")
    load_cdr_file(conn, dat)
    assert fetch(conn, "SELECT count(*) FROM xrs") == [(5,)]
    assert fetch(conn, "SELECT solar_intensity, solar_intensity_source, sclk_partition, footprint IS NOT NULL"
                       " FROM xrs WHERE met = 1000000") == [(1e-5, "test", 2, True)]


def test_region_overlap_query_uses_the_footprint(conn, tmp_path):
    load_cdr_file(conn, write_day(tmp_path)[0])
    execute(conn, "UPDATE xrs SET footprint = ST_Multi(ST_SetSRID(ST_MakeEnvelope(-130,25,-110,45), 910001))"
                  " WHERE met = 1000000")
    region = "ST_SetSRID(ST_MakeEnvelope(-112,40,-100,50), 910001)"      # overlaps footprint, misses its center
    rows = fetch(conn, f"SELECT met FROM xrs WHERE solar_flare_detected AND ST_Intersects(footprint, {region})")
    assert rows == [(1_000_000,)]
    assert fetch(conn, f"SELECT met FROM xrs WHERE ST_Intersects(center, {region})") == []


def test_api_point_query_returns_matching_footprint(conn, tmp_path):
    load_cdr_file(conn, write_day(tmp_path)[0])
    execute(conn, "UPDATE xrs SET footprint = ST_Multi(ST_SetSRID("
                  "ST_MakeEnvelope(-121,34,-119,36), 910001)) WHERE met = 1000000")

    with conn.connect() as connection:
        rows = connection.execute(
            XRS_AT_POINT,
            {"lon": -120.0, "lat": 35.0, "limit": 10},
        ).mappings().all()

    assert [row["met"] for row in rows] == [1_000_000]
    assert len(rows[0]["gpc1_mg_spectrum"]) == 244


def test_duplicate_met_is_rejected_and_nothing_is_written(conn, tmp_path):
    dat, _ = write_day(tmp_path, dup_met=True)
    with pytest.raises(ValueError, match="duplicate MET"):
        load_cdr_file(conn, dat)
    assert fetch(conn, "SELECT count(*) FROM xrs") == [(0,)]


def test_tree_loader_skips_a_bad_file_and_reports_it(conn, tmp_path):
    write_day(tmp_path / "2013" / "04" / "11", "xrscdr2013101", met0=1_000_000)
    write_day(tmp_path / "2013" / "04" / "12", "xrscdr2013102", met0=2_000_000)
    bad, _ = write_day(tmp_path / "2013" / "04" / "13", "xrscdr2013103", met0=3_000_000)
    bad.write_bytes(bad.read_bytes()[:-10])                               # truncated file
    total, failures = load_cdr_tree(conn, tmp_path)
    assert total == 10 and len(failures) == 1 and "xrscdr2013103" in failures[0][0]
    assert fetch(conn, "SELECT count(DISTINCT source_file) FROM xrs") == [(2,)]


def test_truthy_accepts_numeric_and_text_encodings():
    assert _truthy(np.array([0, 1, 2], dtype="u1")).tolist() == [False, True, True]
    assert _truthy(np.array([b"1", b"T ", b"true", b"0", b"F"], dtype="S5")).tolist() == [True, True, True, False, False]