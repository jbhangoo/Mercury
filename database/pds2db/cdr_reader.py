"""
PDS4 XML Label & Binary Data Reader for MESSENGER XRS CDR day files.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import numpy as np

# PDS4 Data Type to NumPy Format Mapping
BINARY_TYPES = {
    "UnsignedByte": "u1", "SignedByte": "i1",
    "UnsignedMSB2": ">u2", "UnsignedMSB4": ">u4", "UnsignedMSB8": ">u8",
    "SignedMSB2": ">i2", "SignedMSB4": ">i4", "SignedMSB8": ">i8",
    "UnsignedLSB2": "<u2", "UnsignedLSB4": "<u4", "UnsignedLSB8": "<u8",
    "SignedLSB2": "<i2", "SignedLSB4": "<i4", "SignedLSB8": "<i8",
    "IEEE754MSBSingle": ">f4", "IEEE754MSBDouble": ">f8",
    "IEEE754LSBSingle": "<f4", "IEEE754LSBDouble": "<f8",
}


def _local(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, name: str) -> str:
    """Find text inside a child element matching `name`."""
    for child in element:
        if _local(child.tag) == name and child.text is not None:
            return child.text.strip()
    raise ValueError(f"<{_local(element.tag)}> has no <{name}> element")


def _field_format(field: ET.Element) -> str:
    name = _text(field, "name")
    data_type = _text(field, "data_type")
    length = int(_text(field, "field_length"))
    
    if data_type in BINARY_TYPES:
        fmt = BINARY_TYPES[data_type]
        if np.dtype(fmt).itemsize != length:
            raise ValueError(
                f"field {name!r}: {data_type} is {np.dtype(fmt).itemsize} bytes, "
                f"label says {length}"
            )
        return fmt
    if data_type.startswith("ASCII_"):
        return f"S{length}"  # Raw ASCII bytes
    raise ValueError(f"field {name!r}: unsupported data_type {data_type!r}")


def _members(parent: ET.Element):
    """Recursively extract names, formats, and offsets for binary fields & groups."""
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
                raise ValueError(
                    f"group {_text(child, 'group_number')}: length {group_length} "
                    f"not divisible by {reps}"
                )
            each = group_length // reps
            sub_names, sub_formats, sub_offsets = _members(child)
            if (
                len(sub_names) == 1
                and isinstance(sub_formats[0], str)
                and sub_offsets[0] == 0
                and np.dtype(sub_formats[0]).itemsize == each
            ):
                name, fmt = sub_names[0], (sub_formats[0], (reps,))
            else:
                element = np.dtype({
                    "names": sub_names,
                    "formats": sub_formats,
                    "offsets": sub_offsets,
                    "itemsize": each
                })
                name, fmt = f"group_{_text(child, 'group_number')}", (element, (reps,))
            names.append(name)
            formats.append(fmt)
            offsets.append(int(_text(child, "group_location")) - 1)
            
    return names, formats, offsets


@lru_cache(maxsize=None)
def _parse_pds_label(xml_path: str) -> tuple[np.dtype, int]:
    """Parse the PDS4 XML label to produce the record layout and count."""
    root = ET.parse(xml_path).getroot()
    table = next((e for e in root.iter() if _local(e.tag) == "Table_Binary"), None)
    if table is None:
        raise ValueError(f"{xml_path}: no <Table_Binary> element found")
        
    record = next((c for c in table if _local(c.tag) == "Record_Binary"), None)
    if record is None:
        raise ValueError(f"{xml_path}: <Table_Binary> has no <Record_Binary>")
        
    names, formats, offsets = _members(record)
    dtype = np.dtype({
        "names": names,
        "formats": formats,
        "offsets": offsets,
        "itemsize": int(_text(record, "record_length"))
    })
    return dtype, int(_text(table, "records"))


def cdr_dtype(xml_path: str | Path) -> np.dtype:
    """Return the record layout defined by a CDR XML label."""
    return _parse_pds_label(str(xml_path))[0]


def read_cdr(
    dat_path: str | Path,
    xml_path: str | Path | None = None,
    *,
    native: bool = True
) -> np.ndarray:
    """Reads a CDR binary file (.dat) into a NumPy structured array using its XML label."""
    dat_path = Path(dat_path)
    xml_path = Path(xml_path) if xml_path else dat_path.with_suffix(".xml")
    
    dtype, records = _parse_pds_label(str(xml_path))
    size = dat_path.stat().st_size
    expected_size = records * dtype.itemsize
    
    if size != expected_size:
        raise ValueError(
            f"{dat_path.name}: {size} bytes, but label expects {records} records "
            f"of {dtype.itemsize} bytes ({expected_size} bytes total)"
        )
        
    rows = np.fromfile(dat_path, dtype=dtype)
    return rows.astype(dtype.newbyteorder("=")) if native else rows


class CDRReader:
    """Reusable reader class for CDR day files."""

    def __init__(self, *, native: bool = True):
        self.native = native

    def read(
        self,
        dat_path: str | Path,
        xml_path: str | Path | None = None,
        *,
        native: bool | None = None
    ) -> np.ndarray:
        return read_cdr(
            dat_path,
            xml_path,
            native=self.native if native is None else self.native
        )

    @staticmethod
    def dtype(xml_path: str | Path) -> np.dtype:
        return cdr_dtype(xml_path)