"""Tests for rdr_reader using synthetic footprint files in the layout the SIS describes."""
import shutil
from datetime import datetime, timezone

import numpy as np
import pytest

from database.database_consts import XRS_ARCHIVE_DIR
from database.pds2db.rdr_reader import (
    RDRReader, parse_footprint_name, read_rdr, read_rdr_label,
)

NS = "http://pds.nasa.gov/pds4/pds/v1"
REAL_LABEL = (
    XRS_ARCHIVE_DIR / "footprints" / "2013" / "04" / "02" / "00"
    / "xrs_fp_2_007184992.xml"
)


def label(records=4, delimiter="Comma", names=("latitude", "longitude"), times=True, namespace=True,
          clock="2/007976872", clock_stop="2/007977072"):
    fields = "".join(
        f"<Field_Delimited><name>{n}</name><field_number>{i}</field_number>"
        f"<data_type>ASCII_Real</data_type><maximum_field_length unit=\"byte\">13</maximum_field_length>"
        f"</Field_Delimited>" for i, n in enumerate(names, 1))
    record_info = f"<Record_Delimited><fields>{len(names)}</fields><groups>0</groups>{fields}</Record_Delimited>" if names else ""
    time_info = ("<Observation_Area><Time_Coordinates><start_date_time>2013-04-11T04:10:00.000Z</start_date_time>"
                 "<stop_date_time>2013-04-11T04:15:00Z</stop_date_time></Time_Coordinates></Observation_Area>"
                 if times else "")
    count = f"<records>{records}</records>" if records is not None else ""
    ns = f' xmlns="{NS}" xmlns:mess="http://pds.nasa.gov/pds4/mission/mess/v1"' if namespace else ""
    clock_info = (f"<Mission_Area><mess:MESSENGER><mess:spacecraft_clock_start_count>{clock}"
                  f"</mess:spacecraft_clock_start_count><mess:spacecraft_clock_stop_count>{clock_stop}"
                  f"</mess:spacecraft_clock_stop_count></mess:MESSENGER></Mission_Area>"
                  if clock and namespace else "")
    return (f'<?xml version="1.0"?><Product_Observational{ns}>{time_info}{clock_info}<File_Area_Observational>'
            f"<Table_Delimited><offset unit=\"byte\">0</offset>{count}"
            f"<record_delimiter>Carriage-Return Line-Feed</record_delimiter>"
            f"<field_delimiter>{delimiter}</field_delimiter>{record_info}</Table_Delimited>"
            f"</File_Area_Observational></Product_Observational>")


def write(tmp_path, body, name="xrs_fp_2_007976872.csv", xml=None):
    csv_path = tmp_path / name
    csv_path.write_text(body, newline="")
    csv_path.with_suffix(".xml").write_text(xml if xml is not None else label())
    return csv_path


# Fixed-width, CRLF, 13-byte fields as in the SIS sample label (29-byte rows).
PADDED = ("   12.3456789,  123.4567890\r\n   -1.0000000,  359.9999999\r\n"
          "   89.9999999,    0.0000000\r\n  -45.5000000,  180.0000000\r\n")


def test_footprint_names_give_partition_and_met():
    assert parse_footprint_name("xrs_fp_2_007976872.csv") == (2, 7976872)
    assert parse_footprint_name("/data/footprints/2011/09/02/00/XRS_FP_1_223411510.CSV") == (1, 223411510)


@pytest.mark.parametrize("name", ["xrscdr2013101.dat", "xrs_fp_2_007976872.xml", "xrs_fp__12.csv", "fp_2_12.csv"])
def test_other_file_names_are_rejected(name):
    with pytest.raises(ValueError, match="not a footprint file name"):
        parse_footprint_name(name)


def test_reads_fixed_width_crlf_vertices(tmp_path):
    vertices = read_rdr(write(tmp_path, PADDED))
    assert vertices.dtype.names == ("latitude", "longitude")
    np.testing.assert_allclose(vertices["latitude"], [12.3456789, -1.0, 89.9999999, -45.5])
    np.testing.assert_allclose(vertices["longitude"], [123.456789, 359.9999999, 0.0, 180.0])


def test_unpadded_values_and_trailing_blank_lines(tmp_path):
    vertices = read_rdr(write(tmp_path, "1.5,2.5\n3.5,4.5\n5.5,6.5\n7.5,8.5\n\n\n"))
    assert len(vertices) == 4 and vertices["longitude"][-1] == 8.5


def test_label_fields(tmp_path):
    info = read_rdr_label(write(tmp_path, PADDED).with_suffix(".xml"))
    assert info.records == 4 and info.delimiter == "," and info.field_names == ("latitude", "longitude")
    assert info.start_time == datetime(2013, 4, 11, 4, 10, tzinfo=timezone.utc)
    assert info.stop_time == datetime(2013, 4, 11, 4, 15, tzinfo=timezone.utc)


def test_label_without_times_namespace_or_field_list_still_reads(tmp_path):
    xml = label(names=(), times=False, namespace=False)
    csv_path = write(tmp_path, PADDED, xml=xml)
    info = read_rdr_label(csv_path.with_suffix(".xml"))
    assert (info.start_time, info.stop_time, info.field_names) == (None, None, ())
    assert len(read_rdr(csv_path)) == 4


def test_tab_delimited_label(tmp_path):
    csv_path = write(tmp_path, "1.0\t2.0\n3.0\t4.0\n", xml=label(records=2, delimiter="Horizontal Tab"))
    np.testing.assert_allclose(read_rdr(csv_path)["longitude"], [2.0, 4.0])


def test_unsupported_delimiter_is_rejected(tmp_path):
    csv_path = write(tmp_path, PADDED, xml=label(delimiter="Space"))
    with pytest.raises(ValueError, match="unsupported field_delimiter"):
        read_rdr(csv_path)


def test_vertex_count_must_match_the_label(tmp_path):
    with pytest.raises(ValueError, match="3 vertices, but label says 4"):
        read_rdr(write(tmp_path, "1,2\n3,4\n5,6\n"))


def test_label_without_a_record_count_skips_that_check(tmp_path):
    assert len(read_rdr(write(tmp_path, "1,2\n3,4\n5,6\n", xml=label(records=None)))) == 3


def test_label_naming_other_columns_is_rejected(tmp_path):
    csv_path = write(tmp_path, PADDED, xml=label(names=("x", "y")))
    with pytest.raises(ValueError, match="expected latitude then longitude"):
        read_rdr(csv_path)


@pytest.mark.parametrize("body, message", [
    ("1,2,3\n4,5,6\n7,8,9\n1,2,3\n", "3 columns per line"),
    ("a,b\n1,2\n3,4\n5,6\n", "cannot parse"),
])
def test_malformed_files_are_rejected(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        read_rdr(write(tmp_path, body))


@pytest.mark.parametrize("body, message", [
    ("91.0,10\n1,2\n3,4\n5,6\n", "latitude outside"),
    ("1.0,400\n1,2\n3,4\n5,6\n", "longitude outside"),
    ("nan,10\n1,2\n3,4\n5,6\n", "non-finite"),
])
def test_out_of_range_values_fail_validation_unless_switched_off(tmp_path, body, message):
    csv_path = write(tmp_path, body)
    with pytest.raises(ValueError, match=message):
        read_rdr(csv_path)
    assert len(read_rdr(csv_path, validate=False)) == 4


def test_empty_file_with_zero_records(tmp_path):
    assert len(read_rdr(write(tmp_path, "", xml=label(records=0)))) == 0


def test_missing_label_is_an_error(tmp_path):
    csv_path = tmp_path / "xrs_fp_2_007976872.csv"
    csv_path.write_text(PADDED)
    with pytest.raises(FileNotFoundError):
        read_rdr(csv_path)


def test_reader_class_returns_the_full_footprint(tmp_path):
    csv_path = write(tmp_path, PADDED)
    footprint = RDRReader().read_footprint(csv_path)
    assert (footprint.partition, footprint.met, footprint.path) == (2, 7976872, csv_path)
    assert footprint.start_time == datetime(2013, 4, 11, 4, 10, tzinfo=timezone.utc)
    assert len(footprint.vertices) == 4
    assert len(RDRReader().read(csv_path)) == 4
    assert RDRReader.label(csv_path.with_suffix(".xml")).records == 4


def test_reader_class_validation_setting_and_per_call_override(tmp_path):
    csv_path = write(tmp_path, "95,10\n1,2\n3,4\n5,6\n")
    with pytest.raises(ValueError):
        RDRReader().read(csv_path)
    assert len(RDRReader(validate=False).read(csv_path)) == 4
    with pytest.raises(ValueError):
        RDRReader(validate=False).read(csv_path, validate=True)


# --- the real label (xrs_fp_2_007184992.xml, copied from the PDS archive) ----------------------

def real_footprint(tmp_path, name="xrs_fp_2_007184992"):
    """A copy of the real label next to a synthetic 357-vertex CSV with 7-character fields."""
    if not REAL_LABEL.is_file():
        pytest.skip(f"real footprint archive label is not available: {REAL_LABEL}")
    angles = np.linspace(0, 2 * np.pi, 357, endpoint=False)
    body = "".join(f"{20 + 3 * np.sin(a):7.3f},{100 + 4 * np.cos(a):7.3f}\r\n" for a in angles)
    csv_path = tmp_path / f"{name}.csv"
    csv_path.write_text(body, newline="")
    shutil.copy(REAL_LABEL, csv_path.with_suffix(".xml"))
    return csv_path


def test_real_label_is_understood():
    if not REAL_LABEL.is_file():
        pytest.skip(f"real footprint archive label is not available: {REAL_LABEL}")
    info = read_rdr_label(REAL_LABEL)
    assert info.records == 357 and info.delimiter == "," and info.field_names == ("latitude", "longitude")
    assert info.start_time == datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc)
    assert info.stop_time == datetime(2013, 4, 2, 0, 6, 32, tzinfo=timezone.utc)
    assert info.clock_start == (2, 7184992) and info.clock_stop == (2, 7185192)


def test_real_label_with_a_matching_csv(tmp_path):
    footprint = RDRReader().read_footprint(real_footprint(tmp_path))
    assert (footprint.partition, footprint.met, footprint.stop_met) == (2, 7184992, 7185192)
    assert len(footprint.vertices) == 357
    assert footprint.vertices["latitude"].max() == pytest.approx(23.0)
    assert (footprint.stop_time - footprint.start_time).total_seconds() == 200


def test_label_and_file_name_must_agree_on_the_clock(tmp_path):
    csv_path = real_footprint(tmp_path, name="xrs_fp_2_007184993")       # label still says ...992
    with pytest.raises(ValueError, match="file name gives clock 2/7184993 but the label says 2/7184992"):
        RDRReader().read_footprint(csv_path)
    wrong_partition = real_footprint(tmp_path, name="xrs_fp_1_007184992")
    with pytest.raises(ValueError, match="file name gives clock 1/7184992"):
        RDRReader().read_footprint(wrong_partition)


def test_clock_counts_are_optional_in_the_label(tmp_path):
    csv_path = write(tmp_path, PADDED, xml=label(clock=None))
    footprint = RDRReader().read_footprint(csv_path)
    assert footprint.stop_met is None and read_rdr_label(csv_path.with_suffix(".xml")).clock_start is None


def test_malformed_clock_count_is_rejected(tmp_path):
    csv_path = write(tmp_path, PADDED, xml=label(clock="7184992"))        # no partition
    with pytest.raises(ValueError, match="unrecognized spacecraft clock count"):
        read_rdr_label(csv_path.with_suffix(".xml"))


def test_stop_clock_in_another_partition_gives_no_stop_met(tmp_path):
    csv_path = write(tmp_path, PADDED, xml=label(clock="2/007976872", clock_stop="1/000000100"))
    assert RDRReader().read_footprint(csv_path).stop_met is None