from unittest.mock import MagicMock, Mock

from sqlalchemy.dialects import postgresql

from app.db import find_xrs_observations_covering_point
from server.app.db.access import db_xrs_covers_point


def test_db_xrs_covers_point_builds_spatial_detail_query():
    expected_rows = [{"id": 1}]
    engine = Mock()
    connection = MagicMock()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    engine.connect.return_value = connection_context
    connection.execute.return_value.mappings.return_value.all.return_value = expected_rows

    rows = db_xrs_covers_point(engine, 83.25, -74.875, 101)

    assert rows == expected_rows
    statement, parameters = connection.execute.call_args.args
    assert parameters == {"lon": 83.25, "lat": -74.875, "limit": 101}

    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ST_Covers" in sql
    assert "ST_SetSRID" in sql
    assert "ST_MakePoint" in sql
    assert "xrs.footprint IS NOT NULL" in sql
    assert "ORDER BY xrs.observed_start DESC, xrs.id DESC" in sql
    assert "LIMIT" in sql
    assert compiled.params["ST_SetSRID_1"] == 910001
