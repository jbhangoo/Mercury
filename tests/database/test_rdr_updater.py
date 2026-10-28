from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from database.pds2db import rdr_updater
from database.pds2db.pds_consts import (
    FOOTPRINT_AMBIGUOUS,
    FOOTPRINT_BORESIGHT_OUTSIDE,
    FOOTPRINT_MATCHED_BY_TIME,
    FOOTPRINT_NO_BORESIGHT,
    FOOTPRINT_UNCHANGED,
    FOOTPRINT_UNMATCHED,
    FOOTPRINT_UPDATED,
)
from database.pds2db.rdr_updater import RDRUpdater

START = datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc)
CSV_PATH = Path("xrs_fp_2_007184992.csv")


class FakeEngine:
    @contextmanager
    def begin(self):
        yield object()


class FakeReader:
    def __init__(self, footprint):
        self.footprint = footprint
        self.calls = []

    def read_footprint(self, csv_path, xml_path):
        self.calls.append((csv_path, xml_path))
        return self.footprint


def make_footprint(**overrides):
    values = {
        "partition": 2,
        "met": 7184992,
        "start_time": START,
        "vertices": object(),
    }
    return SimpleNamespace(**(values | overrides))


def make_row(**overrides):
    values = {
        "id": 42,
        "met": 7184992,
        "observed_start": START,
        "boresight_lat": 30.0,
        "boresight_lon": 40.0,
        "footprint_radius_km": None,
        "sclk_partition": None,
    }
    return values | overrides


def configure_updater(monkeypatch, *, footprint=None, candidates=(), nearby=(), measured=None):
    reader = FakeReader(footprint or make_footprint())
    engine = FakeEngine()
    calls = {"find": [], "nearest": [], "set": [], "measure": []}

    def find(connection, start_time):
        calls["find"].append((connection, start_time))
        return list(candidates)

    def nearest(connection, when):
        calls["nearest"].append((connection, when))
        return list(nearby)

    def set_footprint(connection, row_id, partition, radius_km):
        calls["set"].append((connection, row_id, partition, radius_km))

    def footprint_radius(lat, lon, vertices):
        calls["measure"].append((lat, lon, vertices))
        return measured

    monkeypatch.setattr(rdr_updater, "db_xrs_find_for_footprint_by_time", find)
    monkeypatch.setattr(rdr_updater, "db_xrs_nearest_by_time", nearest)
    monkeypatch.setattr(rdr_updater, "db_xrs_set_footprint", set_footprint)
    monkeypatch.setattr(rdr_updater, "footprint_radius", footprint_radius)
    return RDRUpdater(engine, reader=reader), reader, calls


def test_update_from_file_reads_footprint_matches_row_and_stores_radius(monkeypatch):
    row = make_row(observed_start=START + timedelta(milliseconds=250))
    measured = SimpleNamespace(inside=True, radius_km=303.4)
    updater, reader, calls = configure_updater(monkeypatch, candidates=[row], measured=measured)

    result = updater.update_from_file(CSV_PATH, xml_path=Path("custom.xml"))

    assert reader.calls == [(CSV_PATH, Path("custom.xml"))]
    assert result.source_file == CSV_PATH.name
    assert result.status == FOOTPRINT_UPDATED and result.applied
    assert result.radius_km == 303.4
    assert result.offset_seconds == pytest.approx(0.25)
    assert result.met_offset == 0 and result.row_id == row["id"]
    assert calls["find"][0][1] == START
    assert calls["measure"] == [(30.0, 40.0, reader.footprint.vertices)]
    assert calls["set"] == [(calls["find"][0][0], row["id"], 2, 303.4)]


def test_update_from_file_reports_no_match_using_nearest_rows(monkeypatch):
    nearby = [
        {"met": 7185092, "observed_start": START + timedelta(seconds=100)},
        {"met": 7184792, "observed_start": START - timedelta(seconds=200)},
    ]
    updater, _, calls = configure_updater(monkeypatch, nearby=nearby)

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_UNMATCHED and not result.applied
    assert result.summary.endswith("MET 7185092 (+100 s), MET 7184792 (-200 s)")
    assert calls["nearest"][0][1] == START
    assert calls["measure"] == [] and calls["set"] == []


def test_update_from_file_reports_when_no_nearby_rows_exist(monkeypatch):
    updater, _, _ = configure_updater(monkeypatch)

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_UNMATCHED
    assert result.summary.endswith("no CDR rows within a day of 2013-04-02 00:03:12 UTC; is that day's CDR file loaded?")


def test_exact_met_selects_matching_row_from_multiple_time_candidates(monkeypatch):
    wanted = make_row(id=2)
    other = make_row(id=1, met=111)
    updater, _, calls = configure_updater(monkeypatch, candidates=[other, wanted],
                                          measured=SimpleNamespace(inside=True, radius_km=300))

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_UPDATED
    assert result.row_id == wanted["id"]
    assert calls["set"][0][1] == wanted["id"]


def test_multiple_candidates_without_unique_exact_met_are_ambiguous(monkeypatch):
    candidates = [make_row(met=111), make_row(id=43, met=222)]
    updater, _, calls = configure_updater(monkeypatch, candidates=candidates)

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_AMBIGUOUS and not result.applied
    assert "MET 111, MET 222" in result.summary and "footprint MET 7184992" in result.summary
    assert calls["measure"] == [] and calls["set"] == []


def test_unique_time_match_with_different_met_is_flagged(monkeypatch):
    row = make_row(met=111)
    updater, _, _ = configure_updater(monkeypatch, candidates=[row],
                                      measured=SimpleNamespace(inside=True, radius_km=300))

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME
    assert result.matched_by_time and result.met_offset == 111 - 7184992
    assert f"{111 - 7184992:+d} from the footprint's" in result.summary


def test_matched_row_without_boresight_is_not_measured(monkeypatch):
    row = make_row(boresight_lat=None, boresight_lon=None)
    updater, _, calls = configure_updater(monkeypatch, candidates=[row])

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_NO_BORESIGHT and not result.applied
    assert result.row_id == row["id"]
    assert calls["measure"] == [] and calls["set"] == []


def test_boresight_outside_footprint_is_not_stored(monkeypatch):
    row = make_row()
    updater, _, calls = configure_updater(monkeypatch, candidates=[row],
                                          measured=SimpleNamespace(inside=False, radius_km=200))

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_BORESIGHT_OUTSIDE and not result.applied
    assert result.radius_km == 200 and result.row_id == row["id"]
    assert calls["set"] == []


def test_existing_radius_and_partition_are_reported_unchanged_unless_forced(monkeypatch):
    row = make_row(footprint_radius_km=300.0, sclk_partition=2)
    updater, _, calls = configure_updater(monkeypatch, candidates=[row],
                                          measured=SimpleNamespace(inside=True, radius_km=300.0))

    result = updater.update_from_file(CSV_PATH)
    forced = updater.update_from_file(CSV_PATH, force=True)

    assert result.status == FOOTPRINT_UNCHANGED and result.applied
    assert result.summary.startswith("already loaded")
    assert forced.status == FOOTPRINT_UPDATED
    assert len(calls["set"]) == 1


def test_existing_radius_is_updated_when_measurement_or_partition_changes(monkeypatch):
    row = make_row(footprint_radius_km=300.0, sclk_partition=1)
    updater, _, calls = configure_updater(monkeypatch, candidates=[row],
                                          measured=SimpleNamespace(inside=True, radius_km=303.0))

    result = updater.update_from_file(CSV_PATH)

    assert result.status == FOOTPRINT_UPDATED
    assert calls["set"][0][2:] == (2, 303.0)


def test_missing_start_time_is_rejected_before_database_access(monkeypatch):
    updater, _, calls = configure_updater(monkeypatch, footprint=make_footprint(start_time=None))

    with pytest.raises(ValueError, match="label has no start time"):
        updater.update_from_file(CSV_PATH)

    assert calls["find"] == [] and calls["nearest"] == []
