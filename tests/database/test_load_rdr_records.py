from datetime import date
from types import SimpleNamespace

import pytest

from database import load_rdr_records
from database.pds2db.pds_consts import (
    FOOTPRINT_NO_BORESIGHT,
    FOOTPRINT_UNMATCHED,
    FOOTPRINT_UNCHANGED,
    FOOTPRINT_UPDATED,
)


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

    assert downloaded == [(out.resolve(), date(2013, 4, 11))]
    assert "Found 1 CSV file(s) on disk" in capsys.readouterr().out


def test_dry_run_uses_archive_default(tmp_path, monkeypatch, capsys):
    archive_dir = tmp_path / "messenger_archive" / "xrs"
    day_dir = archive_dir / "footprints" / "2013" / "04" / "11" / "22"
    day_dir.mkdir(parents=True)
    csv_path = day_dir / "xrs_fp_2_012362249.csv"
    csv_path.touch()
    csv_path.with_suffix(".xml").touch()
    monkeypatch.setattr(load_rdr_records, "XRS_ARCHIVE_DIR", archive_dir)

    assert load_rdr_records.main(["2013-04-11", "--dry-run"]) == 0

    assert "Found 1 CSV file(s) on disk" in capsys.readouterr().out


def test_report_counts_bitmap_statuses(capsys):
    results = [
        SimpleNamespace(
            status=FOOTPRINT_UPDATED, source_file="updated.csv", summary="updated", offset_seconds=None,
        ),
        SimpleNamespace(
            status=FOOTPRINT_UNCHANGED, source_file="unchanged.csv", summary="unchanged", offset_seconds=None,
        ),
        SimpleNamespace(
            status=FOOTPRINT_UNMATCHED | FOOTPRINT_NO_BORESIGHT,
            source_file="problem.csv",
            summary="not applied",
            offset_seconds=None,
        ),
    ]

    assert load_rdr_records.report(date(2013, 4, 11), 3, results, []) == 0

    output = capsys.readouterr()
    assert "1 updated, 1 unchanged (already loaded), 1 not applied" in output.out
    assert "1 status 0x01, 1 status 0x02" in output.out
    assert "problem.csv: not applied: not applied" in output.err


def test_main_rejects_out_option():
    with pytest.raises(SystemExit) as exc_info:
        load_rdr_records.main(["2013-04-11", "--out", "custom"])

    assert exc_info.value.code == 2
