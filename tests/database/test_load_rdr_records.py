from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from database import load_rdr_records
from database.pds2db.pds_consts import (
    FOOTPRINT_AMBIGUOUS,
    FOOTPRINT_BORESIGHT_OUTSIDE,
    FOOTPRINT_MATCHED_BY_TIME,
    FOOTPRINT_NO_BORESIGHT,
    FOOTPRINT_UNCHANGED,
    FOOTPRINT_UNMATCHED,
    FOOTPRINT_UPDATED,
)
from database.pds2db.rdr_updater import FootprintUpdate


DAY = date(2013, 4, 11)


def test_resolve_dsn_normalizes_postgresql_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost/mercury")

    assert load_rdr_records.resolve_dsn() == "postgresql+psycopg://user:pass@localhost/mercury"


def test_find_xml_label_accepts_lower_and_uppercase_extensions(tmp_path):
    csv_path = tmp_path / "xrs_fp_2_012362249.csv"
    lower = csv_path.with_suffix(".xml")
    upper = csv_path.with_suffix(".XML")

    assert load_rdr_records.find_xml_label(csv_path) is None
    lower.touch()
    assert load_rdr_records.find_xml_label(csv_path) == lower
    lower.unlink()
    upper.touch()
    assert load_rdr_records.find_xml_label(csv_path) == upper


def test_day_files_finds_sorted_footprints_for_day_only(tmp_path):
    archive = tmp_path / "archive"
    footprint_dir = archive / "footprints" / "2013" / "04" / "11" / "22"
    footprint_dir.mkdir(parents=True)
    paths = [
        footprint_dir / "xrs_fp_2_000000002.csv",
        footprint_dir / "xrs_fp_2_000000001.csv",
        archive / "footprints" / "2013" / "04" / "12" / "00" / "xrs_fp_2_000000003.csv",
        footprint_dir / "other.csv",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    assert load_rdr_records.day_files(archive, DAY) == sorted(paths[:2])
    assert load_rdr_records.day_files(tmp_path / "missing", DAY) == []


def test_download_day_forwards_product_and_date(monkeypatch, tmp_path):
    calls = []

    def fake_download_products(product, **kwargs):
        calls.append((product, kwargs))
        return 0

    monkeypatch.setattr(load_rdr_records, "download_products", fake_download_products)

    assert load_rdr_records.download_day(tmp_path, DAY) == 0
    assert calls == [("rdr", {"out": tmp_path, "start_date": DAY.isoformat(), "end_date": DAY.isoformat()})]


def test_download_only_discovers_files_without_loading(tmp_path, monkeypatch, capsys):
    out = tmp_path / "messenger_archive" / "xrs"
    day_dir = out / "footprints" / "2013" / "04" / "11" / "22"
    day_dir.mkdir(parents=True)
    csv_path = day_dir / "xrs_fp_2_012362249.csv"
    csv_path.touch()
    csv_path.with_suffix(".xml").touch()
    downloaded = []

    def fake_download_day(download_out, download_date):
        downloaded.append((download_out, download_date))
        return 0

    def fail_if_database_accessed():
        raise AssertionError("database must not be accessed")

    monkeypatch.setattr(load_rdr_records, "download_day", fake_download_day)
    monkeypatch.setattr(load_rdr_records, "resolve_dsn", fail_if_database_accessed)
    monkeypatch.setattr(load_rdr_records, "XRS_ARCHIVE_DIR", out)

    assert load_rdr_records.main(["2013-04-11", "--download-only"]) == 0
    assert downloaded == [(out, DAY)]
    assert "Found 1 CSV file(s) on disk" in capsys.readouterr().out


def test_dry_run_uses_archive_default(tmp_path, monkeypatch, capsys):
    archive_dir = tmp_path / "messenger_archive" / "xrs"
    day_dir = archive_dir / "footprints" / "2013" / "04" / "11" / "22"
    day_dir.mkdir(parents=True)
    (day_dir / "xrs_fp_2_012362249.csv").touch()
    (day_dir / "xrs_fp_2_012362249.xml").touch()
    monkeypatch.setattr(load_rdr_records, "XRS_ARCHIVE_DIR", archive_dir)

    assert load_rdr_records.main(["2013-04-11", "--dry-run"]) == 0
    assert "Found 1 CSV file(s) on disk" in capsys.readouterr().out


def test_main_runs_each_file_and_disposes_engine(tmp_path, monkeypatch, capsys):
    archive_dir = tmp_path / "messenger_archive" / "xrs"
    day_dir = archive_dir / "footprints" / "2013" / "04" / "11" / "22"
    day_dir.mkdir(parents=True)
    paths = [day_dir / "xrs_fp_2_000000001.csv", day_dir / "xrs_fp_2_000000002.csv"]
    for path in paths:
        path.touch()
        path.with_suffix(".xml").touch()
    monkeypatch.setattr(load_rdr_records, "XRS_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(load_rdr_records, "resolve_dsn", lambda: "postgresql+psycopg://test")

    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr("sqlalchemy.create_engine", lambda dsn: engine)
    update_calls = []

    class Updater:
        def __init__(self, received_engine):
            assert received_engine is engine

        def update_from_file(self, path, *, force):
            update_calls.append((path, force))
            return FootprintUpdate(path.name, FOOTPRINT_UPDATED, 300.0, offset_seconds=0.1, row_id=7)

    monkeypatch.setattr("database.pds2db.rdr_updater.RDRUpdater", Updater)
    missing_calls = []
    monkeypatch.setattr(
        load_rdr_records,
        "missing_footprints",
        lambda received_engine, day, results: (missing_calls.append((received_engine, day, results)) or ([], [])),
    )

    assert load_rdr_records.main(["2013-04-11", "--rerun", "--force"]) == 0

    assert update_calls == [(path, True) for path in paths]
    assert missing_calls[0][0:2] == (engine, DAY)
    assert len(missing_calls[0][2]) == 2
    assert engine.disposed
    output = capsys.readouterr().out
    assert "2 updated, 0 unchanged (already loaded), 0 not applied, 0 failed" in output


def test_missing_footprints_uses_utc_day_and_unreached_row_ids(monkeypatch):
    expected = [{"id": 1, "met": 100}, {"id": 2, "met": 200}, {"id": 3, "met": 300}]
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Connection()

    def rows_expecting_footprints(connection, start, end):
        calls.append((connection, start, end))
        return expected

    monkeypatch.setattr(
        "server.app.db.access.db_xrs_rows_expecting_footprints",
        rows_expecting_footprints,
    )
    results = [SimpleNamespace(row_id=1), SimpleNamespace(row_id=None), SimpleNamespace(row_id=3)]

    actual_expected, missing = load_rdr_records.missing_footprints(Engine(), DAY, results)

    assert actual_expected == expected
    assert missing == [expected[1]]
    assert calls[0][1:] == (
        datetime(2013, 4, 11, tzinfo=timezone.utc),
        datetime(2013, 4, 12, tzinfo=timezone.utc),
    )


def test_report_missing_prints_clean_summary_or_missing_mets(capsys):
    expected = [{"met": met} for met in range(8)]

    load_rdr_records.report_missing(DAY, expected, [])
    output = capsys.readouterr()
    assert "all 8 CDR row(s) with FOV status 1 or 3 were reached" in output.out
    assert output.err == ""

    load_rdr_records.report_missing(DAY, expected, expected)
    output = capsys.readouterr()
    assert "8 of 8 CDR row(s) with FOV status 1 or 3 have no footprint file" in output.err
    assert "MET 0, MET 1, MET 2, MET 3, MET 4 and 3 more" in output.err


def test_report_counts_statuses_and_returns_success_when_any_applied(capsys):
    results = [
        FootprintUpdate("updated.csv", FOOTPRINT_UPDATED, 300, 0.2),
        FootprintUpdate("unchanged.csv", FOOTPRINT_UNCHANGED, 300, 0.0),
        FootprintUpdate("unmatched.csv", FOOTPRINT_UNMATCHED, note="no CDR data"),
        FootprintUpdate("outside.csv", FOOTPRINT_BORESIGHT_OUTSIDE, 0, 0.3),
    ]

    assert load_rdr_records.report(DAY, 4, results, []) == 0

    output = capsys.readouterr()
    assert "1 updated, 1 unchanged (already loaded), 2 not applied, 0 failed" in output.out
    assert "1 status 0x01, 1 status 0x04" in output.out
    assert "median 0.2 s, largest 0.3 s" in output.out
    assert "unmatched.csv: not applied: no CDR data" in output.err


def test_report_fails_when_files_failed_or_none_were_applied(capsys):
    result = FootprintUpdate("unmatched.csv", FOOTPRINT_UNMATCHED)

    assert load_rdr_records.report(DAY, 1, [result], [("bad.csv", ValueError("invalid"))]) == 1
    assert "1 failed" in capsys.readouterr().out
    assert load_rdr_records.report(DAY, 1, [result], []) == 1
    output = capsys.readouterr()
    assert "no footprint could be applied" in output.err


def test_report_summarizes_matched_by_time_met_offsets(capsys):
    results = [
        FootprintUpdate("one.csv", FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME, 300, 0.2, met_offset=100),
        FootprintUpdate("two.csv", FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME, 300, 0.2, met_offset=200),
    ]

    assert load_rdr_records.report(DAY, 2, results, []) == 0
    assert "2 different values, from +100 to +200" in capsys.readouterr().out


def test_main_rejects_unsupported_options():
    with pytest.raises(SystemExit) as exc_info:
        load_rdr_records.main(["2013-04-11", "--out", "custom"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        load_rdr_records.main(["2013-04-11", "--match-by-time"])
    assert exc_info.value.code == 2
