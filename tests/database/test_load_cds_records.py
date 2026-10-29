from datetime import date
from pathlib import Path

import pytest

from database import load_cdr_records


class FakeEngine:
    def dispose(self):
        pass


class SuccessfulLoader:
    def __init__(self, engine):
        pass

    def load_file(self, path):
        return 3

SAMPLE_FILE_DIR = Path(__file__).resolve().parents[1] / "sample_files"
SAMPLE_CDR_FILE = SAMPLE_FILE_DIR / "xrscdr2013101.dat"
SAMPLE_XML_FILE = SAMPLE_FILE_DIR / "xrscdr2013101.xml"


def test_main_reports_rows_as_upserted(tmp_path, monkeypatch, capsys):
    """The sample files should work"""
    downloads = []
    monkeypatch.setattr(load_cdr_records, "download_cdr_day", lambda day: downloads.append(day) or 0)
    monkeypatch.setattr(load_cdr_records, "XRS_ARCHIVE_DIR", SAMPLE_FILE_DIR)
    monkeypatch.setattr(load_cdr_records, "day_files", lambda day: [SAMPLE_CDR_FILE])
    monkeypatch.setattr(load_cdr_records, "resolve_dsn", lambda: "postgresql+psycopg://test")
    monkeypatch.setattr("sqlalchemy.create_engine", lambda dsn: FakeEngine())
    monkeypatch.setattr("database.pds2db.cdr_loader.CDRLoader", SuccessfulLoader)

    assert load_cdr_records.main(["2013-04-11"]) == 0

    assert downloads == [date(2013, 4, 11)]
    output = capsys.readouterr().out
    assert "3 records upserted (inserted or updated)" in output
    assert "3 records upserted (inserted or updated) from 1/1 file(s)" in output


def test_main_reports_database_insertion_failure(tmp_path, monkeypatch, capsys):
    """Simulate a database write failure to check that it is reported """
    monkeypatch.setattr(load_cdr_records, "XRS_ARCHIVE_DIR", SAMPLE_FILE_DIR)
    monkeypatch.setattr(load_cdr_records, "day_files", lambda day: [SAMPLE_CDR_FILE])
    monkeypatch.setattr(load_cdr_records, "resolve_dsn", lambda: "postgresql+psycopg://test")
    monkeypatch.setattr("sqlalchemy.create_engine", lambda dsn: FakeEngine())

    class FailingLoader:
        def __init__(self, engine):
            pass

        def load_file(self, path):
            raise RuntimeError("database write failed")

    monkeypatch.setattr("database.pds2db.cdr_loader.CDRLoader", FailingLoader)

    assert load_cdr_records.main(["2013-04-11", "--rerun"]) == 1

    captured = capsys.readouterr()
    assert "xrscdr2013101.dat: FAILED: database write failed" in captured.err
    assert "0/1 file(s)" in captured.out
