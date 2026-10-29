from datetime import date

import pytest

from database.pds2db import pds_downloader


@pytest.mark.parametrize(
    ("root", "nested"),
    [
        ("https://pds.example/cdr/data/", False),
        ("https://pds.example/rdr/data/footprints/", True),
    ],
)
def test_crawl_starts_at_target_day_and_visits_nested_directories(monkeypatch, root, nested):
    day_url = f"{root}2013/04/11/"
    hour_url = f"{day_url}22/"
    day_file = f"{day_url}product.dat"
    hour_file = f"{hour_url}footprint.csv"
    calls = []

    def list_dir(session, url):
        calls.append(url)
        if url == day_url:
            entries = [(day_file, False, 10)]
            if nested:
                entries.append((hour_url, True, None))
            return entries, None
        if url == hour_url:
            return [(hour_file, False, 20)], None
        raise AssertionError(f"unexpected directory requested: {url}")

    monkeypatch.setattr(pds_downloader, "list_dir", list_dir)

    files, errors = pds_downloader.crawl(object(), root, date(2013, 4, 11))

    assert calls[0] == day_url
    assert set(calls) == {day_url, *([hour_url] if nested else [])}
    assert errors == []
    assert files == ([(day_file, 10), (hour_file, 20)] if nested else [(day_file, 10)])


@pytest.mark.parametrize(
    ("source", "url", "extensions", "expected_path"),
    [
        (
            pds_downloader.CDR_DATA,
            "https://pds.example/cdr/data/2013/10/01/xrscdr.dat",
            pds_downloader.CDR_EXTS,
            "data/2013/10/01/xrscdr.dat",
        ),
        (
            pds_downloader.RDR_DATA,
            "https://pds.example/rdr/data/footprints/2013/10/01/22/xrs_fp.csv",
            pds_downloader.RDR_EXTS,
            "footprints/2013/10/01/22/xrs_fp.csv",
        ),
    ],
)
def test_download_maps_fixed_pds_path_to_expected_archive_layout(
    monkeypatch, capsys, tmp_path, source, url, extensions, expected_path
):
    monkeypatch.setattr(pds_downloader, "XRS_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(pds_downloader, "make_session", lambda *args, **kwargs: object())
    monkeypatch.setattr(pds_downloader, "crawl", lambda *args: ([(url, 12)], []))

    assert pds_downloader._download_files(
        date(2013, 10, 1),
        source,
        extensions,
        dry_run=True,
    ) == 0

    assert expected_path in capsys.readouterr().out
