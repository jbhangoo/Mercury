"""
Tests for RDRUpdater: applying footprint files to CDR rows in a real database
(TEST_DATABASE_URL; see tests/conftest.py), and the day command's report.
"""
import shutil
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from database import load_rdr_records
from database.database_consts import XRS_ARCHIVE_DIR
from database.pds2db.pds_consts import (
    FOOTPRINT_AMBIGUOUS, FOOTPRINT_BORESIGHT_OUTSIDE, FOOTPRINT_MATCHED_BY_TIME, FOOTPRINT_NO_BORESIGHT,
    FOOTPRINT_UNCHANGED, FOOTPRINT_UNMATCHED, FOOTPRINT_UPDATED,
)
from database.pds2db.rdr_updater import FootprintUpdate, RDRUpdater
from fake_footprint import destination, ring, write_footprint

START = datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc)
# Footprint files store coordinates to 0.001 degree (about 40 m), so measured radii are good to ~0.05 km.
TOLERANCE_KM = 0.1

TEST_FOOTPRINT_PATH = XRS_ARCHIVE_DIR / "footprints" / "2013" / "04" / "11" / "00"
TEST_FOOTPRINT = ("xrs_fp_2_007963552.csv", "xrs_fp_2_007963552.xml")
TEST_FOOTPRINT_START = datetime(2013, 4, 11, 0, 19, 12, tzinfo=timezone.utc)
TEST_MET=7963552
TEST_LAT=76.4450148
TEST_LON=143.6940656

def row(engine, met=1_000_001):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT footprint_radius_km, sclk_partition, xmin::text AS version FROM xrs WHERE met = :met ORDER BY id"),
            {"met": met}).mappings().first()


def test_footprint_radius_and_partition_are_stored_on_the_matching_row(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UPDATED and result.applied and result.radius_km == pytest.approx(300, abs=TOLERANCE_KM)
    stored = row(xrs_engine, 7184992)
    assert stored["footprint_radius_km"] == pytest.approx(300, abs=TOLERANCE_KM) and stored["sclk_partition"] == 2
    assert result.summary.startswith("radius 30") and result.summary.endswith(" km stored")


def test_applying_the_same_footprint_again_writes_nothing(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40)
    updater = RDRUpdater(xrs_engine)
    csv_path = write_footprint(tmp_path, 7184992, ring(30, 40, 300))
    updater.update_from_file(csv_path)
    before = row(xrs_engine, 7184992)
    again = updater.update_from_file(csv_path)
    assert again.status == FOOTPRINT_UNCHANGED and again.applied and "already loaded" in again.summary
    assert row(xrs_engine, 7184992) == before                                    # not even rewritten (same xmin)
    forced = updater.update_from_file(csv_path, force=True)
    assert forced.status == FOOTPRINT_UPDATED and row(xrs_engine, 7184992)["version"] != before["version"]


def test_a_changed_footprint_is_applied_again(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40)
    updater = RDRUpdater(xrs_engine)
    updater.update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    result = updater.update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 350)))
    assert result.status == FOOTPRINT_UPDATED and row(xrs_engine, 7184992)["footprint_radius_km"] == pytest.approx(350, abs=TOLERANCE_KM)


def test_footprint_with_no_cdr_row_is_reported_not_raised(xrs_engine, tmp_path):
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert (result.status, result.applied, result.radius_km, result.offset_seconds) == (FOOTPRINT_UNMATCHED, 0, None, None)
    assert "no CDR data" in result.summary


def test_unmatched_footprint_says_which_cdr_rows_are_near_it_in_time(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7185092, observed_start=START + timedelta(seconds=100), boresight_lat=30, boresight_lon=40)
    insert_xrs(met=7184792, observed_start=START - timedelta(seconds=200), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UNMATCHED
    assert "the footprint's MET is 7184992" in result.summary
    assert "MET 7185092 (+100 s), MET 7184792 (-200 s)" in result.summary                 # nearest first


def test_unmatched_footprint_with_nothing_near_says_the_day_may_not_be_loaded(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START + timedelta(days=3), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UNMATCHED
    assert "no CDR rows within a day of 2013-04-02 00:03:12 UTC; is that day's CDR file loaded?" in result.summary


# --- matching on start time when the MET differs -------------------------------------------------------
PARTITION_GAP = 258_000_000        # e.g. CDR MET counted on from launch, footprint MET counted within the partition


def test_row_with_a_different_met_is_found_by_start_time_and_the_difference_is_reported(xrs_engine, insert_xrs, tmp_path):
    met = 7184992 + PARTITION_GAP
    insert_xrs(met=met, observed_start=START + timedelta(milliseconds=250), boresight_lat=30, boresight_lon=40)
    csv_path = write_footprint(tmp_path, 7184992, ring(30, 40, 300))
    result = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(csv_path)
    assert result.status == FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME and result.matched_by_time
    assert result.met_offset == PARTITION_GAP and result.offset_seconds == pytest.approx(0.25)
    assert f"matched by start time; the CDR row's MET is +{PARTITION_GAP} from the footprint's" in result.summary
    stored = row(xrs_engine, met)
    assert stored["footprint_radius_km"] == pytest.approx(300, abs=TOLERANCE_KM) and stored["sclk_partition"] == 2
    again = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(csv_path)      # the flag survives a rerun
    assert again.status == FOOTPRINT_UNCHANGED | FOOTPRINT_MATCHED_BY_TIME


def test_a_row_with_the_footprints_own_met_is_preferred_to_one_that_merely_starts_at_the_same_time(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=111, observed_start=START, boresight_lat=0, boresight_lon=0)                 # same time, other MET
    insert_xrs(met=7184992, observed_start=START + timedelta(seconds=30), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UPDATED and not result.matched_by_time and result.met_offset == 0
    assert row(xrs_engine, 111)["footprint_radius_km"] is None


def test_two_rows_at_the_same_start_time_are_ambiguous_and_nothing_is_written(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=111, observed_start=START, boresight_lat=30, boresight_lon=40)
    insert_xrs(met=222, observed_start=START + timedelta(seconds=1), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_AMBIGUOUS and not result.applied
    assert "MET 111, MET 222" in result.summary and "footprint MET 7184992" in result.summary
    assert row(xrs_engine, 111)["footprint_radius_km"] is None and row(xrs_engine, 222)["footprint_radius_km"] is None


def test_start_times_further_apart_than_the_tolerance_are_not_matched(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=111, observed_start=START + timedelta(seconds=5), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UNMATCHED and "MET 111 (+5 s)" in result.summary


def test_matching_on_start_time_is_off_unless_asked_for(xrs_engine, insert_xrs, tmp_path):
    """The SIS keys footprints to CDR rows by spacecraft clock, so a different MET is not guessed around by default."""
    insert_xrs(met=111, observed_start=START, boresight_lat=30, boresight_lon=40)
    csv_path = write_footprint(tmp_path, 7184992, ring(30, 40, 300))
    result = RDRUpdater(xrs_engine).update_from_file(csv_path)
    assert result.status == FOOTPRINT_UNMATCHED and "the footprint's MET is 7184992" in result.summary
    assert row(xrs_engine, 111)["footprint_radius_km"] is None
    assert RDRUpdater(xrs_engine, match_by_time=True).update_from_file(csv_path).status == FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME


def test_a_row_found_by_time_can_still_lack_a_boresight_point(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=111, observed_start=START, intersection=False)
    result = RDRUpdater(xrs_engine, match_by_time=True).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_NO_BORESIGHT | FOOTPRINT_MATCHED_BY_TIME and not result.applied


def test_row_whose_boresight_missed_the_planet_cannot_be_measured(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, intersection=False, fov_status=3)
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_NO_BORESIGHT and not result.applied
    assert row(xrs_engine, 7184992)["footprint_radius_km"] is None


def test_boresight_outside_the_footprint_leaves_the_row_alone(xrs_engine, insert_xrs, tmp_path):
    far = destination(30, 40, 90, 500)                                            # 200 km beyond the edge
    insert_xrs(met=7184992, observed_start=START, boresight_lat=far[0], boresight_lon=far[1])
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_BORESIGHT_OUTSIDE and not result.applied and result.radius_km == pytest.approx(200, abs=1)
    stored = row(xrs_engine, 7184992)
    assert stored["footprint_radius_km"] is None and stored["sclk_partition"] is None


def test_start_time_offset_between_cdr_row_and_label_is_reported(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START + timedelta(seconds=3), boresight_lat=30, boresight_lon=40)
    result = RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    assert result.status == FOOTPRINT_UPDATED and result.offset_seconds == pytest.approx(3.0)


def test_same_met_in_another_clock_partition_is_not_touched(xrs_engine, insert_xrs, tmp_path):
    early = insert_xrs(met=7184992, observed_start=datetime(2011, 5, 20, tzinfo=timezone.utc),
                       boresight_lat=30, boresight_lon=40, source_file="early.dat")
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40, source_file="late.dat")
    RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))
    with xrs_engine.connect() as connection:
        radii = dict(connection.execute(text("SELECT source_file, footprint_radius_km FROM xrs")).all())
    assert radii["early.dat"] is None and radii["late.dat"] == pytest.approx(300, abs=TOLERANCE_KM)


def test_footprint_whose_label_disagrees_with_its_file_name_is_an_error(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40)
    csv_path = write_footprint(tmp_path, 7184992, ring(30, 40, 300))
    renamed = csv_path.with_name("xrs_fp_2_007184993.csv")
    csv_path.rename(renamed)
    csv_path.with_suffix(".xml").rename(renamed.with_suffix(".xml"))
    with pytest.raises(ValueError, match="file name gives clock 2/7184993"):
        RDRUpdater(xrs_engine).update_from_file(renamed)


def test_real_footprint_end_to_end(xrs_engine, insert_xrs, tmp_path):
    for name in TEST_FOOTPRINT:
        shutil.copy(TEST_FOOTPRINT_PATH / name, tmp_path / name)
    insert_xrs(
        met=TEST_MET,
        observed_start=TEST_FOOTPRINT_START,
        boresight_lat=TEST_LAT,
        boresight_lon=TEST_LON,
    )
    result = RDRUpdater(xrs_engine).update_from_file(tmp_path / TEST_FOOTPRINT[0])
    assert result.status == FOOTPRINT_UPDATED and result.radius_km == pytest.approx(63.63, abs=0.05)
    assert row(xrs_engine, 7963552)["sclk_partition"] == 2


# --- the day command's report ----------------------------------------------------------------------

def update(status, name="f.csv", offset=0.0, radius=300.0):
    has_radius = status in (FOOTPRINT_UPDATED, FOOTPRINT_UNCHANGED, FOOTPRINT_BORESIGHT_OUTSIDE)
    return FootprintUpdate(name, status, radius if has_radius else None, offset)


def test_report_counts_each_outcome_and_exits_zero_when_something_was_applied(capsys):
    day = datetime(2013, 4, 2).date()
    results = [update(FOOTPRINT_UPDATED, "a.csv", 0.2), update(FOOTPRINT_UPDATED, "b.csv", -1.5),
               update(FOOTPRINT_UNCHANGED, "c.csv", 0.0), update(FOOTPRINT_UNMATCHED, "d.csv"),
               update(FOOTPRINT_NO_BORESIGHT, "e.csv", 0.1), update(FOOTPRINT_BORESIGHT_OUTSIDE, "f.csv", 0.3)]
    assert load_rdr_records.report(day, 6, results, []) == 0
    captured = capsys.readouterr()
    assert "2 updated, 1 unchanged (already loaded), 3 not applied, 0 failed, of 6 footprint file(s)" in captured.out
    assert "not applied: 1 status 0x01, 1 status 0x02, 1 status 0x04" in captured.out
    assert "median 0.2 s, largest 1.5 s" in captured.out
    assert "d.csv: not applied: no CDR data for this MET" in captured.err
    assert "f.csv: not applied: instrument angle too oblique" in captured.err


def test_report_exits_one_when_a_file_failed(capsys):
    day = datetime(2013, 4, 2).date()
    assert load_rdr_records.report(day, 2, [update(FOOTPRINT_UPDATED)], [("bad.csv", ValueError("x"))]) == 1
    assert "1 failed" in capsys.readouterr().out


def test_report_exits_one_when_nothing_could_be_applied(capsys):
    day = datetime(2013, 4, 2).date()
    results = [update(FOOTPRINT_UNMATCHED, f"{i}.csv") for i in range(8)]
    assert load_rdr_records.report(day, 8, results, []) == 1
    captured = capsys.readouterr()
    assert "no footprint could be applied; is the CDR file for this day loaded?" in captured.err
    assert "... and 3 more not applied" in captured.err
    assert "8 not applied" in captured.out


def test_report_for_an_all_unchanged_day_is_a_success(capsys):
    day = datetime(2013, 4, 2).date()
    assert load_rdr_records.report(day, 2, [update(FOOTPRINT_UNCHANGED), update(FOOTPRINT_UNCHANGED)], []) == 0


def test_report_says_how_the_mets_relate_when_footprints_were_matched_by_time(capsys):
    day = datetime(2013, 4, 2).date()
    flagged = lambda met_offset: FootprintUpdate("f.csv", FOOTPRINT_UPDATED | FOOTPRINT_MATCHED_BY_TIME, 300.0, 0.2, met_offset=met_offset)
    assert load_rdr_records.report(day, 3, [flagged(PARTITION_GAP)] * 2 + [update(FOOTPRINT_UPDATED)], []) == 0
    out = capsys.readouterr().out
    assert "2 matched by start time because no CDR row had the footprint's MET; CDR MET minus footprint MET: always +258000000" in out

    assert load_rdr_records.report(day, 2, [flagged(100), flagged(200)], []) == 0
    assert "2 different values, from +100 to +200" in capsys.readouterr().out

    assert load_rdr_records.report(day, 1, [update(FOOTPRINT_UPDATED)], []) == 0
    assert "matched by start time" not in capsys.readouterr().out


def test_report_counts_ambiguous_footprints_as_not_applied(capsys):
    day = datetime(2013, 4, 2).date()
    assert load_rdr_records.report(day, 2, [update(FOOTPRINT_UPDATED), update(FOOTPRINT_AMBIGUOUS, "x.csv")], []) == 0
    captured = capsys.readouterr()
    assert "1 not applied" in captured.out and "not applied: 1 status 0x08" in captured.out
    assert "x.csv: not applied: more than one CDR row" in captured.err


# --- which CDR rows no footprint reached ----------------------------------------------------------------

def test_rows_that_should_have_a_footprint_but_were_not_reached_are_listed(xrs_engine, insert_xrs, tmp_path):
    day = START.date()
    reached = insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40, fov_status=1)
    no_boresight = insert_xrs(met=7184993, observed_start=START + timedelta(seconds=450), fov_status=3, intersection=False)
    missed = insert_xrs(met=7184994, observed_start=START + timedelta(seconds=900), fov_status=1)
    insert_xrs(met=7184995, observed_start=START + timedelta(seconds=1350), fov_status=2)              # dark: no footprint expected
    insert_xrs(met=7184996, observed_start=START + timedelta(seconds=1800), fov_status=0)              # off planet
    insert_xrs(met=7184997, observed_start=START + timedelta(days=1), fov_status=1)                    # another day
    updater = RDRUpdater(xrs_engine)
    results = [updater.update_from_file(write_footprint(tmp_path, met, ring(30, 40, 300), start=START + timedelta(seconds=offset)))
               for met, offset in ((7184992, 0), (7184993, 450))]
    assert [r.row_id for r in results] == [reached, no_boresight]
    expected, missing = load_rdr_records.missing_footprints(xrs_engine, day, results)
    assert [r["id"] for r in expected] == [reached, no_boresight, missed]                              # only FOV status 1 or 3, this UTC day
    assert [r["id"] for r in missing] == [missed]                                                      # the row with no usable boresight was still reached


def test_nothing_is_missing_when_every_expected_row_was_reached(xrs_engine, insert_xrs, tmp_path):
    insert_xrs(met=7184992, observed_start=START, boresight_lat=30, boresight_lon=40, fov_status=1)
    results = [RDRUpdater(xrs_engine).update_from_file(write_footprint(tmp_path, 7184992, ring(30, 40, 300)))]
    expected, missing = load_rdr_records.missing_footprints(xrs_engine, START.date(), results)
    assert len(expected) == 1 and missing == []


def test_report_missing_prints_the_rows_or_a_clean_bill(capsys):
    day = datetime(2013, 4, 2).date()
    rows = [{"id": i, "met": 7184990 + i} for i in range(8)]
    load_rdr_records.report_missing(day, rows, [])
    captured = capsys.readouterr()
    assert "all 8 CDR row(s) with FOV status 1 or 3 were reached" in captured.out and captured.err == ""
    load_rdr_records.report_missing(day, rows, rows[:7])
    captured = capsys.readouterr()
    assert "7 of 8 CDR row(s) with FOV status 1 or 3 have no footprint file" in captured.err
    assert "MET 7184990, MET 7184991, MET 7184992, MET 7184993, MET 7184994 and 2 more" in captured.err