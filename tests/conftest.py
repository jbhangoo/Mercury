"""
Fixtures shared by the server and database tests.

Tests that need a real database use `xrs_engine`: it creates the xrs table from the
CREATE TABLE statement in database/DB_Create.sql inside a throw-away schema of the
database named by TEST_DATABASE_URL, and drops the schema afterwards, so existing
tables are never touched. The tests are skipped when the variable is not set.
"""
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DDL_FILE = Path(__file__).resolve().parents[1] / "database" / "DB_Create.sql"


def create_table_statement() -> str:
    match = re.search(r"^CREATE TABLE xrs \(.*?^\);", DDL_FILE.read_text(), re.S | re.M)
    assert match, "CREATE TABLE xrs not found in DB_Create.sql"
    return match.group(0)


def sqlalchemy_url(url: str):
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


@pytest.fixture
def xrs_engine():
    """An Engine whose search_path holds a fresh, empty xrs table."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    schema = f"test_xrs_{uuid.uuid4().hex[:8]}"
    admin = create_engine(sqlalchemy_url(url), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
        connection.execute(text(f"SET search_path TO {schema}, public"))
        connection.execute(text(create_table_statement()))
    engine = create_engine(sqlalchemy_url(url), connect_args={"options": f"-c search_path={schema},public"})
    yield engine
    engine.dispose()
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


@pytest.fixture
def insert_xrs(xrs_engine):
    """insert_xrs(**columns) adds one row (sensible defaults for the required columns) and returns its id."""
    counter = iter(range(1, 10_000_000))

    def insert(**overrides) -> int:
        number = next(counter)
        values = {
            "source_file": "xrscdr2013101.dat", "source_id": str(number), "met": 1_000_000 + number,
            "orbit_number": 100, "observed_start": "2013-04-11T04:00:00Z", "observed_end": "2013-04-11T04:05:00Z",
            "fov_status": 1, "intersection": True, "data_quality": 0, "solar_flare_detected": False,
            **overrides,
        }
        names = ", ".join(values)
        binds = ", ".join(f":{name}" for name in values)
        with xrs_engine.begin() as connection:
            return connection.execute(
                text(f"INSERT INTO xrs ({names}) VALUES ({binds}) RETURNING id"), values).scalar_one()

    return insert