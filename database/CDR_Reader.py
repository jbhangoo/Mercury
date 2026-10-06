"""
Reader for MESSENGER XRS CDR daily files (xrscdrYYYYDDD.dat).

A .dat file is headerless, big-endian, fixed-width binary: one record per
observation. Its PDS4 label (the .xml next to it) defines the record layout in
a <Table_Binary> element, so the numpy layout is built from the label instead
of being hard-coded. Scalar fields become ordinary columns; repeated groups
(the spectra) become 2-D columns, e.g. rows["gpc1_mg_spectrum_10_253"] has
shape (n_records, 244).

    from CDR_Reader import CDRReader
    rows = CDRReader().read("xrscdr2010157.dat")  # label found next to the file
    rows["met"], rows["orbit_number"], rows["solar_mon_spectrum_23_253"]

Command line summary of one file:  python cdr_reader.py xrscdr2010157.dat
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import numpy as np

_BINARY_TYPES = {
    "UnsignedByte": "u1", "SignedByte": "i1",
    "UnsignedMSB2": ">u2", "UnsignedMSB4": ">u4", "UnsignedMSB8": ">u8",
    "SignedMSB2": ">i2", "SignedMSB4": ">i4", "SignedMSB8": ">i8",
    "UnsignedLSB2": "<u2", "UnsignedLSB4": "<u4", "UnsignedLSB8": "<u8",
    "SignedLSB2": "<i2", "SignedLSB4": "<i4", "SignedLSB8": "<i8",
    "IEEE754MSBSingle": ">f4", "IEEE754MSBDouble": ">f8",
    "IEEE754LSBSingle": "<f4", "IEEE754LSBDouble": "<f8",
}


def _local(tag: str) -> str:
    """Tag name without its XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name and child.text is not None:
            return child.text.strip()
    raise ValueError(f"<{_local(element.tag)}> has no <{name}> element")


def _field_format(field: ET.Element) -> str:
    name = _text(field, "name")
    data_type = _text(field, "data_type")
    length = int(_text(field, "field_length"))
    if data_type in _BINARY_TYPES:
        fmt = _BINARY_TYPES[data_type]
        if np.dtype(fmt).itemsize != length:
            raise ValueError(f"field {name!r}: {data_type} is {np.dtype(fmt).itemsize} bytes, label says {length}")
        return fmt
    if data_type.startswith("ASCII_"):
        return f"S{length}"          # kept as raw bytes; decode where needed
    raise ValueError(f"field {name!r}: unsupported data_type {data_type!r}")


def _members(parent: ET.Element):
    """(names, formats, offsets) for the fields and groups directly under
    `parent`. Offsets are 0-based and relative to the start of `parent`."""
    names, formats, offsets = [], [], []
    for child in parent:
        kind = _local(child.tag)
        if kind == "Field_Binary":
            names.append(_text(child, "name"))
            formats.append(_field_format(child))
            offsets.append(int(_text(child, "field_location")) - 1)
        elif kind == "Group_Field_Binary":
            reps = int(_text(child, "repetitions"))
            group_length = int(_text(child, "group_length"))
            if group_length % reps:
                raise ValueError(f"group {_text(child, 'group_number')}: length {group_length} not divisible by {reps}")
            each = group_length // reps
            sub_names, sub_formats, sub_offsets = _members(child)
            if len(sub_names) == 1 and isinstance(sub_formats[0], str) and sub_offsets[0] == 0 \
                    and np.dtype(sub_formats[0]).itemsize == each:
                name, fmt = sub_names[0], (sub_formats[0], (reps,))       # simple array column
            else:
                element = np.dtype({"names": sub_names, "formats": sub_formats,
                                    "offsets": sub_offsets, "itemsize": each})
                name, fmt = f"group_{_text(child, 'group_number')}", (element, (reps,))
            names.append(name)
            formats.append(fmt)
            offsets.append(int(_text(child, "group_location")) - 1)
    return names, formats, offsets


@lru_cache(maxsize=None)
def _label(xml_path: str) -> tuple[np.dtype, int]:
    root = ET.parse(xml_path).getroot()
    table = next((e for e in root.iter() if _local(e.tag) == "Table_Binary"), None)
    if table is None:
        raise ValueError(f"{xml_path}: no <Table_Binary> element")
    record = next((c for c in table if _local(c.tag) == "Record_Binary"), None)
    if record is None:
        raise ValueError(f"{xml_path}: <Table_Binary> has no <Record_Binary>")
    names, formats, offsets = _members(record)
    dtype = np.dtype({"names": names, "formats": formats, "offsets": offsets,
                      "itemsize": int(_text(record, "record_length"))})
    return dtype, int(_text(table, "records"))


def cdr_dtype(xml_path) -> np.dtype:
    """Record layout (big-endian) defined by a CDR label."""
    return _label(str(xml_path))[0]


def read_cdr(dat_path, xml_path=None, *, native: bool = True) -> np.ndarray:
    """Read one CDR day file into a numpy structured array.

    xml_path defaults to the .xml beside the .dat. With native=True the values
    are converted to the machine's byte order (the file is big-endian), which
    is what pandas, psycopg and most other libraries expect.
    """
    dat_path = Path(dat_path)
    xml_path = Path(xml_path) if xml_path else dat_path.with_suffix(".xml")
    dtype, records = _label(str(xml_path))
    size = dat_path.stat().st_size
    if size != records * dtype.itemsize:
        raise ValueError(f"{dat_path.name}: {size} bytes, but the label says {records} records "
                         f"of {dtype.itemsize} bytes ({records * dtype.itemsize})")
    rows = np.fromfile(dat_path, dtype=dtype)
    return rows.astype(dtype.newbyteorder("=")) if native else rows


class CDRReader:
    """Reusable reader for CDR files.

    Set ``native=False`` to preserve the byte order declared by the PDS label.
    The module-level ``read_cdr`` and ``cdr_dtype`` functions remain available
    for callers that prefer a functional interface.
    """

    def __init__(self, *, native: bool = True):
        self.native = native

    def read(self, dat_path, xml_path=None, *, native: bool | None = None) -> np.ndarray:
        """Read a CDR file, using this reader's byte-order setting by default."""
        return read_cdr(dat_path, xml_path, native=self.native if native is None else native)

    @staticmethod
    def dtype(xml_path) -> np.dtype:
        """Return the record layout described by a CDR label."""
        return cdr_dtype(xml_path)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rows = read_cdr(argv[1])
    print(f"{argv[1]}: {len(rows)} records, {len(rows.dtype.names)} columns, "
          f"{rows.dtype.itemsize} bytes per record")
    for name in rows.dtype.names:
        shape = rows.dtype[name].shape
        print(f"  {name}{' ' + str(shape) if shape else ''}")
    for key in ("met", "orbit_number"):
        if key in rows.dtype.names and len(rows):
            print(f"{key}: {rows[key].min()} .. {rows[key].max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))