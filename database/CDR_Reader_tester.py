"""Tests for CDR_reader using a synthetic label/data pair laid out like a real
CDR day file (adjust the import to wherever CDR_reader.py lives in your repo)."""
import numpy as np
import pytest

from database.CDR_Reader import CDRReader, cdr_dtype, read_cdr

NS = "http://pds.nasa.gov/pds4/pds/v1"
RECORD = 2755
N = 5


def field(name, number, location, dtype, length):
    return (f'<Field_Binary><name>{name}</name><field_number>{number}</field_number>'
            f'<field_location unit="byte">{location}</field_location><data_type>{dtype}</data_type>'
            f'<field_length unit="byte">{length}</field_length></Field_Binary>')


def group(number, reps, location, inner):
    return (f'<Group_Field_Binary><group_number>{number}</group_number><repetitions>{reps}</repetitions>'
            f'<fields>1</fields><groups>0</groups><group_location unit="byte">{location}</group_location>'
            f'<group_length unit="byte">{reps * 2 if "pair" not in inner else reps * 4}</group_length>{inner}</Group_Field_Binary>')


def label(records=N, extra_field="", bad_type=None):
    scalars = (field("met", 1, 1, "UnsignedMSB4", 4) + field("orbit_number", 2, 5, "UnsignedMSB4", 4)
               + field("scalt", 3, 9, bad_type or "IEEE754MSBDouble", 8)
               + field("utc", 4, 17, "ASCII_String", 24) + field("spare", 5, 41, "ASCII_String", 545))
    groups = (group(1, 231, 586, field("solar_mon_spectrum_23_253", 1, 1, "UnsignedMSB2", 2))
              + group(2, 244, 1048, field("gpc1_mg_spectrum_10_253", 1, 1, "UnsignedMSB2", 2))
              + group(3, 244, 1536, field("gpc2_al_spectrum_10_253", 1, 1, "UnsignedMSB2", 2))
              + group(4, 244, 2024, field("gpc3_un_spectrum_10_253", 1, 1, "UnsignedMSB2", 2))
              + group(5, 61, 2512, "pair" + field("lo", 1, 1, "UnsignedMSB2", 2) + field("hi", 2, 3, "UnsignedMSB2", 2)))
    return (f'<?xml version="1.0"?><Product_Observational xmlns="{NS}"><File_Area_Observational>'
            f'<Table_Binary><offset unit="byte">0</offset><records>{records}</records>'
            f'<Record_Binary><fields>5</fields><groups>5</groups><record_length unit="byte">{RECORD}</record_length>'
            f'{scalars}{groups}</Record_Binary></Table_Binary></File_Area_Observational></Product_Observational>')


def write_day(tmp_path, xml=None, nbytes=None):
    rng = np.random.default_rng(1)
    raw = bytearray()
    expected = []
    for i in range(N):
        rec = bytearray(RECORD)
        met, orbit, scalt = 1_000_000 + i, 50 + i, 400.5 + i
        rec[0:4] = met.to_bytes(4, "big")
        rec[4:8] = orbit.to_bytes(4, "big")
        rec[8:16] = np.array(scalt, ">f8").tobytes()
        rec[16:40] = f"2013-04-11T04:00:{i:02d}.000Z".ljust(24).encode()
        sm, g1 = rng.integers(0, 65535, 231), rng.integers(0, 65535, 244)
        g2, g3 = rng.integers(0, 65535, 244), rng.integers(0, 65535, 244)
        pairs = rng.integers(0, 65535, (61, 2))
        rec[585:585 + 462] = sm.astype(">u2").tobytes()
        rec[1047:1047 + 488] = g1.astype(">u2").tobytes()
        rec[1535:1535 + 488] = g2.astype(">u2").tobytes()
        rec[2023:2023 + 488] = g3.astype(">u2").tobytes()
        rec[2511:2511 + 244] = pairs.astype(">u2").tobytes()
        raw += rec
        expected.append((met, orbit, scalt, sm, g1, g2, g3, pairs))
    dat = tmp_path / "xrscdr2013101.dat"
    dat.write_bytes(bytes(raw)[:nbytes] if nbytes else bytes(raw))
    (tmp_path / "xrscdr2013101.xml").write_text(xml or label())
    return dat, expected


def test_layout_matches_label(tmp_path):
    write_day(tmp_path)
    dtype = cdr_dtype(tmp_path / "xrscdr2013101.xml")
    assert dtype.itemsize == RECORD
    assert dtype["gpc1_mg_spectrum_10_253"].shape == (244,)
    assert dtype["solar_mon_spectrum_23_253"].shape == (231,)


def test_values_round_trip(tmp_path):
    dat, expected = write_day(tmp_path)
    rows = read_cdr(dat)
    assert len(rows) == N
    for row, (met, orbit, scalt, sm, g1, g2, g3, pairs) in zip(rows, expected):
        assert row["met"] == met and row["orbit_number"] == orbit and row["scalt"] == scalt
        assert row["utc"].decode().strip().startswith("2013-04-11T04:00:")
        np.testing.assert_array_equal(row["solar_mon_spectrum_23_253"], sm)
        np.testing.assert_array_equal(row["gpc1_mg_spectrum_10_253"], g1)
        np.testing.assert_array_equal(row["gpc2_al_spectrum_10_253"], g2)
        np.testing.assert_array_equal(row["gpc3_un_spectrum_10_253"], g3)
        np.testing.assert_array_equal(row["group_5"]["lo"], pairs[:, 0])   # multi-field group
        np.testing.assert_array_equal(row["group_5"]["hi"], pairs[:, 1])


def test_reader_class_uses_configured_native_byte_order(tmp_path):
    dat, _ = write_day(tmp_path)
    reader = CDRReader(native=False)
    assert not reader.read(dat)["met"].dtype.isnative or np.little_endian is False
    assert reader.dtype(dat.with_suffix(".xml")).itemsize == RECORD


def test_native_byte_order_by_default(tmp_path):
    dat, _ = write_day(tmp_path)
    assert read_cdr(dat)["met"].dtype.isnative
    assert not read_cdr(dat, native=False)["met"].dtype.isnative or np.little_endian is False


def test_size_mismatch_is_rejected(tmp_path):
    dat, _ = write_day(tmp_path, nbytes=RECORD * N - 10)
    with pytest.raises(ValueError, match="records"):
        read_cdr(dat)


def test_unsupported_type_names_the_field(tmp_path):
    dat, _ = write_day(tmp_path, xml=label(bad_type="Weird8"))
    with pytest.raises(ValueError, match="scalt.*Weird8"):
        read_cdr(dat)