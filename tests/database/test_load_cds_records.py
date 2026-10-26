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


def _prepare_day_files(out):
    day_dir = out / "data" / "2013" / "04" / "11"
    day_dir.mkdir(parents=True)
    (day_dir / "xrscdr2013101.dat").touch()
    (day_dir / "xrscdr2013101.xml").touch()


def test_main_reports_rows_as_upserted(tmp_path, monkeypatch, capsys):
    archive_dir = tmp_path / "messenger_archive" / "xrs"
    _prepare_day_files(archive_dir)
    monkeypatch.setattr(load_cdr_records, "XRS_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(load_cdr_records, "resolve_dsn", lambda: "postgresql+psycopg://test")
    monkeypatch.setattr("sqlalchemy.create_engine", lambda dsn: FakeEngine())
    monkeypatch.setattr("database.pds2db.cdr_loader.CDRLoader", SuccessfulLoader)

    assert load_cdr_records.main(["2013-04-11", "--rerun"]) == 0

    output = capsys.readouterr().out
    assert "3 records upserted (inserted or updated)" in output
    assert "3 records upserted (inserted or updated) from 1/1 file(s)" in output


def test_main_reports_database_insertion_failure(tmp_path, monkeypatch, capsys):
    archive_dir = tmp_path / "messenger_archive" / "xrs"
    _prepare_day_files(archive_dir)
    monkeypatch.setattr(load_cdr_records, "XRS_ARCHIVE_DIR", archive_dir)
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


def test_main_rejects_out_option():
    with pytest.raises(SystemExit) as exc_info:
        load_cdr_records.main(["2013-04-11", "--out", "custom"])

    assert exc_info.value.code == 2
