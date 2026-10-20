"""
PDS4 XML Label & CSV Reader for MESSENGER XRS RDR footprint files.

A footprint file (xrs_fp_<partition>_<MET>.csv) holds the perimeter of one
observation's field of view on the surface: one vertex per line, latitude then
east longitude, in decimal degrees (planetocentric, Mercury-fixed), with no
header line. The .xml label beside it describes the table and the observation's
start and stop times and its spacecraft clock counts. The partition and MET that
tie a footprint to its CDR row are in the file name, and the label repeats them
as "<partition>/<MET>"; read_footprint() checks that the two agree.

    from database.pds2db.rdr_reader import read_rdr, parse_footprint_name
    vertices = read_rdr("xrs_fp_2_007976872.csv")   # label found beside the file
    vertices["latitude"], vertices["longitude"]
    partition, met = parse_footprint_name("xrs_fp_2_007976872.csv")

Longitudes are returned as stored. The SIS calls them east longitudes without
stating the range (CDR geometry uses 0 to 360), so normalize them before they
meet the database's -180 to 180 convention. Pole-spanning footprints can contain
a few anomalous interior vertices (a HEALPix artifact, per the SIS); this module
reads them as they are.
"""
from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

VERTEX_DTYPE = np.dtype([("latitude", "<f8"), ("longitude", "<f8")])

# PDS4 field_delimiter values mapped to the character they stand for.
DELIMITERS = {
    "comma": ",",
    "semicolon": ";",
    "horizontal tab": "\t",
    "vertical bar": "|",
}

_NAME = re.compile(r"^xrs_fp_(\d+)_(\d+)\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class RDRLabel:
    """What a footprint's PDS4 label says about its table and observation."""
    records: int | None             # number of vertices, if the label states it
    field_names: tuple[str, ...]    # lower-case, in column order; empty if not listed
    delimiter: str                  # single character separating the columns
    start_time: datetime | None     # UTC start of the observation, if present
    stop_time: datetime | None      # UTC end of the observation, if present
    clock_start: tuple[int, int] | None   # (partition, MET) at the start of integration
    clock_stop: tuple[int, int] | None    # (partition, MET) at the end of integration


@dataclass(frozen=True)
class Footprint:
    """One footprint file: its identity, observation times and perimeter."""
    path: Path
    partition: int
    met: int
    start_time: datetime | None
    stop_time: datetime | None
    stop_met: int | None            # MET at the end of integration (same partition), if the label gives it
    vertices: np.ndarray            # structured array of VERTEX_DTYPE


def _local(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    return tag.rsplit("}", 1)[-1]


def _first_text(root: ET.Element, name: str) -> str | None:
    """Text of the first element called `name` anywhere under `root`."""
    for element in root.iter():
        if _local(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def _parse_time(text: str | None) -> datetime | None:
    if text is None:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_clock(text: str | None) -> tuple[int, int] | None:
    """(partition, MET) from a label clock count such as "2/007184992"."""
    if text is None:
        return None
    match = re.fullmatch(r"\s*(\d+)/(\d+)\s*", text)
    if not match:
        raise ValueError(f"unrecognized spacecraft clock count {text!r} (expected <partition>/<MET>)")
    return int(match.group(1)), int(match.group(2))


def parse_footprint_name(path: str | Path) -> tuple[int, int]:
    """(clock partition, MET seconds) from a footprint file name such as xrs_fp_2_007976872.csv."""
    match = _NAME.match(Path(path).name)
    if not match:
        raise ValueError(f"{Path(path).name}: not a footprint file name (expected xrs_fp_<partition>_<MET>.csv)")
    return int(match.group(1)), int(match.group(2))


def read_rdr_label(xml_path: str | Path) -> RDRLabel:
    """Parse the parts of a footprint's PDS4 label that the reader needs.

    Labels are per file and there are hundreds of thousands, so results are not cached."""
    xml_path = Path(xml_path)
    root = ET.parse(xml_path).getroot()
    table = next((e for e in root.iter() if _local(e.tag) == "Table_Delimited"), None)

    records, names, delimiter = None, (), ","
    if table is not None:
        count = _first_text(table, "records")
        records = int(count) if count else None
        delimiter_name = _first_text(table, "field_delimiter")
        if delimiter_name:
            if delimiter_name.lower() not in DELIMITERS:
                raise ValueError(f"{xml_path.name}: unsupported field_delimiter {delimiter_name!r}")
            delimiter = DELIMITERS[delimiter_name.lower()]
        fields = [e for e in table.iter() if _local(e.tag) == "Field_Delimited"]
        names = tuple((_first_text(f, "name") or "").lower() for f in fields)

    return RDRLabel(
        records=records,
        field_names=names,
        delimiter=delimiter,
        start_time=_parse_time(_first_text(root, "start_date_time")),
        stop_time=_parse_time(_first_text(root, "stop_date_time")),
        clock_start=_parse_clock(_first_text(root, "spacecraft_clock_start_count")),
        clock_stop=_parse_clock(_first_text(root, "spacecraft_clock_stop_count")),
    )


def _check_field_names(csv_name: str, names: tuple[str, ...]) -> None:
    """The SIS fixes the column order (latitude, then east longitude); fail loudly if the label disagrees."""
    if not names:
        return
    if len(names) != 2 or "lat" not in names[0] or "lon" not in names[1]:
        raise ValueError(f"{csv_name}: label lists columns {list(names)}, expected latitude then longitude")


def _validate(csv_name: str, vertices: np.ndarray) -> None:
    lat, lon = vertices["latitude"], vertices["longitude"]
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
        raise ValueError(f"{csv_name}: non-finite latitude or longitude")
    if (np.abs(lat) > 90.0 + 1e-9).any():
        raise ValueError(f"{csv_name}: latitude outside -90..90")
    if ((lon < -180.0 - 1e-9) | (lon > 360.0 + 1e-9)).any():
        raise ValueError(f"{csv_name}: longitude outside -180..360")


def read_rdr(
    csv_path: str | Path,
    xml_path: str | Path | None = None,
    *,
    validate: bool = True,
) -> np.ndarray:
    """Reads a footprint CSV into a structured array of (latitude, longitude) vertices.

    xml_path defaults to the .xml beside the CSV. The vertex count is checked
    against the label, and with validate=True the coordinates are checked to be
    finite and in range."""
    csv_path = Path(csv_path)
    xml_path = Path(xml_path) if xml_path else csv_path.with_suffix(".xml")
    return _read_vertices(csv_path, read_rdr_label(xml_path), validate)


def _read_vertices(csv_path: Path, label: RDRLabel, validate: bool) -> np.ndarray:
    _check_field_names(csv_path.name, label.field_names)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")              # numpy warns about files with no data lines
        try:
            table = np.loadtxt(csv_path, delimiter=label.delimiter, dtype=np.float64,
                               ndmin=2, comments=None)
        except ValueError as exc:
            raise ValueError(f"{csv_path.name}: cannot parse as latitude,longitude lines ({exc})") from exc
    if table.size == 0:
        table = table.reshape(0, 2)
    if table.shape[1] != 2:
        raise ValueError(f"{csv_path.name}: {table.shape[1]} columns per line, expected 2")
    if label.records is not None and label.records != len(table):
        raise ValueError(f"{csv_path.name}: {len(table)} vertices, but label says {label.records}")

    vertices = np.empty(len(table), dtype=VERTEX_DTYPE)
    vertices["latitude"], vertices["longitude"] = table[:, 0], table[:, 1]
    if validate:
        _validate(csv_path.name, vertices)
    return vertices


class RDRReader:
    """Reusable reader class for RDR footprint files."""

    def __init__(self, *, validate: bool = True):
        self.validate = validate

    def read(
        self,
        csv_path: str | Path,
        xml_path: str | Path | None = None,
        *,
        validate: bool | None = None,
    ) -> np.ndarray:
        return read_rdr(csv_path, xml_path, validate=self.validate if validate is None else validate)

    def read_footprint(
        self,
        csv_path: str | Path,
        xml_path: str | Path | None = None,
        *,
        validate: bool | None = None,
    ) -> Footprint:
        """The vertices plus everything needed to match the footprint to its CDR row."""
        csv_path = Path(csv_path)
        xml_path = Path(xml_path) if xml_path else csv_path.with_suffix(".xml")
        partition, met = parse_footprint_name(csv_path)
        label = read_rdr_label(xml_path)
        if label.clock_start is not None and label.clock_start != (partition, met):
            raise ValueError(
                f"{csv_path.name}: the file name gives clock {partition}/{met} but the label "
                f"says {label.clock_start[0]}/{label.clock_start[1]}")
        stop_met = label.clock_stop[1] if label.clock_stop and label.clock_stop[0] == partition else None
        vertices = _read_vertices(csv_path, label, self.validate if validate is None else validate)
        return Footprint(csv_path, partition, met, label.start_time, label.stop_time, stop_met, vertices)

    @staticmethod
    def label(xml_path: str | Path) -> RDRLabel:
        return read_rdr_label(xml_path)