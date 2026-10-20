from datetime import date

from database import load_rdr_records


def test_download_only_discovers_files_without_loading(tmp_path, monkeypatch, capsys):
    out = tmp_path / "xrs_pds"
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

    assert load_rdr_records.main([
        "2013-04-11",
        "--download-only",
        "--out",
        str(out),
    ]) == 0

    assert downloaded == [(out.resolve(), date(2013, 4, 11))]
    assert "Found 1 CSV file(s) on disk" in capsys.readouterr().out
