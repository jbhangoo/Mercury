"""
Checks app.db.schema against the real DDL in database/DB_Create.sql.

The CREATE TABLE statement is run in a throw-away schema of the database named
by TEST_DATABASE_URL, then every column's name, type, nullability and
generated-ness is compared with the SQLAlchemy Table. The constraints that protect the
boresight and footprint-radius columns are exercised too. Skipped if the variable is unset.
"""
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from app.db.schema import xrs

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")
DDL_FILE = Path(__file__).resolve().parents[2] / "database" / "DB_Create.sql"

CATALOG_QUERY = text("""
    SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.attgenerated = 's'
    FROM pg_attribute a
    WHERE a.attrelid = to_regclass(:table) AND a.attnum > 0 AND NOT a.attisdropped
""")


def create_table_statement() -> str:
    sql = DDL_FILE.read_text()
    match = re.search(r"^CREATE TABLE xrs \(.*?^\);", sql, re.S | re.M)
    assert match, "CREATE TABLE xrs not found in DB_Create.sql"
    return match.group(0)


def normalize(type_name: str) -> str:
    return type_name.replace(" ", "").lower()


def sqlalchemy_url():
    url = make_url(URL)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url


@pytest.fixture(scope="module")
def live_columns():
    schema = f"test_schema_{uuid.uuid4().hex[:8]}"
    engine = create_engine(sqlalchemy_url())
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}, public"))
        try:
            conn.execute(text(create_table_statement()))
            rows = conn.execute(CATALOG_QUERY, {"table": f"{schema}.xrs"}).all()
        finally:
            conn.rollback()
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            conn.commit()
    engine.dispose()
    return {name: (normalize(type_), not_null, generated) for name, type_, not_null, generated in rows}


def declared_columns():
    dialect = postgresql.dialect()
    return {
        c.name: (normalize(c.type.compile(dialect=dialect)), not c.nullable, c.computed is not None)
        for c in xrs.columns
    }


def test_same_set_of_columns(live_columns):
    declared = declared_columns()
    assert set(declared) - set(live_columns) == set(), "in schema.py but not in DB_Create.sql"
    assert set(live_columns) - set(declared) == set(), "in DB_Create.sql but not in schema.py"


def test_types_nullability_and_generated_columns_match(live_columns):
    declared = declared_columns()
    mismatches = {name: {"schema.py": declared[name], "database": live_columns[name]}
                  for name in declared if name in live_columns and declared[name] != live_columns[name]}
    # id is a bigserial: NOT NULL is implied by the primary key in both places.
    assert mismatches == {}


@pytest.fixture
def table_connection():
    """A connection whose search_path holds a fresh xrs table; everything is rolled back afterwards."""
    schema = f"test_constraints_{uuid.uuid4().hex[:8]}"
    engine = create_engine(sqlalchemy_url())
    connection = engine.connect()
    connection.execute(text(f"CREATE SCHEMA {schema}"))
    connection.execute(text(f"SET search_path TO {schema}, public"))
    connection.execute(text(create_table_statement()))
    connection.commit()
    yield connection
    connection.rollback()
    connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    connection.commit()
    connection.close()
    engine.dispose()


def insert_row(connection, **overrides):
    values = {"source_file": "f.dat", "source_id": "1", "met": 1, "orbit_number": 1,
              "observed_start": "2013-04-11T04:00:00Z", "observed_end": "2013-04-11T04:05:00Z",
              "fov_status": 1, "intersection": True, "data_quality": 0, "solar_flare_detected": False,
              **overrides}
    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    connection.execute(text(f"INSERT INTO xrs ({names}) VALUES ({binds})"), values)


@pytest.mark.parametrize("values", [
    {},                                                                            # no position at all
    {"boresight_lat": 64.6, "boresight_lon": -169.1},                              # a point
    {"boresight_lat": 64.6, "boresight_lon": -169.1, "footprint_radius_km": 303.0},
    {"boresight_lat": 90, "boresight_lon": -180},                                  # limits are allowed
    {"boresight_lat": -90, "boresight_lon": 180},
])
def test_valid_positions_are_accepted(table_connection, values):
    insert_row(table_connection, **values)


@pytest.mark.parametrize("values, why", [
    ({"boresight_lat": 91, "boresight_lon": 0}, "latitude out of range"),
    ({"boresight_lat": 0, "boresight_lon": 181}, "longitude out of range"),
    ({"boresight_lat": 10.0}, "latitude without longitude"),
    ({"boresight_lon": 10.0}, "longitude without latitude"),
    ({"footprint_radius_km": 100.0}, "radius without a boresight point"),
    ({"boresight_lat": 10, "boresight_lon": 10, "footprint_radius_km": 0}, "radius of zero"),
    ({"boresight_lat": 10, "boresight_lon": 10, "footprint_radius_km": -5}, "negative radius"),
])
def test_invalid_positions_are_rejected(table_connection, values, why):
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        insert_row(table_connection, **values)
    table_connection.rollback()