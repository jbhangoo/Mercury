"""Builds synthetic footprint files (a CSV of perimeter vertices plus its PDS4 .xml label) for tests."""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from database.pds2db.rdr_reader import VERTEX_DTYPE

MERCURY_RADIUS_KM = 2439.4
NS = "http://pds.nasa.gov/pds4/pds/v1"


def vertices(pairs):
    """Structured array from (lat, lon) pairs."""
    array = np.empty(len(pairs), dtype=VERTEX_DTYPE)
    array["latitude"], array["longitude"] = zip(*pairs) if pairs else ((), ())
    return array


def destination(lat, lon, bearing_degrees, distance_km):
    """The point distance_km from (lat, lon) along a great circle leaving at the given bearing (degrees)."""
    delta = distance_km / MERCURY_RADIUS_KM
    if abs(lat) > 90 - 1e-9:                    # at a pole longitude is undefined: use the bearing as the longitude
        return math.copysign(90 - math.degrees(delta), lat), bearing_degrees % 360.0
    phi, lam, b = math.radians(lat), math.radians(lon), math.radians(bearing_degrees)
    phi2 = math.asin(math.sin(phi) * math.cos(delta) + math.cos(phi) * math.sin(delta) * math.cos(b))
    lam2 = lam + math.atan2(math.sin(b) * math.sin(delta) * math.cos(phi),
                            math.cos(delta) - math.sin(phi) * math.sin(phi2))
    return math.degrees(phi2), math.degrees(lam2) % 360.0       # east longitude, 0..360 like the footprint files


def ring(lat, lon, radius_km, count=120, clockwise=False):
    """Perimeter vertices of a circle of radius_km around (lat, lon)."""
    bearings = np.linspace(0, 360, count, endpoint=False)
    if clockwise:
        bearings = bearings[::-1]
    return vertices([destination(lat, lon, b, radius_km) for b in bearings])


def label_xml(partition, met, start, stop_met, stop, records):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Product_Observational xmlns="{NS}" '
        f'xmlns:mess="http://pds.nasa.gov/pds4/mission/mess/v1"><Observation_Area><Time_Coordinates>'
        f"<start_date_time>{start:%Y-%m-%dT%H:%M:%SZ}</start_date_time>"
        f"<stop_date_time>{stop:%Y-%m-%dT%H:%M:%SZ}</stop_date_time></Time_Coordinates><Mission_Area><mess:MESSENGER>"
        f"<mess:spacecraft_clock_start_count>{partition}/{met:09d}</mess:spacecraft_clock_start_count>"
        f"<mess:spacecraft_clock_stop_count>{partition}/{stop_met:09d}</mess:spacecraft_clock_stop_count>"
        f"</mess:MESSENGER></Mission_Area></Observation_Area><File_Area_Observational><Table_Delimited>"
        f"<records>{records}</records><field_delimiter>Comma</field_delimiter><Record_Delimited>"
        f"<Field_Delimited><name>latitude</name></Field_Delimited><Field_Delimited><name>longitude</name>"
        f"</Field_Delimited></Record_Delimited></Table_Delimited></File_Area_Observational></Product_Observational>"
    )


def write_footprint(folder: Path, met: int, perimeter, *, partition=2,
                    start=datetime(2013, 4, 2, 0, 3, 12, tzinfo=timezone.utc), seconds=200) -> Path:
    """Writes xrs_fp_<partition>_<met>.csv and .xml into folder; returns the CSV path."""
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / f"xrs_fp_{partition}_{met:09d}.csv"
    csv_path.write_text("".join(f"{lat:8.3f},{lon:8.3f}\r\n" for lat, lon in zip(perimeter["latitude"], perimeter["longitude"])),
                        newline="")
    csv_path.with_suffix(".xml").write_text(
        label_xml(partition, met, start, met + seconds, start + timedelta(seconds=seconds), len(perimeter)))
    return csv_path