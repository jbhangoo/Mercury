from datetime import datetime, timezone

import numpy as np

from database.pds2db.cdr_parser import parse_utc


def test_parse_utc_accepts_space_separated_fractional_seconds():
    values = np.array([b"2013 04 14 00:01:53.328"], dtype="S23")

    assert parse_utc(values) == [
        datetime(2013, 4, 14, 0, 1, 53, 328000, tzinfo=timezone.utc)
    ]


def test_parse_utc_accepts_space_separated_whole_seconds():
    values = np.array([b"2013 04 14 00:01:53"], dtype="S23")

    assert parse_utc(values) == [
        datetime(2013, 4, 14, 0, 1, 53, tzinfo=timezone.utc)
    ]


def test_parse_utc_keeps_accepting_iso_values():
    values = np.array([b"2013-04-14T00:01:53.328"], dtype="S23")

    assert parse_utc(values) == [
        datetime(2013, 4, 14, 0, 1, 53, 328000, tzinfo=timezone.utc)
    ]
