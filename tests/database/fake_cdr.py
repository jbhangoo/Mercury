"""
Builds synthetic CDR day files for loader tests: a headerless big-endian .dat of
fixed-width records plus the PDS4 .xml label that defines their layout.

    dat, records = write_day(folder, "xrscdr2013101", met0=1_000_000)

write_day() returns the .dat path and the numpy records it wrote. The default
POINTS give five observations (met0 .. met0+4) with boresights on known
longitudes/latitudes, one that misses the planet and one with a vector of the
wrong length.
"""
import math
from pathlib import Path

import numpy as np

NS = "http://pds.nasa.gov/pds4/pds/v1"
R = 2439.4
SCALARS = [  # name, PDS4 type, numpy format
    ("met", "UnsignedMSB4", ">u4"), ("orbit_number", "UnsignedMSB4", ">u4"),
    ("actual_integration_time", "UnsignedMSB4", ">u4"), ("fov_status", "UnsignedByte", "u1"),
    ("intersection", "UnsignedByte", "u1"), ("data_quality", "UnsignedMSB4", ">u4"),
    ("solar_flare_detected", "UnsignedByte", "u1"), ("scalt", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_x", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_y", "IEEE754MSBSingle", ">f4"),
    ("instr_boresight_mercury_z", "IEEE754MSBSingle", ">f4"),
    ("solar_monitor_rate", "UnsignedMSB4", ">u4"), ("solar_monitor_spect_shift", "UnsignedMSB2", ">u2"),
    ("lvps_plus_5v", "IEEE754MSBDouble", ">f8"), ("gpc1_mg_real_gain", "IEEE754MSBSingle", ">f4"),
    ("spare", "UnsignedByte", "u1"), ("utc", "ASCII_String", "S23"),
]
GROUPS = [("solar_stability", 10), ("solar_mon_spectrum_23_253", 231), ("gpc1_mg_spectrum_10_253", 244),
          ("gpc2_al_spectrum_10_253", 244), ("gpc3_un_spectrum_10_253", 244)]


def layout():
    names, formats, offsets, pos = [], [], [], 0
    for name, _, fmt in SCALARS:
        names.append(name); formats.append(fmt); offsets.append(pos); pos += np.dtype(fmt).itemsize
    for name, reps in GROUPS:
        names.append(name); formats.append((">u2", (reps,))); offsets.append(pos); pos += 2 * reps
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": pos})


def label_xml(dtype, n):
    parts = []
    for name, ptype, fmt in SCALARS:
        parts.append(f"<Field_Binary><name>{name}</name><field_location unit=\"byte\">{dtype.fields[name][1] + 1}"
                     f"</field_location><data_type>{ptype}</data_type>"
                     f"<field_length unit=\"byte\">{np.dtype(fmt).itemsize}</field_length></Field_Binary>")
    for number, (name, reps) in enumerate(GROUPS, 1):
        parts.append(f"<Group_Field_Binary><group_number>{number}</group_number><repetitions>{reps}</repetitions>"
                     f"<group_location unit=\"byte\">{dtype.fields[name][1] + 1}</group_location>"
                     f"<group_length unit=\"byte\">{2 * reps}</group_length><Field_Binary><name>{name}</name>"
                     f"<field_location unit=\"byte\">1</field_location><data_type>UnsignedMSB2</data_type>"
                     f"<field_length unit=\"byte\">2</field_length></Field_Binary></Group_Field_Binary>")
    return (f'<?xml version="1.0"?><Product_Observational xmlns="{NS}"><Table_Binary><records>{n}</records>'
            f'<Record_Binary><record_length unit="byte">{dtype.itemsize}</record_length>{"".join(parts)}'
            f"</Record_Binary></Table_Binary></Product_Observational>")


# (lon, lat, radius, fov_status, intersection, flare)
POINTS = [(-120.0, 35.0, 2440.0, 1, 1, 1), (10.0, -80.0, R, 1, 1, 0), (179.9, 0.0, R, 3, 1, 0),
          (0.0, 0.0, 0.0, 0, 0, 0), (45.0, 10.0, 1000.0, 2, 1, 0)]


def write_day(folder: Path, name="xrscdr2013101", met0=1_000_000, points=POINTS, dup_met=False):
    folder.mkdir(parents=True, exist_ok=True)
    dtype = layout()
    rng = np.random.default_rng(7)
    rec = np.zeros(len(points), dtype=dtype)
    for i, (lon, lat, radius, fov, inter, flare) in enumerate(points):
        rec["met"][i] = met0 if dup_met else met0 + i
        rec["orbit_number"][i] = 100 + i
        rec["actual_integration_time"][i] = 300
        rec["fov_status"][i], rec["intersection"][i], rec["solar_flare_detected"][i] = fov, inter, flare
        rec["scalt"][i] = 400.5 + i
        rec["instr_boresight_mercury_x"][i] = radius * math.cos(math.radians(lat)) * math.cos(math.radians(lon))
        rec["instr_boresight_mercury_y"][i] = radius * math.cos(math.radians(lat)) * math.sin(math.radians(lon))
        rec["instr_boresight_mercury_z"][i] = radius * math.sin(math.radians(lat))
        rec["solar_monitor_rate"][i], rec["solar_monitor_spect_shift"][i] = 5000 + i, i
        rec["lvps_plus_5v"][i] = float("nan") if i == 1 else 5.0 + i
        rec["gpc1_mg_real_gain"][i] = 0.0383
        rec["spare"][i] = 9
        rec["utc"][i] = f"2013-04-11T04:{i:02d}:00.250".encode()
    for g, reps in GROUPS:
        rec[g] = rng.integers(0, 65535, (len(points), reps))
    (folder / f"{name}.dat").write_bytes(rec.tobytes())
    (folder / f"{name}.xml").write_text(label_xml(dtype, len(points)))
    return folder / f"{name}.dat", rec