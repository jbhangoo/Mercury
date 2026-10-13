"""
Checks app.db.schema against the real DDL in database/DB_Create.sql.

The CREATE TABLE statement is run in a throw-away schema of the database named
by TEST_DATABASE_URL, then every column's name, type, nullability and
generated-ness is compared with the SQLAlchemy Table. Requires PostGIS with the
Mercury SRID registered (DB_Create.sql does that). Skipped if the variable is unset.
"""
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from app.db.schema import SRID, xrs

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


@pytest.fixture(scope="module")
def live_columns():
    schema = f"test_schema_{uuid.uuid4().hex[:8]}"
    url = make_url(URL)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(url)
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


def test_geometry_columns_use_the_mercury_srid(live_columns):
    for name in ("center", "footprint"):
        assert str(SRID) in live_columns[name][0]